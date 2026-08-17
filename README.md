# HA-WWebJS

Home Assistant integration for [wwebjs-api](https://github.com/avoylenko/wwebjs-api).

Phase 1 includes:

- UI configuration for the WWebJS API server and API key
- Multiple WWebJS sender sessions
- Existing connected session setup
- New session creation with phone-number pairing codes
- Plain text messages via `wwebjs.send_message`

## Send a text message

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Hello from Home Assistant"
```

> WWebJS uses an unofficial WhatsApp Web client. Review the upstream project's warnings before relying on it for critical messaging.
