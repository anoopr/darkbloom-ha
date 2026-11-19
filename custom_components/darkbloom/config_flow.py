"""Config flow to add a Darkbloom account."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_API_KEY, DOMAIN, EARNINGS_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


async def validate_key(hass: HomeAssistant, api_key: str) -> tuple[bool, Any]:
    """Return (ok, account_id_or_error_key) for an API key."""
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(
            EARNINGS_URL,
            params={"limit": 1},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        )
    except (TimeoutError, aiohttp.ClientError):
        return False, "cannot_connect"
    if resp.status == 200:
        try:
            data = await resp.json()
        except (aiohttp.ContentTypeError, ValueError):
            return False, "cannot_connect"
        return True, data.get("account_id") or "default"
    if resp.status in (401, 403):
        return False, "invalid_auth"
    return False, "cannot_connect"


class DarkbloomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Darkbloom config flow (one entry per account)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ok, info = await validate_key(self.hass, user_input[CONF_API_KEY])
            if ok:
                await self.async_set_unique_id(str(info))
                self._abort_if_unique_id_mismatch()
                return self.async_create_entry(title="Darkbloom", data=user_input)
            errors["base"] = str(info)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
