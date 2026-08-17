"""Async client for wwebjs-api."""

from __future__ import annotations

import json
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
            async with self._session.request(method, url, headers=self.headers, json=json_data, timeout=20) as response:
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
        return await self._request("POST", f"/client/sendMessage/{session_id}", json_data={"chatId": normalize_target(target), "contentType": "string", "content": message})


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
