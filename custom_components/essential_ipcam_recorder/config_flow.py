"""Config and options flow."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAMERA,
    CONF_DAY_FOLDER_FORMAT,
    CONF_FAVORITES_FOLDER,
    CONF_FOLDER,
    CONF_LOOKBACK,
    CONF_MOTION_SENSORS,
    CONF_PERSON_SENSORS,
    CONF_PET_SENSORS,
    CONF_POST_MOTION,
    CONF_RETENTION_DAYS,
    CONF_RTSP_TRANSPORT,
    CONF_SNAPSHOT_OFFSET,
    CONF_STREAM_URL,
    CONF_VIDEO_DURATION,
    CONF_WALLCLOCK,
    DEFAULT_OPTIONS,
    DOMAIN,
    RTSP_TRANSPORT_OPTIONS,
)
from .helpers import folder_to_media_id

SENSOR_KEYS = (CONF_PERSON_SENSORS, CONF_PET_SENSORS, CONF_MOTION_SENSORS)


def _sensor_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
    )


def _number(min_value: float, max_value: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_value,
            max=max_value,
            step=1,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _sensor_fields(values: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(key, default=values.get(key, [])): _sensor_selector()
        for key in SENSOR_KEYS
    }


def _option_fields(values: dict[str, Any]) -> dict[Any, Any]:
    def default(key: str) -> Any:
        return values.get(key, DEFAULT_OPTIONS[key])

    return {
        vol.Required(CONF_VIDEO_DURATION, default=default(CONF_VIDEO_DURATION)): _number(5, 600, "s"),
        vol.Required(CONF_LOOKBACK, default=default(CONF_LOOKBACK)): _number(0, 10, "s"),
        vol.Required(CONF_POST_MOTION, default=default(CONF_POST_MOTION)): _number(0, 120, "s"),
        vol.Required(CONF_SNAPSHOT_OFFSET, default=default(CONF_SNAPSHOT_OFFSET)): _number(0, 30, "s"),
        vol.Required(CONF_RETENTION_DAYS, default=default(CONF_RETENTION_DAYS)): _number(0, 365, "d"),
        vol.Required(CONF_RTSP_TRANSPORT, default=default(CONF_RTSP_TRANSPORT)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=RTSP_TRANSPORT_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_WALLCLOCK, default=default(CONF_WALLCLOCK)): selector.BooleanSelector(),
        vol.Optional(CONF_STREAM_URL, description={"suggested_value": default(CONF_STREAM_URL)}): selector.TextSelector(),
        vol.Required(CONF_FAVORITES_FOLDER, default=default(CONF_FAVORITES_FOLDER)): selector.TextSelector(),
        vol.Required(CONF_DAY_FOLDER_FORMAT, default=default(CONF_DAY_FOLDER_FORMAT)): selector.TextSelector(),
    }


class IpCamRecorderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one camera."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose camera, folder and trigger sensors."""
        errors: dict[str, str] = {}
        if user_input is not None:
            folder = os.path.normpath(user_input[CONF_FOLDER])
            await self.async_set_unique_id(user_input[CONF_CAMERA])
            self._abort_if_unique_id_configured()
            if folder_to_media_id(folder, self.hass.config.media_dirs) is None:
                errors[CONF_FOLDER] = "folder_not_in_media"
            elif not any(user_input.get(key) for key in SENSOR_KEYS):
                errors["base"] = "no_sensors"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_CAMERA: user_input[CONF_CAMERA], CONF_FOLDER: folder},
                    options={
                        **DEFAULT_OPTIONS,
                        **{key: user_input.get(key, []) for key in SENSOR_KEYS},
                    },
                )
        values = user_input or {}
        media_dir = next(iter(self.hass.config.media_dirs.values()), "/media")
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=values.get(CONF_NAME, "")): selector.TextSelector(),
                vol.Required(CONF_CAMERA, default=values.get(CONF_CAMERA, vol.UNDEFINED)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="camera")
                ),
                vol.Required(CONF_FOLDER, default=values.get(CONF_FOLDER, f"{media_dir}/")): selector.TextSelector(),
                **_sensor_fields(values),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return IpCamRecorderOptionsFlow()


class IpCamRecorderOptionsFlow(OptionsFlow):
    """Change sensors and recording settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show all settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_FOLDER] = os.path.normpath(user_input[CONF_FOLDER])
            if folder_to_media_id(user_input[CONF_FOLDER], self.hass.config.media_dirs) is None:
                errors[CONF_FOLDER] = "folder_not_in_media"
            elif not any(user_input.get(key) for key in SENSOR_KEYS):
                errors["base"] = "no_sensors"
            else:
                for key in SENSOR_KEYS:
                    user_input.setdefault(key, [])
                user_input.setdefault(CONF_STREAM_URL, "")
                return self.async_create_entry(data=user_input)
        values = {
            **DEFAULT_OPTIONS,
            **self.config_entry.data,
            **self.config_entry.options,
            **(user_input or {}),
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_FOLDER, default=values[CONF_FOLDER]): selector.TextSelector(),
                **_sensor_fields(values),
                **_option_fields(values),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
