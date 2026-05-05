# 🛒 WooCord Alerts (WooCommerce to Discord Bridge)

Una función Serverless (Google Cloud Functions) escrita en **Python** que intercepta Webhooks de WooCommerce y pasarelas de pago (como Monei o Redsys), los formatea en mensajes ricos (embeds) y los envía a canales de Discord específicos.

## ✨ Características

* **Enrutamiento Inteligente:** Separa las notificaciones. Los pedidos van a un canal (ej. `#pedidos`) y los pagos a otro (ej. `#finanzas`).
* **Soporte Nativo para WooCommerce:** Lee webhooks de `customer.created`, `order.created` y `order.updated`.
* **Filtro de Estados:** Solo notifica pedidos cuando cambian al estado `processing` para evitar spam con pedidos pendientes o fallidos.
* **Módulo de Pasarelas de Pago:** Formateador integrado para notificaciones directas desde pasarelas de pago (actualmente soporta Monei).
* **Manejo del "Ping":** Responde automáticamente con `200 OK` a los pings de verificación de WooCommerce para permitir la creación fácil de webhooks.

## 🚀 Requisitos Previos

* Una cuenta en [Google Cloud Platform](https://console.cloud.google.com/).
* Servidor de Discord con permisos para crear Webhooks (Ajustes del servidor > Integraciones > Webhooks).
* Tienda online con WooCommerce.

## 🛠️ Instalación y Despliegue en Google Cloud

1. Entra a **Google Cloud Functions** y haz clic en **Crear Función**.
2. Configura los parámetros básicos:
   * **Entorno:** Cloud Run functions (Generación 2)
   * **Activador:** HTTP (Permitir invocaciones sin autenticar).
3. En la sección **Variables de Entorno**, añade:
   * `DISCORD_WEBHOOK_URL`: (Tu URL de Discord para clientes y pedidos)
   * `DISCORD_WEBHOOK_PAGOS`: (Tu URL de Discord para pagos entrantes)
4. En la configuración de Código:
   * **Runtime:** Python 3.12 o superior.
   * **Punto de entrada (Entry point):** `main_webhook_receiver`
5. Copia el contenido de `main.py` y `requirements.txt` de este repositorio en el editor de Google Cloud.
6. Haz clic en **Implementar (Deploy)**.

## 📦 Configuración en WooCommerce

1. Copia la **URL del activador** que te da Google Cloud al terminar el despliegue.
2. En WordPress, ve a **WooCommerce > Ajustes > Avanzado > Webhooks**.
3. Añade webhooks con los siguientes temas (topics), todos apuntando a la URL de tu Cloud Function:
   * Cliente creado (`customer.created`)
   * Pedido creado (`order.created`)
   * Pedido actualizado (`order.updated`)

## 💳 Configuración en Monei (Opcional)

Si utilizas Monei como pasarela, puedes recibir notificaciones de pagos directamente:
1. Ve al panel de control de Monei > Configuración > Webhooks.
2. Pega la misma URL de tu Google Cloud Function.
3. El código detectará automáticamente que es un pago (`charge.succeeded`) y lo enviará al canal configurado en `DISCORD_WEBHOOK_PAGOS`.

## 📂 Archivos del Proyecto

* `main.py`: Lógica principal, formateadores modulares de WooCommerce y pasarelas de pago.
* `requirements.txt`: Dependencias necesarias (`requests`, `functions-framework`).
* `WooCommerce_Discord.json`: (Opcional) Colección de Postman para realizar pruebas locales sin necesidad de crear pedidos reales.

## 🤝 Contribuciones

¡Las contribuciones son bienvenidas! El flujo recomendado para añadir una nueva pasarela de pago (Redsys, Stripe, PayPal, etc.) es:

1. **Haz un fork** del repositorio en tu cuenta de GitHub.
2. **Clona tu fork** y crea una rama con un nombre descriptivo:
   ```bash
   git checkout -b feat/parser-redsys
   ```
3. En `main.py`, añade una función `parse_<pasarela>_payload(data)` que devuelva el mismo diccionario normalizado que `parse_monei_payload` (claves: `processor`, `is_live`, `order_id`, `amount`, `currency`, `customer_name`, `customer_email`, `customer_phone`, `payment_type`). Reutiliza `format_payment_notification` — **no** dupliques el formateador.
4. En `main_webhook_receiver`, añade un `elif` en la rama de pasarelas de pago que detecte el payload por su forma (campo único, header propio, etc.) y llame a tu nuevo parser.
5. Prueba localmente con `functions-framework` (ver sección siguiente) usando un payload real de la pasarela.
6. Haz commit, push a tu fork y abre un **Pull Request** contra la rama `main` de este repositorio describiendo el cambio.

## 🧪 Pruebas locales

```bash
pip install -r requirements.txt
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
DISCORD_WEBHOOK_PAGOS="https://discord.com/api/webhooks/..." \
  functions-framework --target=main_webhook_receiver --debug
```

La función queda escuchando en `http://localhost:8080`. Puedes simular llamadas con `curl`, Postman (importando `WooCommerce_Discord.json`) o cualquier cliente HTTP. Para que la rama de WooCommerce se active recuerda enviar el header `X-WC-Webhook-Topic` (`order.created`, `order.updated` o `customer.created`).

---

## 📋 Ejemplos de payloads de referencia

Los siguientes JSON son ejemplos **anonimizados** del formato real que envían WooCommerce y Monei. Útiles para construir tests, replays o entender qué campos lee cada formateador.

### Monei — `charge.succeeded`

```json
{
  "id": "00000000000000000000000000000000",
  "type": "charge.succeeded",
  "livemode": true,
  "accountId": "00000000-0000-0000-0000-000000000000",
  "objectType": "charge",
  "objectId": "0000000000000000000000000000000000000000",
  "createdAt": 1700000000,
  "object": {
    "id": "0000000000000000000000000000000000000000",
    "accountId": "00000000-0000-0000-0000-000000000000",
    "createdAt": 1700000000,
    "updatedAt": 1700000000,
    "amount": 5065,
    "authorizationCode": "XXXXXX",
    "currency": "EUR",
    "customer": {
      "phone": "+340000000000",
      "name": "NOMBRE APELLIDO",
      "email": "cliente@example.com"
    },
    "livemode": true,
    "orderId": "000000000000",
    "paymentMethod": {
      "method": "card",
      "card": {
        "country": "ES",
        "last4": "0000",
        "threeDSecure": true,
        "type": "debit",
        "threeDSecureVersion": "2.2.0",
        "threeDSecureStatus": "Y",
        "tokenized": true,
        "bank": "Banco Ejemplo",
        "cardholderEmail": "cliente@example.com",
        "cardholderName": "NOMBRE APELLIDO",
        "expiration": 1800000000,
        "brand": "mastercard"
      }
    },
    "shop": {
      "country": "ES",
      "name": "mitienda"
    },
    "status": "SUCCEEDED",
    "statusCode": "E000",
    "statusMessage": "Transaction approved"
  }
}
```

### Monei — `charge.pending_processing` (ignorado por el código actual)

```json
{
  "id": "00000000000000000000000000000000",
  "type": "charge.pending_processing",
  "livemode": true,
  "objectType": "charge",
  "object": {
    "amount": 5065,
    "currency": "EUR",
    "customer": {
      "phone": "+340000000000",
      "name": "NOMBRE APELLIDO",
      "email": "cliente@example.com"
    },
    "orderId": "000000000000",
    "status": "PENDING_PROCESSING"
  }
}
```

### WooCommerce — `order.updated` con estado `pending` (ignorado por el filtro)

```json
{
  "id": 1001,
  "status": "pending",
  "currency": "EUR",
  "total": "6.70",
  "customer_id": 100,
  "billing": {
    "first_name": "Nombre",
    "last_name": "Apellido",
    "address_1": "Calle Ejemplo 1",
    "city": "Ciudad",
    "postcode": "00000",
    "country": "ES",
    "email": "cliente@example.com",
    "phone": "+340000000000"
  },
  "shipping": {
    "first_name": "Destinatario",
    "last_name": "Ejemplo",
    "address_1": "Calle Envío 1",
    "city": "Ciudad",
    "postcode": "00000",
    "country": "ES",
    "phone": ""
  },
  "line_items": [
    {
      "id": 1,
      "name": "Producto de ejemplo",
      "quantity": 1,
      "total": "6.70",
      "sku": "SKU-0001"
    }
  ]
}
```

### WooCommerce — `order.updated` con estado `processing` (este sí dispara el embed)

```json
{
  "id": 1001,
  "status": "processing",
  "currency": "EUR",
  "total": "6.70",
  "date_paid": "2026-01-01T12:00:00",
  "customer_id": 100,
  "billing": {
    "first_name": "Nombre",
    "last_name": "Apellido",
    "address_1": "Calle Ejemplo 1",
    "city": "Ciudad",
    "postcode": "00000",
    "country": "ES",
    "email": "cliente@example.com",
    "phone": "+340000000000"
  },
  "shipping": {
    "first_name": "Destinatario",
    "last_name": "Ejemplo",
    "address_1": "Calle Envío 1",
    "city": "Ciudad",
    "postcode": "00000",
    "country": "ES",
    "phone": ""
  },
  "line_items": [
    {
      "id": 1,
      "name": "Producto de ejemplo",
      "quantity": 1,
      "total": "6.70",
      "sku": "SKU-0001"
    }
  ]
}
```

> ⚠️ Todos los nombres, emails, teléfonos, direcciones, IDs y números de tarjeta son ficticios. Si añades nuevos ejemplos al repositorio, anonimízalos antes de hacer commit.

---
*Desarrollado para optimizar el flujo de trabajo en E-commerce.*
