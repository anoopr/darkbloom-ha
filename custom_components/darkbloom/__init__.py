"""The Darkbloom integration: provider earnings sensors.

One config entry per Darkbloom account. A DataUpdateCoordinator polls
/api/me/earnings (newest-first, max 1000 rows per page), maintains a
persisted rolling cache (26 h of rows + 8 days of hourly buckets), and
publishes windowed earning-rate sensors for 1/2/3/4/6/12/24 h.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_KEY,
    DEFAULT_SCAN_INTERVAL,
    EARNINGS_URL,
    REQUEST_TIMEOUT,
    STORE_KEY,
    STORE_VERSION,
)
from .logic import (
    add_hourly,
    compress_earnings,
    compute_windows,
    merge_new_rows,
    prune_hourly,
    prune_rows,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


class DarkbloomCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Darkbloom, keep the rolling cache, compute window stats."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._api_key: str = entry.data[CONF_API_KEY]
        self._session = async_get_clientsession(hass)
        self._store = Store(hass, STORE_VERSION, STORE_KEY.format(entry.entry_id))
        self._rows: dict[str, dict] = {}
        self._hourly: dict[str, dict] = {}
        super().__init__(
            hass,
            _LOGGER,
            name="darkbloom",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def async_load_cache(self) -> None:
        """Restore the rolling cache across restarts (24h windows survive)."""
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        rows = data.get("rows")
        hourly = data.get("hourly")
        if isinstance(rows, list):
            self._rows = {str(r["i"]): r for r in rows if isinstance(r, dict) and "i" in r}
        if isinstance(hourly, dict):
            self._hourly = hourly
        _LOGGER.debug("restored cache: %s rows, %s hourly buckets", len(self._rows), len(self._hourly))

    async def _async_fetch(self) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            resp = await self._session.get(
                EARNINGS_URL, params={"limit": 1000}, headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            )
        except (TimeoutError, aiohttp.ClientError) as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        if resp.status in (401, 403):
            raise UpdateFailed(f"API key rejected (HTTP {resp.status})")
        if resp.status == 429 or resp.status == 503:
            raise UpdateFailed(f"Rate limited by Darkbloom (HTTP {resp.status})")
        if resp.status != 200:
            raise UpdateFailed(f"Unexpected HTTP {resp.status}")
        try:
            return await resp.json()
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise UpdateFailed(f"Malformed response: {err}") from err

    async def _async_update_data(self) -> dict[str, Any]:
        payload = await self._async_fetch()
        earnings = payload.get("earnings")
        if not isinstance(earnings, list):
            raise UpdateFailed("Response missing 'earnings' list")

        now = datetime.now(timezone.utc)
        compressed = compress_earnings(earnings)
        new_rows = merge_new_rows(self._rows, compressed)
        add_hourly(self._hourly, new_rows)
        prune_rows(self._rows, now)
        prune_hourly(self._hourly, now)

        await self._store.async_save(
            {"rows": list(self._rows.values()), "hourly": self._hourly}
        )

        rows_asc = sorted(self._rows.values(), key=lambda r: r["t"])
        data: dict[str, Any] = {
            "windows": compute_windows(self._rows, now),
            "withdrawable_usd": float(payload.get("withdrawable_balance_usd", 0)),
            "available_usd": float(payload.get("available_balance_usd", 0)),
            "lifetime_usd": float(payload.get("total_usd", 0)),
            "last_job_at": rows_asc[-1]["t"] if rows_asc else None,
            "fetched_at": now.isoformat(),
        }
        _LOGGER.debug(
            "updated: + %s new rows, cache %s rows, balance $%s",
            len(new_rows), len(self._rows), data["withdrawable_usd"],
        )
        return data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = DarkbloomCoordinator(hass, entry)
    await coordinator.async_load_cache()
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: DarkbloomCoordinator | None = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            await coordinator.async_shutdown()
        hass.data.setdefault(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
