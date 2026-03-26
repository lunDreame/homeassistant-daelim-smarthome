"""Sensor platform for Daelim SmartHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DaelimEnergyCoordinator

ENERGY_MONITOR_DEVICE = ("EM-000000", "에너지 사용량")

ENERGY_TYPES: dict[str, tuple[str, SensorDeviceClass | None, str, str]] = {
    "Elec": ("전기", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, "mdi:flash"),
    "Gas": ("가스", SensorDeviceClass.GAS, UnitOfVolume.CUBIC_METERS, "mdi:fire"),
    "Water": ("수도", SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS, "mdi:water"),
    "Hotwater": (
        "온수",
        SensorDeviceClass.WATER,
        UnitOfVolume.CUBIC_METERS,
        "mdi:water-boiler",
    ),
    "Heating": (
        "난방",
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        "mdi:radiator",
    ),
}

MONTHLY_SPECS: list[tuple[str, str, int, SensorStateClass, bool]] = [
    ("current", "당월", 0, SensorStateClass.TOTAL_INCREASING, True),
    ("previous", "전월", 1, SensorStateClass.MEASUREMENT, False),
    ("total", "누적", 2, SensorStateClass.TOTAL, True),
    ("average", "평균", 3, SensorStateClass.MEASUREMENT, False),
]

YEARLY_SPECS: list[tuple[str, str, str, int, SensorStateClass, bool]] = [
    ("usage", "연간 사용량", "rank", 0, SensorStateClass.TOTAL, True),
    ("average", "연간 평균", "rank", 1, SensorStateClass.MEASUREMENT, False),
    ("rank", "연간 순위", "total", 0, SensorStateClass.MEASUREMENT, False),
    ("households", "세대 수", "total", 1, SensorStateClass.MEASUREMENT, False),
]


def _parse_float(value: Any) -> float | None:
    """Convert API values to float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_monthly_item(energy_data: dict[str, Any] | None, energy_type: str) -> dict[str, Any] | None:
    """Return matching monthly energy item."""
    if not energy_data:
        return None
    for item in energy_data.get("item", []):
        if item.get("type") == energy_type:
            return item
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimEnergyCoordinator = data["energy_coordinator"]
    entry_id = entry.entry_id
    device_id = ENERGY_MONITOR_DEVICE[0]
    device_name = ENERGY_MONITOR_DEVICE[1]
    complex_name = entry.data["complex"]

    entities: list[SensorEntity] = [
        DaelimEnergyQueryDaySensor(
            coordinator,
            entry_id,
            device_id,
            device_name,
            complex_name,
        )
    ]

    for energy_type, (name_ko, device_class, unit, icon) in ENERGY_TYPES.items():
        for sensor_key, suffix, index, state_class, use_device_class in MONTHLY_SPECS:
            entities.append(
                DaelimEnergyMonthlySensor(
                    coordinator,
                    entry_id,
                    device_id,
                    device_name,
                    complex_name,
                    energy_type,
                    name_ko,
                    sensor_key,
                    suffix,
                    index,
                    state_class,
                    device_class if use_device_class else None,
                    unit,
                    icon,
                )
            )

        for sensor_key, suffix, source_key, index, state_class, use_device_class in YEARLY_SPECS:
            yearly_unit = unit if source_key == "rank" else None
            yearly_icon = icon if source_key == "rank" else "mdi:numeric"
            entities.append(
                DaelimEnergyYearlySensor(
                    coordinator,
                    entry_id,
                    device_id,
                    device_name,
                    complex_name,
                    energy_type,
                    name_ko,
                    sensor_key,
                    suffix,
                    source_key,
                    index,
                    state_class,
                    device_class if use_device_class else None,
                    yearly_unit,
                    yearly_icon,
                )
            )

    async_add_entities(entities)


class DaelimEnergyQueryDaySensor(CoordinatorEntity[DaelimEnergyCoordinator], SensorEntity):
    """Query day sensor for monthly EMS data."""

    _attr_icon = "mdi:calendar"

    def __init__(
        self,
        coordinator: DaelimEnergyCoordinator,
        entry_id: str,
        device_id: str,
        device_name: str,
        complex_name: str,
    ) -> None:
        """Initialize query day sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = device_name
        self._complex_name = complex_name
        self._attr_name = "에너지 조회일"
        self._attr_unique_id = f"{entry_id}_{device_id}_query_day"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
        )

    @property
    def available(self) -> bool:
        """Return whether query day is available."""
        return self.coordinator.data.get("energy") is not None

    @property
    def native_value(self) -> str | None:
        """Return query day value."""
        energy_data = self.coordinator.data.get("energy")
        if not energy_data:
            return None
        query_day = energy_data.get("queryday")
        if query_day is None:
            return None
        return str(query_day)


class DaelimEnergyMonthlySensor(CoordinatorEntity[DaelimEnergyCoordinator], SensorEntity):
    """Monthly energy sensor."""

    def __init__(
        self,
        coordinator: DaelimEnergyCoordinator,
        entry_id: str,
        device_id: str,
        device_name: str,
        complex_name: str,
        energy_type: str,
        name_ko: str,
        sensor_key: str,
        suffix: str,
        value_index: int,
        state_class: SensorStateClass,
        device_class: SensorDeviceClass | None,
        unit: str,
        icon: str,
    ) -> None:
        """Initialize monthly energy sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = device_name
        self._complex_name = complex_name
        self._energy_type = energy_type
        self._value_index = value_index
        self._attr_name = f"{name_ko} {suffix}"
        self._attr_unique_id = f"{entry_id}_{energy_type.lower()}_{sensor_key}"
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
        )

    @property
    def available(self) -> bool:
        """Return whether monthly data is available."""
        return _get_monthly_item(self.coordinator.data.get("energy"), self._energy_type) is not None

    @property
    def native_value(self) -> float | None:
        """Return monthly value."""
        item = _get_monthly_item(self.coordinator.data.get("energy"), self._energy_type)
        if not item:
            return None
        values = item.get("datavalue", [])
        if not isinstance(values, list) or len(values) <= self._value_index:
            return None
        return _parse_float(values[self._value_index])


class DaelimEnergyYearlySensor(CoordinatorEntity[DaelimEnergyCoordinator], SensorEntity):
    """Yearly energy sensor."""

    def __init__(
        self,
        coordinator: DaelimEnergyCoordinator,
        entry_id: str,
        device_id: str,
        device_name: str,
        complex_name: str,
        energy_type: str,
        name_ko: str,
        sensor_key: str,
        suffix: str,
        source_key: str,
        value_index: int,
        state_class: SensorStateClass,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        icon: str,
    ) -> None:
        """Initialize yearly energy sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = device_name
        self._complex_name = complex_name
        self._energy_type = energy_type
        self._source_key = source_key
        self._value_index = value_index
        self._attr_name = f"{name_ko} {suffix}"
        self._attr_unique_id = f"{entry_id}_{energy_type.lower()}_yearly_{sensor_key}"
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
        )

    @property
    def available(self) -> bool:
        """Return whether yearly data is available."""
        return self.coordinator.data.get("energy_yearly", {}).get(self._energy_type) is not None

    @property
    def native_value(self) -> float | None:
        """Return yearly value."""
        type_data = self.coordinator.data.get("energy_yearly", {}).get(self._energy_type)
        if not type_data:
            return None

        source_values = type_data.get(self._source_key)
        if not isinstance(source_values, list) or len(source_values) <= self._value_index:
            return None
        return _parse_float(source_values[self._value_index])
