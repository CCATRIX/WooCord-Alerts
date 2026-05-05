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
   - **Order filter:** `format_order_processing` returns `None` for any status other than `processing`, which silently drops `pending`/`failed`/etc. Both `order.created` and `order.updated` route through the same formatter, so a single order typically fires twice and only the `processing` transition surfaces.

2. **Payment-gateway branch** — fallback when no WC header is present. Detected by payload shape (currently `payload.type == "charge.succeeded"` ⇒ Monei). Parsed → formatted → POST to `DISCORD_WEBHOOK_PAGOS`.

The payment side is split deliberately into two stages: `parse_<gateway>_payload(data)` normalizes provider-specific JSON into a common dict, then `format_payment_notification(parsed)` builds the Discord embed. **To add a new gateway** (Redsys, Stripe, PayPal): add a `parse_<gateway>_payload` returning the same normalized keys (`processor`, `is_live`, `order_id`, `amount`, `currency`, `customer_*`, `payment_type`), then add a detection `elif` in the payment branch of `main_webhook_receiver`. Don't fork `format_payment_notification` per gateway.

Gotchas to preserve:
- Almost every error path returns `200` (not 4xx/5xx) so WooCommerce/Monei don't retry indefinitely. The one exception is missing `DISCORD_WEBHOOK_PAGOS`, which returns `500`.
- Monei sends `amount` in cents — `parse_monei_payload` divides by 100. New gateways need their own unit handling.
- Shipping phone falls back to billing phone when empty (`format_order_processing`).
