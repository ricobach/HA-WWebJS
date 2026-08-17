"""Session health monitoring and automatic recovery for WWebJS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import WWebJSApi, WWebJSError
from .const import (
    CONF_SESSION_ID,
    HEALTH_FAILURES_BEFORE_RESTART,
    HEALTH_RESTART_COOLDOWN,
    HEALTH_SCAN_INTERVAL,
    SUBENTRY_TYPE_SESSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionHealth:
    """Runtime health state for one sender session."""

    state: str = "UNKNOWN"
    api_available: bool = False
    consecutive_failures: int = 0
    recovery_count: int = 0
    last_checked: datetime | None = None
    last_connected: datetime | None = None
    last_restart: datetime | None = None
    last_error: str | None = None


class WWebJSHealthManager:
    """Poll session state and recover failed sessions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: WWebJSApi) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api
        self.sessions: dict[str, SessionHealth] = {}
        self._unsub_interval = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def session_ids(self) -> list[str]:
        """Return configured sender session IDs."""
        return [
            str(subentry.data[CONF_SESSION_ID])
            for subentry in self.entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_SESSION
            and subentry.data.get(CONF_SESSION_ID)
        ]

    async def async_start(self) -> None:
        """Start monitoring."""
        for session_id in self.session_ids:
            self.sessions.setdefault(session_id, SessionHealth())
        await self.async_refresh()
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._handle_interval,
            HEALTH_SCAN_INTERVAL,
        )

    async def async_stop(self) -> None:
        """Stop monitoring."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    async def _handle_interval(self, now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Refresh health for all configured sessions."""
        configured = set(self.session_ids)

        for session_id in list(self.sessions):
            if session_id not in configured:
                self.sessions.pop(session_id, None)

        try:
            api_available = await self.api.ping()
        except WWebJSError as err:
            api_available = False
            api_error = str(err)
        else:
            api_error = None

        for session_id in configured:
            health = self.sessions.setdefault(session_id, SessionHealth())
            health.api_available = api_available
            health.last_checked = dt_util.utcnow()

            if not api_available:
                health.state = "API_UNAVAILABLE"
                health.consecutive_failures += 1
                health.last_error = api_error
                continue

            try:
                state = await self.api.get_session_status(session_id)
            except WWebJSError as err:
                health.state = "ERROR"
                health.consecutive_failures += 1
                health.last_error = str(err)
            else:
                health.state = state or "UNKNOWN"
                health.last_error = None
                if health.state == "CONNECTED":
                    health.consecutive_failures = 0
                    health.last_connected = dt_util.utcnow()
                else:
                    health.consecutive_failures += 1

            if self._should_restart(health):
                await self._async_restart(session_id, health)

        self._notify_listeners()

    def _should_restart(self, health: SessionHealth) -> bool:
        """Return whether automatic recovery should restart the session."""
        if not health.api_available:
            return False
        if health.consecutive_failures < HEALTH_FAILURES_BEFORE_RESTART:
            return False
        if health.last_restart is None:
            return True
        return dt_util.utcnow() - health.last_restart >= HEALTH_RESTART_COOLDOWN

    async def _async_restart(self, session_id: str, health: SessionHealth) -> None:
        """Attempt to recover an unhealthy session."""
        try:
            await self.api.restart_session(session_id)
        except WWebJSError as err:
            health.last_error = f"Automatic restart failed: {err}"
            _LOGGER.warning(
                "Automatic recovery failed for WWebJS session %s: %s",
                session_id,
                err,
            )
            return

        health.last_restart = dt_util.utcnow()
        health.recovery_count += 1
        health.consecutive_failures = 0
        health.state = "RESTARTING"
        _LOGGER.warning(
            "Restarted unhealthy WWebJS session %s automatically",
            session_id,
        )

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a health listener."""
        self._listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove_listener

    @callback
    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def get(self, session_id: str) -> SessionHealth:
        """Return health state for a session."""
        return self.sessions.setdefault(session_id, SessionHealth())
