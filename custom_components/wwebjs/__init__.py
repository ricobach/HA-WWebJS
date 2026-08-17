"""WWebJS integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WWebJSApi, WWebJSError, extract_message_id, normalize_target
from .const import (
    ATTR_CLEANUP_KEY,
    ATTR_DELETE_AFTER,
    ATTR_DELETE_FOR_EVERYONE,
    ATTR_DELETE_IF_UNREAD_AFTER,
    ATTR_IMAGE,
    ATTR_MEDIA,
    ATTR_MESSAGE,
    ATTR_SESSION,
    ATTR_TARGET,
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_SESSION_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_MESSAGE,
    SUBENTRY_TYPE_SESSION,
)
from .coordinator import WWebJSHealthManager
from .lifecycle import WWebJSLifecycleManager


@dataclass(slots=True)
class WWebJSRuntimeData:
    """Runtime data for one WWebJS server."""

    api: WWebJSApi
    health: WWebJSHealthManager


SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SESSION): cv.string,
        vol.Required(ATTR_TARGET): cv.string,
        vol.Optional(ATTR_MESSAGE, default=""): cv.string,
        vol.Optional(ATTR_MEDIA): cv.string,
        vol.Optional(ATTR_IMAGE): cv.string,
        vol.Optional(ATTR_DELETE_AFTER): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_DELETE_IF_UNREAD_AFTER): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Optional(ATTR_CLEANUP_KEY): cv.string,
        vol.Optional(ATTR_DELETE_FOR_EVERYONE, default=True): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up WWebJS and register global actions."""
    hass.data.setdefault(DOMAIN, {})

    def resolve_api(session_id: str) -> WWebJSApi | None:
        entry = _find_session_entry(hass, session_id)
        if entry is None or entry.runtime_data is None:
            return None
        runtime: WWebJSRuntimeData = entry.runtime_data
        return runtime.api

    lifecycle = WWebJSLifecycleManager(hass, resolve_api)
    await lifecycle.async_start()
    hass.data[DOMAIN]["lifecycle"] = lifecycle

    async def async_send_message(call: ServiceCall) -> None:
        session_id = call.data[ATTR_SESSION]
        entry = _find_session_entry(hass, session_id)
        if entry is None or entry.runtime_data is None:
            raise HomeAssistantError(
                f"WWebJS session '{session_id}' is not configured"
            )

        runtime: WWebJSRuntimeData = entry.runtime_data
        api = runtime.api
        target = call.data[ATTR_TARGET]
        chat_id = normalize_target(target)

        media = call.data.get(ATTR_MEDIA)
        image = call.data.get(ATTR_IMAGE)
        if media and image:
            raise HomeAssistantError("Use either 'media' or 'image', not both")
        media_source = media or image
        message = call.data.get(ATTR_MESSAGE, "")

        if not message and not media_source:
            raise HomeAssistantError("A message or media/image is required")

        try:
            state = await api.get_session_status(session_id)
            if state != "CONNECTED":
                await runtime.health.async_refresh()
                state = await api.get_session_status(session_id)
            if state != "CONNECTED":
                raise HomeAssistantError(
                    f"WWebJS session '{session_id}' is not connected "
                    f"(state: {state or 'unknown'})"
                )

            if media_source:
                if _is_http_url(media_source):
                    response = await api.send_media_url(
                        session_id,
                        target,
                        media_source,
                        caption=message or None,
                    )
                else:
                    path = Path(media_source).expanduser()
                    exists = await hass.async_add_executor_job(path.is_file)
                    if not exists:
                        raise HomeAssistantError(
                            f"Media file does not exist: {media_source}"
                        )
                    try:
                        data = await hass.async_add_executor_job(path.read_bytes)
                    except OSError as err:
                        raise HomeAssistantError(
                            f"Unable to read media file: {media_source}"
                        ) from err
                    response = await api.send_media_bytes(
                        session_id,
                        target,
                        data,
                        path.name,
                        caption=message or None,
                    )
            else:
                response = await api.send_text(session_id, target, message)
        except HomeAssistantError:
            raise
        except WWebJSError as err:
            raise HomeAssistantError(str(err)) from err

        delete_after = call.data.get(ATTR_DELETE_AFTER)
        delete_if_unread_after = call.data.get(ATTR_DELETE_IF_UNREAD_AFTER)
        cleanup_key = call.data.get(ATTR_CLEANUP_KEY)

        if delete_after or delete_if_unread_after or cleanup_key:
            message_id = extract_message_id(response)
            if not message_id:
                raise HomeAssistantError(
                    "Message was sent, but wwebjs-api did not return a message ID, "
                    "so lifecycle cleanup cannot be scheduled"
                )

            lifecycle_manager: WWebJSLifecycleManager = hass.data[DOMAIN][
                "lifecycle"
            ]
            await lifecycle_manager.async_track(
                session_id=session_id,
                chat_id=chat_id,
                message_id=message_id,
                delete_after=delete_after,
                delete_if_unread_after=delete_if_unread_after,
                cleanup_key=cleanup_key,
                delete_for_everyone=call.data[ATTR_DELETE_FOR_EVERYONE],
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        async_send_message,
        schema=SEND_MESSAGE_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one WWebJS API server."""
    api = WWebJSApi(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data.get(CONF_API_KEY, ""),
    )
    health = WWebJSHealthManager(hass, entry, api)
    entry.runtime_data = WWebJSRuntimeData(api=api, health=health)

    await health.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one WWebJS API server."""
    runtime: WWebJSRuntimeData | None = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if runtime is not None:
        await runtime.health.async_stop()
    return unload_ok


def _find_session_entry(hass: HomeAssistant, session_id: str) -> ConfigEntry | None:
    """Find the parent server entry for a configured session."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        for subentry in entry.subentries.values():
            if (
                subentry.subentry_type == SUBENTRY_TYPE_SESSION
                and subentry.data.get(CONF_SESSION_ID) == session_id
            ):
                return entry
    return None


def _is_http_url(value: str) -> bool:
    value = value.lower()
    return value.startswith("http://") or value.startswith("https://")
