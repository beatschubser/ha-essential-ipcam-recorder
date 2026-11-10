"""Base entity for Essential IP Cam Recorder."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .recorder import IpCamRecorder


class IpCamEntity(Entity):
    """Entity bound to one recorder."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, recorder: IpCamRecorder, key: str) -> None:
        """Initialize."""
        self.recorder = recorder
        self._attr_translation_key = key
        self._attr_unique_id = f"{recorder.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, recorder.entry.entry_id)},
            name=recorder.name,
            manufacturer="Essential IP Cam Recorder",
            model="Recorder",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to recorder updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self.recorder.entry.entry_id),
                self.async_write_ha_state,
            )
        )
