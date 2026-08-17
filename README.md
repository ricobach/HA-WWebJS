# WWebJS for Home Assistant

A Home Assistant custom integration for [wwebjs-api](https://github.com/avoylenko/wwebjs-api), designed for multiple WhatsApp sender sessions.

> [!WARNING]
> wwebjs-api uses an unofficial WhatsApp Web client. Use it at your own risk; WhatsApp may restrict or block accounts using unofficial clients.

## Features

- Home Assistant UI configuration
- Multiple WWebJS sessions / senders
- Phone-number pairing codes
- Plain text messages
- Images, video, audio and document media from HTTP(S) URLs or local files
- Session health monitoring
- Automatic restart after three consecutive unhealthy checks
- Five-minute restart cooldown to avoid restart loops
- Persisted message cleanup across Home Assistant restarts
- Delete messages after a timeout
- Delete messages after a timeout only when unread
- Cleanup keys that automatically remove superseded notifications

## Installation with HACS

1. Open HACS in Home Assistant.
2. Add `https://github.com/ricobach/HA-WWebJS` as a custom repository of type **Integration**.
3. Install **WWebJS**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **WWebJS**.

## Text message

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Hello from Home Assistant"
```

## Image or other media

Local Home Assistant file:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Someone is at the front door"
  image: "/config/www/snapshots/frontdoor.jpg"
```

URL:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Camera snapshot"
  media: "https://example.com/snapshot.jpg"
```

The `message` becomes the media caption.

## Temporary notification cleanup

Always revoke after 10 minutes:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Front door opened"
  delete_after: 600
```

Revoke after five minutes only if WWebJS does not report that it was read:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Motion at the front door"
  image: "/config/www/snapshots/frontdoor.jpg"
  delete_if_unread_after: 300
```

Keep only the newest notification for a logical event:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Latest front-door state"
  cleanup_key: "front_door"
  delete_after: 900
```

After the new message is successfully sent, older tracked messages with the same session, recipient and `cleanup_key` are revoked.

`delete_for_everyone` defaults to `true`. WhatsApp ultimately decides whether a message can still be revoked for all participants.

## Session health and recovery

Each configured session gets diagnostic sensors:

- `Session status`
- `Recovery count`

The integration checks the WWebJS API and each configured session every 60 seconds. A session that remains unhealthy for three checks is restarted automatically. Restarts have a five-minute cooldown to avoid restart loops.

If the API server itself is unreachable, the integration reports `API_UNAVAILABLE` and does not repeatedly restart sessions.

## Notes about unread cleanup

Unread cleanup uses the upstream `/message/getInfo` read-receipt data. Read information from WhatsApp Web is not guaranteed to be available or perfectly accurate in every version. When read information cannot be obtained, WWebJS keeps the tracked message and retries instead of deleting it blindly.

## License

MIT
