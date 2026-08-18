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
- Send media directly from Home Assistant `camera.*` and `image.*` entities
- `notify.wwebjs_<session>` services with dynamic recipients
- Send a WhatsApp location from a `person.*` or `device_tracker.*` entity
- Session health monitoring
- Start, stop and restart buttons for each sender session
- Automatic recovery with authentication-aware suspension and escalating retry backoff
- Persisted outbound message history diagnostics
- Message lifecycle/cleanup support is implemented, but deletion is currently blocked by an upstream `whatsapp-web.js` message-ID regression (see below)

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

## Notify services

Each configured sender session also registers a notify service using the same session name.

For a session named `rico`:

```yaml
action: notify.wwebjs_rico
data:
  target: "+4512345678"
  message: "Hello from the Rico sender"
```

Multiple recipients can be supplied as a list:

```yaml
action: notify.wwebjs_rico
data:
  target:
    - "+4511111111"
    - "+4522222222"
  message: "The alarm is armed"
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

## Send media from a Home Assistant entity

WWebJS can request the current image directly from a Home Assistant `camera.*` or `image.*` entity and send it without first writing a snapshot file.

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Front door camera"
  media_entity: camera.front_door
```

An image entity works the same way:

```yaml
action: wwebjs.send_message
data:
  session: rico
  target: "+4512345678"
  message: "Latest generated image"
  media_entity: image.latest_snapshot
```

The same option can be used through a session notify service:

```yaml
action: notify.wwebjs_rico
data:
  target: "+4512345678"
  message: "Front door camera"
  data:
    media_entity: camera.front_door
```

## Send a person or device location

A `person.*` or `device_tracker.*` entity that exposes latitude and longitude can be sent as a native WhatsApp location.

```yaml
action: wwebjs.send_location
data:
  session: rico
  target: "+4512345678"
  location_entity: person.rico
```

An optional label can be supplied:

```yaml
action: wwebjs.send_location
data:
  session: rico
  target: "+4512345678"
  location_entity: device_tracker.phone
  description: "Current phone location"
```

## Session management and recovery

Each configured sender gets Home Assistant controls for:

- **Start**
- **Restart**
- **Stop**

The session device also exposes:

- **Session status**
- **Recovery count**
- **Message history**

Health checks run every 60 seconds. Automatic recovery starts after three consecutive transient failures. Retry delays increase from 1 minute to 5, 15 and then 30 minutes to avoid restart loops.

Authentication, pairing, blocked-account/proxy and deprecated-client states suspend automatic recovery instead of repeatedly restarting a session that needs user or upstream action. Pressing **Start** or **Restart** resumes recovery. Pressing **Stop** intentionally suspends automatic recovery for that running Home Assistant instance.

If the API server itself is unreachable, WWebJS reports `API_UNAVAILABLE` and does not repeatedly restart sessions.

## Message history diagnostics

Each session has a **Message history** diagnostic sensor. It stores a small persisted ring buffer of recent outbound attempts, including:

- Timestamp
- Recipient
- Message type (`text`, `media`, `entity_media`, or `location`)
- Sent/failed state
- Short message/caption preview
- Source Home Assistant entity when applicable
- Error details for failed sends

The sensor state reflects the latest send result and its `recent` attribute contains the latest history entries.

## Temporary notification cleanup

> [!IMPORTANT]
> **Message deletion/cleanup does not currently work with the normal upstream `wwebjs-api` / `whatsapp-web.js` combination.**
>
> The lifecycle options are implemented in this Home Assistant integration, but current `whatsapp-web.js` builds are affected by a WhatsApp Web change where the serialized message-ID property moved from `_serialized` to `$1`. As a result, `wwebjs-api` can successfully send a message while returning only `{ "success": true }` without the message object/ID that deletion and other `/message/*` operations require.
>
> Upstream `whatsapp-web.js` PR [#201832](https://github.com/wwebjs/whatsapp-web.js/pull/201832) addresses this regression, including the `sendMessage` empty-result problem. Until an upstream fix is merged and included in the version used by `wwebjs-api`, treat the cleanup options below as **not operational**.

The intended cleanup interface is documented below so automations can be prepared for when upstream message IDs are reliable again.

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

When the upstream message-ID issue is resolved, a newer message with the same session, recipient and `cleanup_key` will allow older tracked messages to be revoked.

`delete_for_everyone` defaults to `true`. WhatsApp ultimately decides whether a message can still be revoked for all participants.

## Notes about unread cleanup

Unread cleanup depends on two upstream capabilities: a reliable message ID from the send operation and `/message/getInfo` read-receipt data. At the moment, the message-ID regression described above prevents lifecycle cleanup from being scheduled reliably. Once message IDs are available again, read information from WhatsApp Web may still vary by version; if read information cannot be obtained, WWebJS keeps the tracked message and retries instead of deleting it blindly.

## License

MIT
