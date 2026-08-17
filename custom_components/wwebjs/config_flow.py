"""Config flow for WWebJS."""

from __future__ import annotations

from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, ConfigSubentryFlow, FlowType, SOURCE_USER, SubentryFlowContext, SubentryFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .api import WWebJSApi, WWebJSApiError, WWebJSAuthError, WWebJSConnectionError, normalize_phone_number
from .const import CONF_API_KEY, CONF_BASE_URL, CONF_PHONE_NUMBER, CONF_SESSION_ID, DOMAIN, SUBENTRY_TYPE_SESSION


def _server_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema({
        vol.Required(CONF_BASE_URL, default=defaults.get(CONF_BASE_URL, "http://localhost:3000")): TextSelector(TextSelectorConfig(type="url")),
        vol.Optional(CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")): TextSelector(TextSelectorConfig(type="password")),
    })


class WWebJSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input.get(CONF_API_KEY, "")
            api = WWebJSApi(async_get_clientsession(self.hass), base_url, api_key)
            try:
                if await api.ping():
                    return self.async_create_entry(title="WWebJS", data={CONF_BASE_URL: base_url, CONF_API_KEY: api_key})
                errors["base"] = "cannot_connect"
            except WWebJSAuthError:
                errors["base"] = "invalid_auth"
            except (WWebJSConnectionError, WWebJSApiError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", data_schema=_server_schema(user_input), errors=errors)

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        subentry_result = await self.hass.config_entries.subentries.async_init((result["result"].entry_id, SUBENTRY_TYPE_SESSION), context=SubentryFlowContext(source=SOURCE_USER))
        result["next_flow"] = (FlowType.CONFIG_SUBENTRIES_FLOW, subentry_result["flow_id"])
        return result

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_SESSION: WWebJSSessionSubentryFlow}


class WWebJSSessionSubentryFlow(ConfigSubentryFlow):
    def _api(self) -> WWebJSApi:
        entry = self._get_entry()
        return WWebJSApi(async_get_clientsession(self.hass), entry.data[CONF_BASE_URL], entry.data.get(CONF_API_KEY, ""))

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors = {}
        if user_input is not None:
            session_id = user_input[CONF_SESSION_ID].strip()
            phone_number = normalize_phone_number(user_input[CONF_PHONE_NUMBER])
            if not session_id:
                errors[CONF_SESSION_ID] = "required"
            elif not all(ch.isalnum() or ch == "-" for ch in session_id):
                errors[CONF_SESSION_ID] = "invalid_session_id"
            elif not phone_number:
                errors[CONF_PHONE_NUMBER] = "invalid_phone_number"
            else:
                parent = self._get_entry()
                if any(s.subentry_type == SUBENTRY_TYPE_SESSION and s.data.get(CONF_SESSION_ID) == session_id for s in parent.subentries.values()):
                    return self.async_abort(reason="session_already_configured")
                self._session_id = session_id
                self._phone_number = phone_number
                try:
                    api = self._api()
                    sessions = await api.get_sessions()
                    if session_id in sessions and await api.get_session_status(session_id) == "CONNECTED":
                        return self.async_create_entry(title=session_id, unique_id=session_id, data={CONF_SESSION_ID: session_id, CONF_PHONE_NUMBER: phone_number})
                    if session_id not in sessions:
                        await api.start_session(session_id)
                    self._pairing_code = await api.request_pairing_code(session_id, phone_number)
                    return await self.async_step_pair()
                except WWebJSAuthError:
                    errors["base"] = "invalid_auth"
                except (WWebJSConnectionError, WWebJSApiError):
                    errors["base"] = "session_setup_failed"
        schema = vol.Schema({vol.Required(CONF_SESSION_ID, default=(user_input or {}).get(CONF_SESSION_ID, "")): str, vol.Required(CONF_PHONE_NUMBER, default=(user_input or {}).get(CONF_PHONE_NUMBER, "")): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors = {}
        if user_input is not None:
            try:
                if await self._api().get_session_status(self._session_id) == "CONNECTED":
                    return self.async_create_entry(title=self._session_id, unique_id=self._session_id, data={CONF_SESSION_ID: self._session_id, CONF_PHONE_NUMBER: self._phone_number})
                errors["base"] = "not_connected"
            except WWebJSAuthError:
                errors["base"] = "invalid_auth"
            except (WWebJSConnectionError, WWebJSApiError):
                errors["base"] = "session_setup_failed"
        return self.async_show_form(step_id="pair", data_schema=vol.Schema({}), errors=errors, description_placeholders={"session": self._session_id, "phone_number": self._phone_number, "pairing_code": self._pairing_code})
