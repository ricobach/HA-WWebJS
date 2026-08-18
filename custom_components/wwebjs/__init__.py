"""WWebJS integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

from .api import WWebJSApi, WWebJSError, extract_message_id, normalize_target
from .const import (
    ATTR_CLEANUP_KEY,
    ATTR_DELETE_AFTER,
    ATTR_DELETE_FOR_EVERYONE,
    ATTR_DELETE_IF_UNREAD_AFTER,
    ATTR_DESCRIPTION,
    ATTR_IMAGE,
    ATTR_LOCATION_ENTITY,
    ATTR_MEDIA,
    ATTR_MEDIA_ENTITY,
    ATTR_MESSAGE,
    ATTR_SESSION,
    ATTR_TARGET,
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_SESSION_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_LOCATION,
    SERVICE_SEND_MESSAGE,
    SUBENTRY_TYPE_SESSION,
)
from .coordinator import WWebJSHealthManager
from .history import WWebJSHistoryManager
from .lifecycle import WWebJSLifecycleManager

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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
        vol.Optional(ATTR_MEDIA_ENTITY): cv.entity_id,
        vol.Optional(ATTR_DELETE_AFTER): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_DELETE_IF_UNREAD_AFTER): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Optional(ATTR_CLEANUP_KEY): cv.string,
        vol.Optional(ATTR_DELETE_FOR_EVERYONE, default=True): cv.boolean,
    }
)

SEND_LOCATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SESSION): cv.string,
        vol.Required(ATTR_TARGET): cv.string,
        vol.Required(ATTR_LOCATION_ENTITY): cv.entity_id,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
    }
)

NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Required(ATTR_TARGET): vol.Any(cv.string, [cv.string]),
        vol.Optional("title"): cv.string,
        vol.Optional("data"): dict,
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

    history = WWebJSHistoryManager(hass)
    await history.async_start()
    hass.data[DOMAIN]["history"] = history

    async def async_send_message(call: ServiceCall) -> None:
        await _async_send_message(
            hass,
            session_id=call.data[ATTR_SESSION],
            target=call.data[ATTR_TARGET],
            message=call.data.get(ATTR_MESSAGE, ""),
            media=call.data.get(ATTR_MEDIA),
            image=call.data.get(ATTR_IMAGE),
            media_entity=call.data.get(ATTR_MEDIA_ENTITY),
            lifecycle_data=call.data,
        )

    async def async_send_location(call: ServiceCall) -> None:
        await _async_send_location(
            hass,
            session_id=call.data[ATTR_SESSION],
            target=call.data[ATTR_TARGET],
            entity_id=call.data[ATTR_LOCATION_ENTITY],
            description=call.data.get(ATTR_DESCRIPTION),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        async_send_message,
        schema=SEND_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_LOCATION,
        async_send_location,
        schema=SEND_LOCATION_SCHEMA,
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
    _register_notify_services(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one WWebJS API server."""
    runtime: WWebJSRuntimeData | None = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _remove_notify_services(hass, entry)
    if runtime is not None:
        await runtime.health.async_stop()
    return unload_ok


def _register_notify_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register notify.wwebjs_<session> services with dynamic recipients."""
    for session_id in _entry_session_ids(entry):
        service_name = f"wwebjs_{slugify(session_id)}"

        async def async_notify(
            call: ServiceCall,
            *,
            _session_id: str = session_id,
        ) -> None:
            target_value = call.data[ATTR_TARGET]
            targets = target_value if isinstance(target_value, list) else [target_value]
            data = call.data.get("data", {})
            media = data.get(ATTR_MEDIA) or data.get(ATTR_IMAGE)
            media_entity = data.get(ATTR_MEDIA_ENTITY)
            for target in targets:
                await _async_send_message(
                    hass,
                    session_id=_session_id,
                    target=target,
                    message=call.data[ATTR_MESSAGE],
                    media=media,
                    media_entity=media_entity,
                )

        hass.services.async_register(
            "notify",
            service_name,
            async_notify,
            schema=NOTIFY_SCHEMA,
        )


def _remove_notify_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove dynamic notify services for an unloaded server."""
    for session_id in _entry_session_ids(entry):
        service_name = f"wwebjs_{slugify(session_id)}"
        if hass.services.has_service("notify", service_name):
            hass.services.async_remove("notify", service_name)


async def _async_send_message(
    hass: HomeAssistant,
    *,
    session_id: str,
    target: str,
    message: str,
    media: str | None = None,
    image: str | None = None,
    media_entity: str | None = None,
    lifecycle_data: dict[str, Any] | None = None,
) -> Any:
    """Send text/media through a configured WWebJS session."""
    entry = _find_session_entry(hass, session_id)
    if entry is None or entry.runtime_data is None:
        raise HomeAssistantError(f"WWebJS session '{session_id}' is not configured")

    runtime: WWebJSRuntimeData = entry.runtime_data
    api = runtime.api
    chat_id = normalize_target(target)
    history: WWebJSHistoryManager = hass.data[DOMAIN]["history"]

    sources = [value for value in (media, image, media_entity) if value]
    if len(sources) > 1:
        raise HomeAssistantError("Use only one of 'media', 'image', or 'media_entity'")
    media_source = media or image
    if not message and not media_source and not media_entity:
        raise HomeAssistantError("A message, media/image, or media_entity is required")

    kind = "text"
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

        if media_entity:
            if not media_entity.startswith("camera."):
                raise HomeAssistantError(
                    "media_entity currently supports camera entities"
                )
            camera_image = await async_get_image(hass, media_entity)
            kind = "camera"
            response = await api.send_media_bytes(
                session_id,
                target,
                camera_image.content,
                f"{slugify(media_entity)}.jpg",
                mimetype=camera_image.content_type,
                caption=message or None,
            )
        elif media_source:
            kind = "media"
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
    except HomeAssistantError as err:
        await history.async_record(
            session_id=session_id,
            target=target,
            kind=kind,
            status="failed",
            message=message,
            source_entity=media_entity,
            error=str(err),
        )
        raise
    except WWebJSError as err:
        await history.async_record(
            session_id=session_id,
            target=target,
            kind=kind,
            status="failed",
            message=message,
            source_entity=media_entity,
            error=str(err),
        )
        raise HomeAssistantError(str(err)) from err

    await history.async_record(
        session_id=session_id,
        target=target,
        kind=kind,
        status="sent",
        message=message,
        source_entity=media_entity,
    )

    if lifecycle_data:
        delete_after = lifecycle_data.get(ATTR_DELETE_AFTER)
        delete_if_unread_after = lifecycle_data.get(ATTR_DELETE_IF_UNREAD_AFTER)
        cleanup_key = lifecycle_data.get(ATTR_CLEANUP_KEY)
        if delete_after or delete_if_unread_after or cleanup_key:
            message_id = extract_message_id(response)
            if not message_id:
                raise HomeAssistantError(
                    "Message was sent, but wwebjs-api did not return a message ID, "
                    "so lifecycle cleanup cannot be scheduled"
                )
            lifecycle_manager: WWebJSLifecycleManager = hass.data[DOMAIN]["lifecycle"]
            await lifecycle_manager.async_track(
                session_id=session_id,
                chat_id=chat_id,
                message_id=message_id,
                delete_after=delete_after,
                delete_if_unread_after=delete_if_unread_after,
                cleanup_key=cleanup_key,
                delete_for_everyone=lifecycle_data[ATTR_DELETE_FOR_EVERYONE],
            )

    return response


async def _async_send_location(
    hass: HomeAssistant,
    *,
    session_id: str,
    target: str,
    entity_id: str,
    description: str | None = None,
) -> Any:
    """Send a person/device_tracker GPS position as a WhatsApp Location."""
    entry = _find_session_entry(hass, session_id)
    if entry is None or entry.runtime_data is None:
        raise HomeAssistantError(f"WWebJS session '{session_id}' is not configured")
    if not (entity_id.startswith("person.") or entity_id.startswith("device_tracker.")):
        raise HomeAssistantError(
            "location_entity must be a person or device_tracker entity"
        )

    state = hass.states.get(entity_id)
    if state is None:
        raise HomeAssistantError(f"Location entity '{entity_id}' does not exist")
    latitude = state.attributes.get(ATTR_LATITUDE)
    longitude = state.attributes.get(ATTR_LONGITUDE)
    if latitude is None or longitude is None:
        raise HomeAssistantError(
            f"Location entity '{entity_id}' has no GPS coordinates"
        )

    runtime: WWebJSRuntimeData = entry.runtime_data
    history: WWebJSHistoryManager = hass.data[DOMAIN]["history"]
    resolved_description = (
        description or state.attributes.get("friendly_name") or entity_id
    )

    try:
        response = await runtime.api.send_location(
            session_id,
            target,
            float(latitude),
            float(longitude),
            resolved_description,
        )
    except WWebJSError as err:
        await history.async_record(
            session_id=session_id,
            target=target,
            kind="location",
            status="failed",
            message=resolved_description,
            source_entity=entity_id,
            error=str(err),
        )
        raise HomeAssistantError(str(err)) from err

    await history.async_record(
        session_id=session_id,
        target=target,
        kind="location",
        status="sent",
        message=resolved_description,
        source_entity=entity_id,
    )
    return response


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


def _entry_session_ids(entry: ConfigEntry) -> list[str]:
    """Return all session IDs configured below a server entry."""
    return [
        str(subentry.data[CONF_SESSION_ID])
        for subentry in entry.subentries.values()
        if (
            subentry.subentry_type == SUBENTRY_TYPE_SESSION
            and subentry.data.get(CONF_SESSION_ID)
        )
    ]


def _is_http_url(value: str) -> bool:
    value = value.lower()
    return value.startswith("http://") or value.startswith("https://")
