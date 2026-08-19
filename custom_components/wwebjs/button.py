"""Session management buttons for WWebJS."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SESSION_ID, DOMAIN, SUBENTRY_TYPE_SESSION
from .coordinator import WWebJSHealthManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WWebJS session control buttons."""
    health: WWebJSHealthManager = entry.runtime_data.health

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SESSION:
            continue
        session_id = subentry.data.get(CONF_SESSION_ID)
        if not session_id:
            continue
        session_id = str(session_id)
        subentry_id = subentry.subentry_id

        async_add_entities(
            [
                WWebJSSessionButton(
                    health, entry, subentry_id, session_id, "start"
                ),
                WWebJSSessionButton(
                    health, entry, subentry_id, session_id, "restart"
                ),
                WWebJSSessionButton(
                    health, entry, subentry_id, session_id, "stop"
                ),
            ],
            config_subentry_id=subentry_id,
        )


class WWebJSSessionButton(ButtonEntity):
    """A WWebJS session control button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        health: WWebJSHealthManager,
        entry: ConfigEntry,
        subentry_id: str,
        session_id: str,
        action: str,
    ) -> None:
        self.health = health
        self.session_id = session_id
        self.action = action
        self._attr_config_subentry_id = subentry_id
        self._attr_name = action.capitalize()
        self._attr_unique_id = f"{entry.entry_id}_{session_id}_{action}"
        self._attr_icon = {
            "start": "mdi:play",
            "restart": "mdi:restart",
            "stop": "mdi:stop",
        }[action]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{session_id}")},
            name=f"WWebJS – {session_id}",
            manufacturer="WWebJS",
            model="wwebjs-api session",
        )

    async def async_press(self) -> None:
        """Run the selected session control."""
        if self.action == "start":
            await self.health.async_manual_start(self.session_id)
        elif self.action == "restart":
            await self.health.async_manual_restart(self.session_id)
        else:
            await self.health.async_manual_stop(self.session_id)
