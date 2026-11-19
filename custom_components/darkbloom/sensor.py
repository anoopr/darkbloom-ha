"""Darkbloom sensors: windowed earning rates, balances, freshness."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .logic import is_reward, parse_ts

RATE_DECIMALS = 3
MONEY_DECIMALS = 2


def _device_info() -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, "provider_network")},
        name="Darkbloom Provider Network",
        manufacturer="Darkbloom",
        model="Inference network",
        configuration_url="https://console.darkbloom.dev",
    )


class _DarkbloomSensor(CoordinatorEntity, SensorEntity):
    """Common plumbing: device, naming, attributes from coordinator data."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self, coordinator, entry: ConfigEntry, unique_suffix: str, name: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_name = name
        self._attr_device_info = _device_info()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class DarkbloomRateSensor(_DarkbloomSensor):
    """Earning rate over a rolling window, USD/hour."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/h"
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator, entry: ConfigEntry, hours: int) -> None:
        super().__init__(coordinator, entry, f"rate_{hours}h", f"Darkbloom Rate {hours}h")
        self._hours = hours

    @property
    def native_value(self) -> float | None:
        window = self.coordinator.data["windows"][self._hours]
        rate = window["rate_usd_h"]
        return round(rate, RATE_DECIMALS) if rate is not None else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        window = self.coordinator.data["windows"][self._hours]
        rewards = 0
        jobs = 0
        for model, src in window["sources"].items():
            if is_reward(model):
                rewards += src["earned_micro_usd"]
        jobs = sum(s["jobs"] for s in window["sources"].values())
        sources = {
            model: {
                "jobs": s["jobs"],
                "earned_usd": round(s["earned_micro_usd"] / 1e6, 6),
            }
            for model, s in sorted(
                window["sources"].items(), key=lambda kv: -kv[1]["earned_micro_usd"]
            )
        }
        return {
            "window_hours": self._hours,
            "earned_usd": round(window["shown_micro_usd"] / 1e6, 6),
            "work_usd": round((window["shown_micro_usd"] - rewards) / 1e6, 6),
            "rewards_usd": round(rewards / 1e6, 6),
            "jobs": jobs,
            "exact": window["exact"],
            "sources": sources,
            "data_as_of": self.coordinator.data["fetched_at"],
        }


class DarkbloomBalanceSensor(_DarkbloomSensor):
    """Withdrawable provider balance."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:wallet"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "withdrawable", "Darkbloom Withdrawable Balance")

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.data["withdrawable_usd"], MONEY_DECIMALS)


class DarkbloomLifetimeSensor(_DarkbloomSensor):
    """Lifetime earnings (monotone)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cash-check"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "lifetime", "Darkbloom Lifetime Earnings")

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.data["lifetime_usd"], MONEY_DECIMALS)


class DarkbloomLastJobSensor(_DarkbloomSensor):
    """Timestamp of the most recent served job (freshness at a glance)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_job", "Darkbloom Last Job")

    @property
    def native_value(self) -> datetime | None:
        raw = self.coordinator.data["last_job_at"]
        return parse_ts(raw) if raw else None


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        DarkbloomRateSensor(coordinator, entry, hours) for hours in (1, 2, 3, 4, 6, 12, 24)
    ]
    entities.append(DarkbloomBalanceSensor(coordinator, entry))
    entities.append(DarkbloomLifetimeSensor(coordinator, entry))
    entities.append(DarkbloomLastJobSensor(coordinator, entry))
    async_add_entities(entities)
