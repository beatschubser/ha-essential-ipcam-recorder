import time

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized

"""End to end: sensor fires, video and image land in the day folder."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essential_ipcam_recorder.const import DOMAIN, EVENT_SAVED


async def test_record_label_and_favorite(
    hass: HomeAssistant, tmp_path, hass_ws_client, hass_read_only_user
) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    folder = tmp_path / "Garden"

    stream = MagicMock()

    async def fake_record(path, duration, lookback):
        assert os.path.basename(path).startswith("~")
        assert os.path.dirname(path) == str(folder)
        with open(path, "wb") as f:
            f.write(b"video")
        # a slow recording: file untouched for an hour, cleanup runs meanwhile
        old = time.time() - 3600
        os.utime(path, (old, old))
        await entry.runtime_data._async_cleanup_temp()
        assert os.path.exists(path)

    stream.async_record = AsyncMock(side_effect=fake_record)
    stream.start = AsyncMock()
    stream.stop = AsyncMock()

    async def fake_ffmpeg(self, args, output):
        with open(output, "wb") as f:
            f.write(b"jpg")
        return True

    hass.states.async_set("binary_sensor.motion", "off")
    hass.states.async_set("binary_sensor.person", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={"camera_entity": "camera.garden", "folder": str(folder)},
        options={
            "motion_sensors": ["binary_sensor.motion"],
            "person_sensors": ["binary_sensor.person"],
            "lookback": 0,
            "post_motion": 0,
        },
    )
    entry.add_to_hass(hass)
    events = []
    hass.bus.async_listen(EVENT_SAVED, lambda e: events.append(e))

    base = "custom_components.essential_ipcam_recorder"
    with (
        patch(f"{base}.recorder.create_stream", return_value=stream),
        patch(f"{base}.recorder.async_get_stream_source", AsyncMock(return_value="rtsp://x")),
        patch(f"{base}.recorder.IpCamRecorder._async_ffmpeg", fake_ffmpeg),
        patch(f"{base}.add_extra_js_url"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # motion first, person later during the recording
        hass.states.async_set("binary_sensor.motion", "on")
        hass.states.async_set("binary_sensor.person", "on")
        hass.states.async_set("binary_sensor.person", "off")
        await hass.async_block_till_done(wait_background_tasks=True)

    assert len(events) == 1
    data = events[0].data
    assert data["label"] == "PERSON"
    assert data["trigger"] == "motion"
    assert os.path.exists(data["video_path"]) and os.path.exists(data["image_path"])
    assert not [n for n in os.listdir(folder) if n.startswith("~")]  # temp files renamed

    state = hass.states.get("sensor.garden_last_event")
    assert state is not None and state.attributes["label"] == "PERSON"

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/cameras"})
    msg = await client.receive_json()
    assert msg["result"][0]["path"] == "media-source://media_source/local/Garden"

    await hass.services.async_call(
        DOMAIN, "toggle_favorite", {"media_content_id": data["image"]}, blocking=True
    )
    name = os.path.basename(data["video_path"])
    assert (folder / "Protected" / name).exists()

    fav_id = data["image"].rsplit("/", 2)[0] + "/Protected/" + os.path.basename(data["image_path"])
    await hass.services.async_call(
        DOMAIN, "toggle_favorite", {"media_content_id": fav_id}, blocking=True
    )
    assert os.path.exists(data["video_path"])

    # delete: protected events are refused, day folder events are deleted (image + video)
    await hass.services.async_call(
        DOMAIN, "toggle_favorite", {"media_content_id": data["image"]}, blocking=True
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "delete_event", {"media_content_id": fav_id}, blocking=True
        )
    assert (folder / "Protected" / name).exists()
    await hass.services.async_call(
        DOMAIN, "toggle_favorite", {"media_content_id": fav_id}, blocking=True
    )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "delete_event",
            {"media_content_id": data["image"]},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert os.path.exists(data["image_path"])
    await hass.services.async_call(
        DOMAIN, "delete_event", {"media_content_id": data["image"]}, blocking=True
    )
    assert not os.path.exists(data["video_path"]) and not os.path.exists(data["image_path"])

    assert await hass.config_entries.async_unload(entry.entry_id)
