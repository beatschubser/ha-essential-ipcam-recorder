"""Last saved event."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import IpCamConfigEntry
from .entity import IpCamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IpCamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the last event sensor."""
    async_add_entities([LastEventSensor(entry.runtime_data, "last_event")])


class LastEventSensor(IpCamEntity, SensorEntity, RestoreEntity):
    """Time of the last saved event, with label and file references."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    async def async_added_to_hass(self) -> None:
        """Restore the last event after a restart."""
        await super().async_added_to_hass()
        if self.recorder.last_event is None and (state := await self.async_get_last_state()):
            if (time := dt_util.parse_datetime(state.state)) is not None:
                keys = ("label", "trigger", "video", "image", "video_path", "image_path")
                self.recorder.last_event = {
                    "time": time,
                    **{k: state.attributes.get(k) for k in keys},
                }

    @property
    def native_value(self) -> datetime | None:
        """Time of the last event."""
        event = self.recorder.last_event
        return event.get("time") if event else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Label and media references of the last event."""
        event = self.recorder.last_event
        if not event:
            return None
        keys = ("label", "trigger", "video", "image", "video_path", "image_path")
        return {k: event.get(k) for k in keys}
