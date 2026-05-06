import base64
import hashlib
import hmac
import logging
import os

import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("woocord")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DISCORD_WEBHOOK_PAGOS = os.environ.get("DISCORD_WEBHOOK_PAGOS")
WC_WEBHOOK_SECRET = os.environ.get("WC_WEBHOOK_SECRET")
MONEI_WEBHOOK_SECRET = os.environ.get("MONEI_WEBHOOK_SECRET")

DISCORD_FIELD_LIMIT = 1024
DISCORD_TIMEOUT = 10

# ==========================================
# 1. VERIFICACIÓN DE FIRMA (HMAC)
# ==========================================
def verify_wc_signature(raw_body: bytes, header_signature: str) -> bool:
    """WooCommerce firma con HMAC-SHA256 del cuerpo, en base64."""
    if not WC_WEBHOOK_SECRET:
        return True  # verificación desactivada
    if not header_signature:
        return False
    expected = base64.b64encode(
        hmac.new(WC_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, header_signature)


def verify_monei_signature(raw_body: bytes, header_signature: str) -> bool:
    """Monei envía 'MONEI-Signature: t=<ts>,v1=<hex>' donde v1 = HMAC-SHA256(secret, ts + '.' + body)."""
    if not MONEI_WEBHOOK_SECRET:
        return True
    if not header_signature:
        return False
    try:
        parts = dict(p.split("=", 1) for p in header_signature.split(","))
    except ValueError:
        return False
    timestamp = parts.get("t")
    received = parts.get("v1")
    if not timestamp or not received:
        return False
    signed_payload = f"{timestamp}.{raw_body.decode('utf-8', errors='replace')}".encode()
    expected = hmac.new(MONEI_WEBHOOK_SECRET.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


# ==========================================
# 2. FORMATEADORES DE WOOCOMMERCE
# ==========================================
def format_customer_created(data):
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or data.get("username", "Nuevo Usuario")
    customer_id = data.get("id", "N/A")

    return {
        "content": "👤 **Registro de Nuevo Cliente**",
        "embeds": [{
            "title": full_name,
            "color": 3066993,
            "fields": [
                {"name": "Email", "value": data.get("email", "Sin email"), "inline": False},
                {"name": "ID de Cliente", "value": str(customer_id), "inline": True}
            ]
        }]
    }


def _build_product_block(line_items):
    """Construye el bloque de productos respetando el límite de 1024 caracteres
    de Discord para el campo `value` de un embed. Si no caben todas las líneas,
    añade un sufijo '... y N producto(s) más'."""
    lines = [
        f"✅ {i.get('quantity')}x {i.get('name')} (SKU: {i.get('sku') or 'N/A'})"
        for i in line_items
    ]
    fence_open = "```md\n"
    fence_close = "\n```"
    inner_limit = DISCORD_FIELD_LIMIT - len(fence_open) - len(fence_close)
    # Reservamos siempre espacio para un posible tail "... y NNN producto(s) más"
    tail_reserve = 32

    accepted = []
    used = 0
    truncated = False
    for line in lines:
        sep = 1 if accepted else 0
        if used + sep + len(line) + tail_reserve > inner_limit:
            truncated = True
            break
        accepted.append(line)
        used += sep + len(line)

    if truncated:
        accepted.append(f"... y {len(lines) - len(accepted)} producto(s) más")

    return fence_open + "\n".join(accepted) + fence_close


def format_order_processing(data):
    if data.get("status") != "processing":
        return None

    order_id = data.get("id", "N/A")
    total = f"{data.get('total')} {data.get('currency')}"

    billing = data.get("billing") or {}
    customer_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or "N/A"
    customer_phone = billing.get("phone") or "N/A"

    shipping = data.get("shipping") or {}
    ship_name = f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip() or customer_name
    address = f"{shipping.get('address_1', 'N/A')}, {shipping.get('city', '')}".strip(", ")
    ship_phone = shipping.get("phone") or customer_phone

    product_block = _build_product_block(data.get("line_items") or [])

    return {
        "content": f"# 📦 PEDIDO LISTO PARA PROCESAR: #{order_id}",
        "embeds": [{
            "color": 15844367,
            "fields": [
                {"name": "👤 Cliente", "value": f"**Nombre:** {customer_name}\n**Email:** {billing.get('email', 'N/A')}\n**Tel:** {customer_phone}", "inline": True},
                {"name": "🚚 Destinatario", "value": f"**Nombre:** {ship_name}\n**Dirección:** {address}\n**Tel:** {ship_phone}", "inline": True},
                {"name": "🛒 Productos", "value": product_block, "inline": False},
                {"name": "💰 Total", "value": f"## {total}", "inline": False}
            ]
        }]
    }


# ==========================================
# 3. PARSEADORES DE PASARELAS DE PAGO (MODULAR)
# ==========================================
def parse_monei_payload(data):
    """Extrae y normaliza los datos del JSON de Monei (succeeded o failed)."""
    obj = data.get("object") or {}
    customer = obj.get("customer") or {}
    card = (obj.get("paymentMethod") or {}).get("card") or {}

    amount_raw = obj.get("amount") or 0
    amount_formatted = f"{amount_raw / 100:.2f}"

    return {
        "processor": "Monei",
        "event_type": data.get("type", ""),
        "is_live": bool(data.get("livemode", False)),
        "order_id": obj.get("orderId", "N/A"),
        "amount": amount_formatted,
        "currency": obj.get("currency", "EUR"),
        "customer_name": customer.get("name", "N/A"),
        "customer_email": customer.get("email", "N/A"),
        "customer_phone": customer.get("phone", "N/A"),
        "payment_type": f"{card.get('brand', 'Desconocida').capitalize()} ({card.get('type', 'desconocido').capitalize()})",
        "status_code": obj.get("statusCode") or "N/A",
        "status_message": obj.get("statusMessage") or "Sin descripción",
    }


def format_payment_notification(parsed_data):
    """Pago aprobado — embed verde."""
    env_indicator = "🟢 PRODUCCIÓN" if parsed_data["is_live"] else "🟠 PRUEBAS"

    return {
        "content": f"💸 **¡PAGO RECIBIDO!** ({parsed_data['processor']})",
        "embeds": [{
            "color": 5763719,
            "fields": [
                {"name": "💰 Monto Pagado", "value": f"**{parsed_data['amount']} {parsed_data['currency']}**", "inline": True},
                {"name": "🛒 Id_Order", "value": f"#{parsed_data['order_id']}", "inline": True},
                {"name": "💳 Método", "value": parsed_data['payment_type'], "inline": True},
                {"name": "👤 Cliente", "value": f"{parsed_data['customer_name']}\n📧 {parsed_data['customer_email']}\n📱 {parsed_data['customer_phone']}", "inline": False}
            ],
            "footer": {"text": f"Entorno: {env_indicator}"}
        }]
    }


def format_payment_failed_notification(parsed_data):
    """Pago fallido — embed rojo, incluye código + mensaje del banco para que el comercio
    pueda contactar al cliente y reintentar el cobro."""
    env_indicator = "🟢 PRODUCCIÓN" if parsed_data["is_live"] else "🟠 PRUEBAS"

    return {
        "content": f"⚠️ **PAGO FALLIDO** ({parsed_data['processor']})",
        "embeds": [{
            "color": 15548997,  # rojo Discord
            "fields": [
                {"name": "💰 Monto", "value": f"**{parsed_data['amount']} {parsed_data['currency']}**", "inline": True},
                {"name": "🛒 Id_Order", "value": f"#{parsed_data['order_id']}", "inline": True},
                {"name": "💳 Método", "value": parsed_data['payment_type'], "inline": True},
                {"name": "❌ Motivo del rechazo", "value": f"`{parsed_data['status_code']}` — {parsed_data['status_message']}", "inline": False},
                {"name": "👤 Cliente", "value": f"{parsed_data['customer_name']}\n📧 {parsed_data['customer_email']}\n📱 {parsed_data['customer_phone']}", "inline": False}
            ],
            "footer": {"text": f"Contacta al cliente para reintentar el cobro · Entorno: {env_indicator}"}
        }]
    }


# Dispatcher: qué `type` de Monei se enrutan a qué formateador.
# Para añadir más eventos (charge.refunded, charge.canceled, etc.) basta con
# crear un nuevo formateador y registrarlo aquí — el ciclo es idéntico.
MONEI_FORMATTERS = {
    "charge.succeeded": format_payment_notification,
    "charge.failed": format_payment_failed_notification,
}


# ==========================================
# 4. ENVÍO A DISCORD
# ==========================================
def send_to_discord(url, payload, source):
    """POST con manejo de errores y logging. Devuelve True si Discord aceptó."""
    try:
        resp = requests.post(url, json=payload, timeout=DISCORD_TIMEOUT)
    except requests.RequestException as exc:
        log.error("[%s] Fallo de red al enviar a Discord: %s", source, exc)
        return False
    if resp.status_code >= 300:
        log.error("[%s] Discord respondió %s: %s", source, resp.status_code, resp.text[:500])
        return False
    log.info("[%s] Notificación enviada a Discord (%s)", source, resp.status_code)
    return True


# ==========================================
# 5. ENTRY POINT
# ==========================================
WC_MAPPER = {
    "customer.created": format_customer_created,
    "order.created": format_order_processing,
    "order.updated": format_order_processing,
}


def main_webhook_receiver(request):
    """Punto de entrada para Google Cloud Functions."""
    raw_body = request.get_data() or b""
    payload = request.get_json(silent=True)

    # --- RUTA A: WEBHOOK DE WOOCOMMERCE ---
    wc_topic = request.headers.get("X-WC-Webhook-Topic")
    if wc_topic:
        if wc_topic == "webhook.ping":
            return "Ping WooCommerce OK", 200

        wc_signature = request.headers.get("X-WC-Webhook-Signature", "")
        if not verify_wc_signature(raw_body, wc_signature):
            log.warning("Firma WooCommerce inválida (topic=%s)", wc_topic)
            return "Firma inválida", 401

        if not DISCORD_WEBHOOK_URL:
            log.error("Falta DISCORD_WEBHOOK_URL en variables de entorno")
            return "Configuración incompleta", 500
        if not payload:
            log.warning("Payload WooCommerce vacío (topic=%s)", wc_topic)
            return "Payload vacío", 200

        formatter = WC_MAPPER.get(wc_topic)
        if not formatter:
            log.info("Topic WooCommerce no manejado: %s", wc_topic)
            return "Topic ignorado", 200

        discord_payload = formatter(payload)
        if discord_payload:
            send_to_discord(DISCORD_WEBHOOK_URL, discord_payload, f"WC:{wc_topic}")
        return "Procesado WooCommerce", 200

    # --- RUTA B: WEBHOOK DE PASARELA DE PAGO ---
    if not payload:
        return "Webhook ignorado (sin payload)", 200

    # Detección Monei: tipo soportado + accountId presente (campo único de su API)
    monei_type = payload.get("type")
    if monei_type in MONEI_FORMATTERS and payload.get("accountId"):
        monei_signature = request.headers.get("MONEI-Signature", "")
        if not verify_monei_signature(raw_body, monei_signature):
            log.warning("Firma Monei inválida (id=%s, type=%s)", payload.get("id"), monei_type)
            return "Firma inválida", 401

        if not DISCORD_WEBHOOK_PAGOS:
            log.error("Falta DISCORD_WEBHOOK_PAGOS en variables de entorno")
            return "Configuración incompleta", 500

        parsed_data = parse_monei_payload(payload)
        formatter = MONEI_FORMATTERS[monei_type]
        discord_payload = formatter(parsed_data)
        send_to_discord(DISCORD_WEBHOOK_PAGOS, discord_payload, f"Monei:{monei_type}")
        return f"Procesado Monei {monei_type}", 200

    log.info("Webhook ignorado (formato no reconocido o type Monei no manejado): type=%s",
             payload.get("type"))
    return "Webhook ignorado (Formato no reconocido)", 200
