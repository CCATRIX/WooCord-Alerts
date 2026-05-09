# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Single-file Google Cloud Function (Gen 2, Python) that bridges WooCommerce + payment-gateway webhooks to Discord. Deployed by pasting `main.py` and `requirements.txt` into the Cloud Function editor — there is no build step or package layout. README.md is the source of truth for deploy steps.

## Required environment variables

- `DISCORD_WEBHOOK_URL` — Discord webhook for customer/order notifications.
- `DISCORD_WEBHOOK_PAGOS` — Discord webhook for payment notifications.

Both must be set in the Cloud Function config; the code reads them via `os.environ.get` at request time.

## Local development

```bash
pip install -r requirements.txt
DISCORD_WEBHOOK_URL=... DISCORD_WEBHOOK_PAGOS=... \
  functions-framework --target=main_webhook_receiver --debug
```

The Postman collection `WooCommerce_Discord.json` contains anonymized fixtures for replaying webhooks against the local server (default `http://localhost:8080`), including a stress-test order ("Pedido GRANDE") that forces the 1024-char Discord field truncation. WooCommerce requests must include the `X-WC-Webhook-Topic` header — without it, the function falls through to the payment-gateway branch.

## Architecture

`main_webhook_receiver` (entry point) routes by **request shape**, not URL — a single endpoint serves all sources:

1. **WooCommerce branch** — triggered by presence of the `X-WC-Webhook-Topic` header.
   - `webhook.ping` short-circuits with `200 OK` so WooCommerce can register the webhook.
   - Topic is looked up in `WC_MAPPER` (`customer.created`, `order.created`, `order.updated`) → formatter function → POST to `DISCORD_WEBHOOK_URL`.
   - **Order filter:** `format_order_processing` returns `None` (silently drops the webhook) unless **all** the following hold:
     1. `status == "processing"` — drops `pending`/`failed`/`completed`/etc.
     2. `created_via == "checkout"` — drops admin-created, REST-API-created and subscription-renewal orders. We only notify real online sales.
     3. `date_paid` (or `date_paid_gmt`) is non-null — confirms the gateway registered the payment.
     4. `|date_modified_gmt − date_paid_gmt| ≤ ORDER_PAYMENT_WINDOW_SECONDS` (60s by default) — anti-duplicate heuristic. The real `pending → processing` transition happens in the same instant as the payment; later `order.updated` events come from background plugins (YayCurrency syncing rates, ERPs, stock plugins) that touch the order minutes later and fall outside the window.
   - Both `order.created` and `order.updated` route through the same formatter. `order.created` is normally rejected by check (1) since new orders start in `pending`; the surviving event is the `order.updated` that flips status to `processing`, and only the first one (within the time window) passes.
   - The historical workaround of subscribing to a "Custom Action" topic (`action.woocommerce_order_status_processing`) is still wired in `WC_MAPPER` for backwards compatibility, but it ships only `{action, arg}` and lacks every field the filter requires, so it is silently rejected. Use `order.updated` instead.

2. **Payment-gateway branch** — fallback when no WC header is present. Detected by payload shape: `payload.type` must be a key in `MONEI_FORMATTERS` AND `payload.accountId` must be present (the `accountId` check disambiguates from other gateways that also use `charge.succeeded` event names, e.g. Stripe). Parsed → formatted → POST to `DISCORD_WEBHOOK_PAGOS`.

`MONEI_FORMATTERS` is the type-dispatcher for Monei events. Currently routes `charge.succeeded` → green embed and `charge.failed` → red embed (with `statusCode`/`statusMessage` so the merchant can contact the customer). All other Monei lifecycle events (`charge.pending`, `charge.pending_processing`, `charge.canceled`, `charge.refunded`, etc.) fall through to a `200 "Webhook ignorado"` so Monei doesn't retry. The deliberate filter prevents publishing 3 messages per order (one per lifecycle phase) and avoids false positives when a `pending_processing` ends in `failed` after 3DS rejection.

The payment side is split deliberately into two stages: `parse_<gateway>_payload(data)` normalizes provider-specific JSON into a common dict (with `event_type`, `status_code`, `status_message` for failure context), then a per-event formatter (`format_payment_notification`, `format_payment_failed_notification`) builds the embed. **To add a new Monei event** (e.g. refunds): write a new `format_payment_<event>_notification` and register it in `MONEI_FORMATTERS` — routing is automatic. **To add a new gateway** (Redsys, Stripe, PayPal): write a `parse_<gateway>_payload` returning the same normalized keys, mirror the `<GATEWAY>_FORMATTERS` dict, and add a detection branch in `main_webhook_receiver` that distinguishes the gateway by a unique field/header.

Gotchas to preserve:
- Almost every error path returns `200` (not 4xx/5xx) so WooCommerce/Monei don't retry indefinitely. The one exception is missing `DISCORD_WEBHOOK_PAGOS`, which returns `500`.
- Monei sends `amount` in cents — `parse_monei_payload` divides by 100. New gateways need their own unit handling.
- Shipping phone falls back to billing phone when empty (`format_order_processing`).
