"""Essential IP Cam Recorder: event recordings with lookback, labels and favorites."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_MEDIA_CONTENT_ID,
    CARD_FILENAME,
    CARD_URL_BASE,
    CONF_DAY_FOLDER_FORMAT,
    DOMAIN,
    SERVICE_DELETE_EVENT,
    SERVICE_TOGGLE_FAVORITE,
    WS_CAMERAS,
)
from .helpers import (
    EVENT_FILE_RE,
    delete_event_files,
    favorite_target,
    is_inside,
    media_id_to_path,
    move_event_files,
)
from .recorder import IpCamRecorder

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type IpCamConfigEntry = ConfigEntry[IpCamRecorder]


def _manifest_version() -> str:
    path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(path, encoding="utf-8") as file:
        return json.load(file).get("version", "0")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card, the websocket command and the service."""
    version = await hass.async_add_executor_job(_manifest_version)
    card_path = os.path.join(os.path.dirname(__file__), "frontend", CARD_FILENAME)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"{CARD_URL_BASE}/{CARD_FILENAME}", card_path, False)]
    )
    add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILENAME}?v={version}")

    websocket_api.async_register_command(hass, ws_cameras)

    async def toggle_favorite(call: ServiceCall) -> None:
        media_id: str = call.data[ATTR_MEDIA_CONTENT_ID]
        path = media_id_to_path(media_id, hass.config.media_dirs)
        recorder = next(
            (r for r in _recorders(hass) if path and is_inside(path, r.folder)), None
        )
        if (
            path is None
            or recorder is None
            or not EVENT_FILE_RE.match(os.path.basename(path))
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_recording"
            )
        target, now_favorite = favorite_target(
            path,
            recorder.folder,
            recorder.favorites_folder,
            str(recorder.config[CONF_DAY_FOLDER_FORMAT]),
        )
        stem = os.path.splitext(path)[0]
        moved = await hass.async_add_executor_job(move_event_files, stem, target)
        if not moved:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_recording"
            )
        _LOGGER.debug("%s favorite=%s: %s", recorder.name, now_favorite, moved)

    hass.services.async_register(
        DOMAIN,
        SERVICE_TOGGLE_FAVORITE,
        toggle_favorite,
        schema=vol.Schema({vol.Required(ATTR_MEDIA_CONTENT_ID): cv.string}),
    )

    async def delete_event(call: ServiceCall) -> None:
        # Only administrators (calls without a user, e.g. from automations, are allowed)
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None or not user.is_admin:
                raise Unauthorized(context=call.context)
        media_id: str = call.data[ATTR_MEDIA_CONTENT_ID]
        path = media_id_to_path(media_id, hass.config.media_dirs)
        recorder = next(
            (r for r in _recorders(hass) if path and is_inside(path, r.folder)), None
        )
        if path is None or recorder is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_recording"
            )
        try:
            deleted = await hass.async_add_executor_job(
                delete_event_files,
                path,
                recorder.folder,
                recorder.favorites_folder,
                str(recorder.config[CONF_DAY_FOLDER_FORMAT]),
            )
        except PermissionError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_deletable"
            ) from err
        if not deleted:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_recording"
            )
        _LOGGER.info("%s: deleted %s", recorder.name, deleted)

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_EVENT,
        delete_event,
        schema=vol.Schema({vol.Required(ATTR_MEDIA_CONTENT_ID): cv.string}),
    )
    return True


def _recorders(hass: HomeAssistant) -> list[IpCamRecorder]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(getattr(entry, "runtime_data", None), IpCamRecorder)
    ]


@websocket_api.websocket_command({vol.Required("type"): WS_CAMERAS})
@callback
def ws_cameras(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the configured cameras for the card."""
    connection.send_result(
        msg["id"],
        [
            {
                "entry_id": r.entry.entry_id,
                "name": r.name,
                "path": r.media_id,
                "favorites_folder": r.favorites_folder,
            }
            for r in _recorders(hass)
            if r.media_id
        ],
    )


async def async_setup_entry(hass: HomeAssistant, entry: IpCamConfigEntry) -> bool:
    """Set up one camera."""
    recorder = IpCamRecorder(hass, entry)
    entry.runtime_data = recorder
    await recorder.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: IpCamConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IpCamConfigEntry) -> bool:
    """Unload one camera."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
