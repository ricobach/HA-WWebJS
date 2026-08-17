"""Async client for wwebjs-api."""

from __future__ import annotations

import base64
import json
import mimetypes
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession


class WWebJSError(Exception):
    """Base WWebJS API error."""


class WWebJSConnectionError(WWebJSError):
    """Raised when the WWebJS API cannot be reached."""


class WWebJSAuthError(WWebJSError):
    """Raised when the API key is rejected."""


class WWebJSApiError(WWebJSError):
    """Raised for API errors."""


class WWebJSApi:
    """Small async wrapper around wwebjs-api."""

    def __init__(self, session: ClientSession, base_url: str, api_key: str | None = None) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or ""

    @property
    def headers(self) -> dict[str, str]:
        """Return request headers."""
        return {"x-api-key": self._api_key} if self._api_key else {}

    async def _request(self, method: str, path: str, *, json_data: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(method, url, headers=self.headers, json=json_data, timeout=30) as response:
                if response.status == 403:
                    raise WWebJSAuthError("Invalid API key")
                response.raise_for_status()
                if "json" in response.headers.get("Content-Type", ""):
                    return await response.json()
                text = await response.text()
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
        except WWebJSAuthError:
            raise
        except ClientResponseError as err:
            raise WWebJSApiError(f"WWebJS API returned HTTP {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise WWebJSConnectionError(f"Unable to connect to WWebJS API at {self._base_url}") from err

    async def ping(self) -> bool:
        data = await self._request("GET", "/ping")
        return bool(data.get("success", False)) if isinstance(data, dict) else "pong" in str(data).lower()

    async def get_sessions(self) -> list[str]:
        data = await self._request("GET", "/session/getSessions")
        if isinstance(data, dict) and isinstance(data.get("result"), list):
            return [str(value) for value in data["result"]]
        return []

    async def start_session(self, session_id: str) -> Any:
        return await self._request("GET", f"/session/start/{session_id}")

    async def restart_session(self, session_id: str) -> Any:
        return await self._request("GET", f"/session/restart/{session_id}")

    async def get_session_status(self, session_id: str) -> str | None:
        data = await self._request("GET", f"/session/status/{session_id}")
        if isinstance(data, dict) and data.get("state") is not None:
            return str(data["state"]).upper()
        return None

    async def request_pairing_code(self, session_id: str, phone_number: str) -> str:
        data = await self._request("POST", f"/session/requestPairingCode/{session_id}", json_data={"phoneNumber": phone_number, "showNotification": True})
        if isinstance(data, str):
            code = data
        elif isinstance(data, dict):
            code = data.get("pairingCode") or data.get("pairing_code") or data.get("code") or data.get("result") or data.get("message")
        else:
            code = None
        if isinstance(code, dict):
            code = code.get("pairingCode") or code.get("pairing_code") or code.get("code")
        if not code:
            raise WWebJSApiError("The API did not return a pairing code in a recognized format")
        return str(code)

    async def send_text(self, session_id: str, target: str, message: str) -> Any:
        return await self._send_message(session_id, normalize_target(target), "string", message)

    async def send_media_url(self, session_id: str, target: str, media_url: str, caption: str | None = None) -> Any:
        options = {"caption": caption} if caption else None
        return await self._send_message(session_id, normalize_target(target), "MessageMediaFromURL", media_url, options=options)

    async def send_media_bytes(self, session_id: str, target: str, data: bytes, filename: str, mimetype: str | None = None, caption: str | None = None) -> Any:
        resolved_mimetype = mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        content = {"mimetype": resolved_mimetype, "data": base64.b64encode(data).decode("ascii"), "filename": filename}
        options = {"caption": caption} if caption else None
        return await self._send_message(session_id, normalize_target(target), "MessageMedia", content, options=options)

    async def _send_message(self, session_id: str, chat_id: str, content_type: str, content: Any, *, options: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {"chatId": chat_id, "contentType": content_type, "content": content}
        if options:
            payload["options"] = options
        return await self._request("POST", f"/client/sendMessage/{session_id}", json_data=payload)

    async def delete_message(self, session_id: str, chat_id: str, message_id: str, *, everyone: bool = True, clear_media: bool = True) -> Any:
        return await self._request("POST", f"/message/delete/{session_id}", json_data={"chatId": chat_id, "messageId": message_id, "everyone": everyone, "clearMedia": clear_media})

    async def get_message_info(self, session_id: str, chat_id: str, message_id: str) -> Any:
        return await self._request("POST", f"/message/getInfo/{session_id}", json_data={"chatId": chat_id, "messageId": message_id})


def normalize_phone_number(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def normalize_target(value: str) -> str:
    value = value.strip()
    if "@" in value:
        return value
    digits = normalize_phone_number(value)
    if not digits:
        raise WWebJSApiError("Target must contain a phone number or WWebJS chat ID")
    return f"{digits}@c.us"


def extract_message_id(data: Any) -> str | None:
    """Extract the raw WhatsApp message ID from a wwebjs-api response.

    wwebjs-api returns ``{success: true, message: messageOut}``. Depending on
    whatsapp-web.js/WhatsApp Web versions, the Message ID may be exposed on
    ``message.id`` or only inside ``message._data.id``. Recent WhatsApp Web
    builds have also renamed ``_serialized`` to ``$1`` in some ID objects.

    The wwebjs-api message endpoints accept the raw ``id`` component together
    with ``chatId``, so prefer that value when it is available.
    """
    if isinstance(data, list):
        for item in data:
            found = extract_message_id(item)
            if found:
                return found
        return None

    if not isinstance(data, dict):
        return None

    for key in ("messageId", "message_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    identifier = data.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier

    if isinstance(identifier, dict):
        raw_id = identifier.get("id")
        if isinstance(raw_id, str) and raw_id:
            return raw_id

        # Fallbacks for versions where only the serialized key survives JSON.
        for key in ("_serialized", "$1"):
            serialized = identifier.get(key)
            if isinstance(serialized, str) and serialized:
                # A serialized message key is usually
                # <fromMe>_<remote>_<raw-id>. Return the raw suffix because
                # wwebjs-api fetchMessages({messageId}) expects the message ID.
                parts = serialized.rsplit("_", 1)
                return parts[-1] if len(parts) == 2 else serialized

    # Prefer known envelopes first, including Message.rawData/_data.
    for key in ("message", "result", "data", "_data"):
        value = data.get(key)
        if isinstance(value, (dict, list)):
            found = extract_message_id(value)
            if found:
                return found

    # Be tolerant of additional upstream envelopes without relying on their
    # exact property names.
    for key, value in data.items():
        if key in {"message", "result", "data", "_data", "id"}:
            continue
        if isinstance(value, (dict, list)):
            found = extract_message_id(value)
            if found:
                return found

    return None


def unwrap_message_info(data: Any) -> dict[str, Any] | None:
    """Unwrap message delivery/read info from wwebjs-api responses."""
    if not isinstance(data, dict):
        return None
    if any(key in data for key in ("read", "readRemaining", "delivery", "deliveryRemaining")):
        return data
    for key in ("info", "result", "data", "message"):
        value = data.get(key)
        if isinstance(value, dict):
            found = unwrap_message_info(value)
            if found is not None:
                return found
    return None
