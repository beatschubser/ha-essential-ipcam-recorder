"""Recording state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IpCamConfigEntry
from .entity import IpCamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IpCamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the recording sensor."""
    async_add_entities([RecordingSensor(entry.runtime_data, "recording")])


class RecordingSensor(IpCamEntity, BinarySensorEntity):
    """On while a recording is running."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return True while recording."""
        return self.recorder.recording
