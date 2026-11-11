"""Config flow tests."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.essential_ipcam_recorder.const import DOMAIN


async def test_user_flow(hass: HomeAssistant) -> None:
    hass.config.media_dirs = {"local": "/media"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Garden", "camera_entity": "camera.garden", "folder": "/config/x", "motion_sensors": ["binary_sensor.m"]},
    )
    assert result["errors"] == {"folder": "folder_not_in_media"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Garden", "camera_entity": "camera.garden", "folder": "/media/IP/Garden", "motion_sensors": []},
    )
    assert result["errors"] == {"base": "no_sensors"}

    with patch(
        "custom_components.essential_ipcam_recorder.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"name": "Garden", "camera_entity": "camera.garden", "folder": "/media/IP/Garden/", "motion_sensors": ["binary_sensor.m"]},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"camera_entity": "camera.garden", "folder": "/media/IP/Garden"}
    assert result["options"]["motion_sensors"] == ["binary_sensor.m"]
    assert result["options"]["video_duration"] == 60


async def test_options_change_folder(hass: HomeAssistant) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.config.media_dirs = {"local": "/media"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"camera_entity": "camera.garden", "folder": "/media/IP/Garden"},
        options={"motion_sensors": ["binary_sensor.m"]},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.essential_ipcam_recorder.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"folder": "/config/x", "motion_sensors": ["binary_sensor.m"]}
        )
        assert result["errors"] == {"folder": "folder_not_in_media"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"folder": "/media/IP/Garten/", "motion_sensors": ["binary_sensor.m"]}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["folder"] == "/media/IP/Garten"
