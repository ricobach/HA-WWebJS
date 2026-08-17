# WWebJS for Home Assistant

A Home Assistant custom integration for [wwebjs-api](https://github.com/avoylenko/wwebjs-api), designed for multiple WhatsApp sender sessions.

> [!WARNING]
> wwebjs-api uses an unofficial WhatsApp Web client. Use it at your own risk; WhatsApp may restrict or block accounts using unofficial clients.

## Features

- Home Assistant UI configuration
- Local wwebjs-api server with optional API-key authentication
- Multiple WWebJS sessions/senders
- Add an already-connected session
- Create missing sessions
- Pair new sessions using a phone-number pairing code instead of a QR code
- Send text messages to arbitrary phone numbers or raw WWebJS chat IDs

## Requirements

You need a running [wwebjs-api](https://github.com/avoylenko/wwebjs-api) instance reachable from Home Assistant.

## Installation with HACS

1. Open HACS in Home Assistant.
2. Add `https://github.com/ricobach/HA-WWebJS` as a custom repository of type **Integration**.
3. Install **WWebJS**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **WWebJS**.

## Configuration

First configure the wwebjs-api server URL and API key. Then add one or more sender sessions.

For a new or disconnected session, WWebJS requests a phone-number pairing code. In WhatsApp, use **Linked devices → Link a device → Link with phone number**, enter the displayed code, then return to Home Assistant to finish setup.

## Send a message

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Hello from Home Assistant"
```

Phone numbers are normalized to the WWebJS `@c.us` format. Raw chat IDs can also be supplied directly:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "120363012345678@g.us"
  message: "Hello group"
```

## Status

This project is under active development. The current first phase focuses on configuration, multiple sessions, pairing-code setup, and plain-text sending.

Planned next steps include session health monitoring/recovery, `notify` entities, image/media messages, and message lifecycle management.

## Issues

Please report integration bugs and feature requests in the [GitHub issue tracker](https://github.com/ricobach/HA-WWebJS/issues).

## License

MIT
