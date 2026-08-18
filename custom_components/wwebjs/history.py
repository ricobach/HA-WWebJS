"""Recent outbound message diagnostics for WWebJS."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    HISTORY_LIMIT_PER_SESSION,
    HISTORY_STORAGE_KEY,
    HISTORY_STORAGE_VERSION,
)


@dataclass(slots=True)
class MessageHistoryItem:
    """One outbound message attempt."""

    timestamp: str
    session_id: str
    target: str
    kind: str
    status: str
    message: str | None = None
    source_entity: str | None = None
    error: str | None = None


class WWebJSHistoryManager:
    """Persist a small diagnostics ring buffer for each session."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            HISTORY_STORAGE_VERSION,
            HISTORY_STORAGE_KEY,
        )
        self._items: dict[str, list[MessageHistoryItem]] = defaultdict(list)
        self._listeners: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        """Load persisted history."""
        stored = await self._store.async_load() or {}
        for session_id, values in stored.get("sessions", {}).items():
            for value in values:
                try:
                    self._items[session_id].append(MessageHistoryItem(**value))
                except (TypeError, ValueError):
                    continue

    async def async_record(
        self,
        *,
        session_id: str,
        target: str,
        kind: str,
        status: str,
        message: str | None = None,
        source_entity: str | None = None,
        error: str | None = None,
    ) -> None:
        """Append an outbound diagnostic item."""
        item = MessageHistoryItem(
            timestamp=dt_util.utcnow().isoformat(),
            session_id=session_id,
            target=target,
            kind=kind,
            status=status,
            message=_preview(message),
            source_entity=source_entity,
            error=_preview(error),
        )
        values = self._items[session_id]
        values.append(item)
        del values[:-HISTORY_LIMIT_PER_SESSION]
        await self._store.async_save(
            {
                "sessions": {
                    key: [asdict(stored_item) for stored_item in items]
                    for key, items in self._items.items()
                }
            }
        )
        self._notify_listeners()

    def recent(self, session_id: str, limit: int = 10) -> list[MessageHistoryItem]:
        """Return recent outbound attempts."""
        return list(self._items.get(session_id, [])[-limit:])

    @callback
    def async_add_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe to history updates."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()


def _preview(value: str | None, length: int = 160) -> str | None:
    if value is None:
        return None
    return value if len(value) <= length else f"{value[:length - 1]}…"
