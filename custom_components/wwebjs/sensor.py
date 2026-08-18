"""Diagnostic sensors for WWebJS sessions."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_SESSION_ID,
    DOMAIN,
    HISTORY_SENSOR_LIMIT,
    SUBENTRY_TYPE_SESSION,
)
from .coordinator import WWebJSHealthManager
from .history import WWebJSHistoryManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WWebJS diagnostic sensors."""
    runtime = entry.runtime_data
    health: WWebJSHealthManager = runtime.health
    history: WWebJSHistoryManager = hass.data[DOMAIN]["history"]

    entities: list[SensorEntity] = []
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SESSION:
            continue
        session_id = subentry.data.get(CONF_SESSION_ID)
        if not session_id:
            continue
        session_id = str(session_id)
        entities.extend(
            [
                WWebJSSessionStatusSensor(health, entry, session_id),
                WWebJSRecoveryCountSensor(health, entry, session_id),
                WWebJSMessageHistorySensor(history, entry, session_id),
            ]
        )

    async_add_entities(entities)


class WWebJSBaseSensor(SensorEntity):
    """Base sensor for one WWebJS sender session."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, session_id: str) -> None:
        self.session_id = session_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{session_id}")},
            name=f"WWebJS – {session_id}",
            manufacturer="WWebJS",
            model="wwebjs-api session",
        )


class WWebJSHealthSensor(WWebJSBaseSensor):
    """Base sensor subscribed to health updates."""

    def __init__(
        self,
        health: WWebJSHealthManager,
        entry: ConfigEntry,
        session_id: str,
    ) -> None:
        super().__init__(entry, session_id)
        self.health = health
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.health.async_add_listener(
            self._handle_health_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_health_update(self) -> None:
        self.async_write_ha_state()


class WWebJSSessionStatusSensor(WWebJSHealthSensor):
    """Session connection state."""

    _attr_name = "Session status"
    _attr_icon = "mdi:message-processing"

    def __init__(
        self,
        health: WWebJSHealthManager,
        entry: ConfigEntry,
        session_id: str,
    ) -> None:
        super().__init__(health, entry, session_id)
        self._attr_unique_id = f"{entry.entry_id}_{session_id}_session_status"

    @property
    def native_value(self) -> str:
        return self.health.get(self.session_id).state

    @property
    def extra_state_attributes(self) -> dict:
        state = self.health.get(self.session_id)
        return {
            "api_available": state.api_available,
            "consecutive_failures": state.consecutive_failures,
            "last_checked": state.last_checked,
            "last_connected": state.last_connected,
            "last_restart": state.last_restart,
            "last_error": state.last_error,
            "recovery_failures": state.recovery_failures,
            "recovery_suspended": state.recovery_suspended,
            "next_recovery": state.next_recovery,
        }


class WWebJSRecoveryCountSensor(WWebJSHealthSensor):
    """Number of automatic restarts performed."""

    _attr_name = "Recovery count"
    _attr_icon = "mdi:restart"

    def __init__(
        self,
        health: WWebJSHealthManager,
        entry: ConfigEntry,
        session_id: str,
    ) -> None:
        super().__init__(health, entry, session_id)
        self._attr_unique_id = f"{entry.entry_id}_{session_id}_recovery_count"

    @property
    def native_value(self) -> int:
        return self.health.get(self.session_id).recovery_count


class WWebJSMessageHistorySensor(WWebJSBaseSensor):
    """Expose recent outbound message diagnostics."""

    _attr_name = "Message history"
    _attr_icon = "mdi:message-text-clock"

    def __init__(
        self,
        history: WWebJSHistoryManager,
        entry: ConfigEntry,
        session_id: str,
    ) -> None:
        super().__init__(entry, session_id)
        self.history = history
        self._remove_listener = None
        self._attr_unique_id = f"{entry.entry_id}_{session_id}_message_history"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.history.async_add_listener(
            self._handle_history_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_history_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        recent = self.history.recent(self.session_id, 1)
        return recent[-1].status if recent else "none"

    @property
    def extra_state_attributes(self) -> dict:
        recent = self.history.recent(self.session_id, HISTORY_SENSOR_LIMIT)
        return {
            "recent": [
                {
                    "timestamp": item.timestamp,
                    "target": item.target,
                    "kind": item.kind,
                    "status": item.status,
                    "message": item.message,
                    "source_entity": item.source_entity,
                    "error": item.error,
                }
                for item in reversed(recent)
            ]
        }
