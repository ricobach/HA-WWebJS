"""Message lifecycle management for WWebJS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import WWebJSApi, WWebJSError, unwrap_message_info
from .const import LIFECYCLE_SCAN_INTERVAL, STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

ApiResolver = Callable[[str], WWebJSApi | None]


@dataclass(slots=True)
class TrackedMessage:
    """A sent message with cleanup policy."""

    session_id: str
    chat_id: str
    message_id: str
    sent_at: str
    delete_at: str | None = None
    delete_if_unread_at: str | None = None
    cleanup_key: str | None = None
    delete_for_everyone: bool = True


class WWebJSLifecycleManager:
    """Persist and execute cleanup policies for sent messages."""

    def __init__(self, hass: HomeAssistant, api_resolver: ApiResolver) -> None:
        self.hass = hass
        self._api_resolver = api_resolver
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._messages: list[TrackedMessage] = []
        self._unsub_interval = None

    async def async_start(self) -> None:
        """Load persisted state and start periodic cleanup."""
        stored = await self._store.async_load() or {}
        raw_messages = stored.get("messages", [])
        self._messages = []
        for raw in raw_messages:
            try:
                self._messages.append(TrackedMessage(**raw))
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring invalid persisted WWebJS lifecycle entry")
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._handle_interval,
            LIFECYCLE_SCAN_INTERVAL,
        )
        await self.async_cleanup()

    async def async_stop(self) -> None:
        """Stop the cleanup loop and save state."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        await self._async_save()

    async def _handle_interval(self, now: datetime) -> None:
        await self.async_cleanup()

    async def async_track(
        self,
        *,
        session_id: str,
        chat_id: str,
        message_id: str,
        delete_after: int | None,
        delete_if_unread_after: int | None,
        cleanup_key: str | None,
        delete_for_everyone: bool,
    ) -> None:
        """Track a newly sent message and supersede older keyed messages."""
        now = dt_util.utcnow()
        item = TrackedMessage(
            session_id=session_id,
            chat_id=chat_id,
            message_id=message_id,
            sent_at=now.isoformat(),
            delete_at=(
                (now + timedelta(seconds=delete_after)).isoformat()
                if delete_after is not None
                else None
            ),
            delete_if_unread_at=(
                (now + timedelta(seconds=delete_if_unread_after)).isoformat()
                if delete_if_unread_after is not None
                else None
            ),
            cleanup_key=cleanup_key,
            delete_for_everyone=delete_for_everyone,
        )

        if cleanup_key:
            await self._async_delete_superseded(item)

        self._messages.append(item)
        await self._async_save()

    async def _async_delete_superseded(self, new_item: TrackedMessage) -> None:
        """Delete older messages with the same logical cleanup key."""
        remaining: list[TrackedMessage] = []
        for item in self._messages:
            if (
                item.session_id == new_item.session_id
                and item.chat_id == new_item.chat_id
                and item.cleanup_key == new_item.cleanup_key
            ):
                if not await self._async_delete(item):
                    remaining.append(item)
            else:
                remaining.append(item)
        self._messages = remaining

    async def async_cleanup(self) -> None:
        """Apply due cleanup policies."""
        now = dt_util.utcnow()
        remaining: list[TrackedMessage] = []
        changed = False

        for item in self._messages:
            delete_now = item.delete_at is not None and _parse_dt(item.delete_at) <= now

            if not delete_now and item.delete_if_unread_at is not None:
                if _parse_dt(item.delete_if_unread_at) <= now:
                    read = await self._async_is_read(item)
                    if read is True:
                        item.delete_if_unread_at = None
                        changed = True
                    elif read is False:
                        delete_now = True
                    else:
                        remaining.append(item)
                        continue

            if delete_now:
                if await self._async_delete(item):
                    changed = True
                    continue

            if (
                item.delete_at is None
                and item.delete_if_unread_at is None
                and item.cleanup_key is None
            ):
                changed = True
                continue

            remaining.append(item)

        self._messages = remaining
        if changed:
            await self._async_save()

    async def _async_is_read(self, item: TrackedMessage) -> bool | None:
        """Return True if upstream reports at least one reader."""
        api = self._api_resolver(item.session_id)
        if api is None:
            return None

        try:
            response = await api.get_message_info(
                item.session_id,
                item.chat_id,
                item.message_id,
            )
        except WWebJSError as err:
            _LOGGER.debug(
                "Could not query read state for WWebJS message %s: %s",
                item.message_id,
                err,
            )
            return None

        info = unwrap_message_info(response)
        if info is None:
            return None

        read = info.get("read")
        if isinstance(read, list):
            return len(read) > 0

        return None

    async def _async_delete(self, item: TrackedMessage) -> bool:
        """Delete a tracked message, returning success."""
        api = self._api_resolver(item.session_id)
        if api is None:
            return False

        try:
            await api.delete_message(
                item.session_id,
                item.chat_id,
                item.message_id,
                everyone=item.delete_for_everyone,
                clear_media=True,
            )
        except WWebJSError as err:
            _LOGGER.warning(
                "Could not clean up WWebJS message %s: %s",
                item.message_id,
                err,
            )
            return False

        return True

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"messages": [asdict(item) for item in self._messages]}
        )


def _parse_dt(value: str) -> datetime:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return dt_util.utcnow()
    return parsed
