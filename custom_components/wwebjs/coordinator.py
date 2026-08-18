"""Session health monitoring and automatic recovery for WWebJS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import WWebJSApi, WWebJSError
from .const import (
    CONF_SESSION_ID,
    HEALTH_AUTH_FAILURE_STATES,
    HEALTH_FAILURES_BEFORE_RESTART,
    HEALTH_RECOVERY_BACKOFF,
    HEALTH_SCAN_INTERVAL,
    HEALTH_TRANSIENT_STATES,
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
    recovery_failures: int = 0
    recovery_suspended: bool = False
    last_checked: datetime | None = None
    last_connected: datetime | None = None
    last_restart: datetime | None = None
    next_recovery: datetime | None = None
    last_error: str | None = None


class WWebJSHealthManager:
    """Poll session state and recover failed sessions."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: WWebJSApi,
    ) -> None:
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
            if (
                subentry.subentry_type == SUBENTRY_TYPE_SESSION
                and subentry.data.get(CONF_SESSION_ID)
            )
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
                health.last_error = api_error
                continue

            try:
                state = await self.api.get_session_status(session_id)
            except WWebJSError as err:
                state = "ERROR"
                health.last_error = str(err)
            else:
                health.last_error = None

            health.state = state or "UNKNOWN"
            if health.state == "CONNECTED":
                self._mark_connected(health)
            elif health.state in HEALTH_AUTH_FAILURE_STATES:
                health.consecutive_failures += 1
                health.recovery_suspended = True
                health.next_recovery = None
            else:
                health.consecutive_failures += 1
                if health.recovery_suspended and health.state in HEALTH_TRANSIENT_STATES:
                    health.recovery_suspended = False

            if self._should_restart(health):
                await self._async_restart(session_id, health)

        self._notify_listeners()

    def _mark_connected(self, health: SessionHealth) -> None:
        health.consecutive_failures = 0
        health.recovery_failures = 0
        health.recovery_suspended = False
        health.next_recovery = None
        health.last_connected = dt_util.utcnow()

    def _should_restart(self, health: SessionHealth) -> bool:
        if not health.api_available or health.recovery_suspended:
            return False
        if health.consecutive_failures < HEALTH_FAILURES_BEFORE_RESTART:
            return False
        if health.state not in HEALTH_TRANSIENT_STATES:
            return False
        if health.next_recovery is None:
            return True
        return dt_util.utcnow() >= health.next_recovery

    def _backoff(self, recovery_failures: int) -> timedelta:
        index = min(
            max(recovery_failures - 1, 0),
            len(HEALTH_RECOVERY_BACKOFF) - 1,
        )
        return HEALTH_RECOVERY_BACKOFF[index]

    async def _async_restart(
        self,
        session_id: str,
        health: SessionHealth,
    ) -> None:
        try:
            await self.api.restart_session(session_id)
        except WWebJSError as err:
            health.recovery_failures += 1
            health.next_recovery = dt_util.utcnow() + self._backoff(
                health.recovery_failures
            )
            health.last_error = f"Automatic restart failed: {err}"
            _LOGGER.warning(
                "Automatic recovery failed for WWebJS session %s: %s",
                session_id,
                err,
            )
            return

        health.last_restart = dt_util.utcnow()
        health.recovery_count += 1
        health.recovery_failures += 1
        health.consecutive_failures = 0
        health.next_recovery = dt_util.utcnow() + self._backoff(
            health.recovery_failures
        )
        health.state = "RESTARTING"
        _LOGGER.warning(
            "Restarted unhealthy WWebJS session %s automatically",
            session_id,
        )

    async def async_manual_start(self, session_id: str) -> None:
        """Start a session and resume automatic recovery."""
        await self.api.start_session(session_id)
        health = self.get(session_id)
        health.recovery_suspended = False
        health.consecutive_failures = 0
        health.next_recovery = None
        await self.async_refresh()

    async def async_manual_stop(self, session_id: str) -> None:
        """Stop a session and suspend automatic recovery."""
        await self.api.stop_session(session_id)
        health = self.get(session_id)
        health.state = "STOPPED"
        health.recovery_suspended = True
        health.next_recovery = None
        self._notify_listeners()

    async def async_manual_restart(self, session_id: str) -> None:
        """Restart a session immediately."""
        await self.api.restart_session(session_id)
        health = self.get(session_id)
        health.last_restart = dt_util.utcnow()
        health.recovery_suspended = False
        health.consecutive_failures = 0
        health.next_recovery = None
        health.state = "RESTARTING"
        self._notify_listeners()

    @callback
    def async_add_listener(
        self,
        listener: Callable[[], None],
    ) -> Callable[[], None]:
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
