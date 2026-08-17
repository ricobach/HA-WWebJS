"""WWebJS integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WWebJSApi, WWebJSError
from .const import ATTR_MESSAGE, ATTR_SESSION, ATTR_TARGET, CONF_API_KEY, CONF_BASE_URL, CONF_SESSION_ID, DOMAIN, SERVICE_SEND_MESSAGE, SUBENTRY_TYPE_SESSION

SEND_MESSAGE_SCHEMA = vol.Schema({vol.Required(ATTR_SESSION): cv.string, vol.Required(ATTR_TARGET): cv.string, vol.Required(ATTR_MESSAGE): cv.string})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up WWebJS and register global actions."""

    async def async_send_message(call: ServiceCall) -> None:
        session_id = call.data[ATTR_SESSION]
        match = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            for subentry in entry.subentries.values():
                if subentry.subentry_type == SUBENTRY_TYPE_SESSION and subentry.data.get(CONF_SESSION_ID) == session_id:
                    match = entry
                    break
            if match:
                break
        if match is None:
            raise HomeAssistantError(f"WWebJS session '{session_id}' is not configured")
        api = WWebJSApi(async_get_clientsession(hass), match.data[CONF_BASE_URL], match.data.get(CONF_API_KEY, ""))
        try:
            state = await api.get_session_status(session_id)
            if state != "CONNECTED":
                raise HomeAssistantError(f"WWebJS session '{session_id}' is not connected (state: {state or 'unknown'})")
            await api.send_text(session_id, call.data[ATTR_TARGET], call.data[ATTR_MESSAGE])
        except WWebJSError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_SEND_MESSAGE, async_send_message, schema=SEND_MESSAGE_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
