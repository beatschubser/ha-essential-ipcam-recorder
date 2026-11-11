"""Recording logic for one camera."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.components.camera import (
    DynamicStreamSettings,
    async_get_image,
    async_get_stream_source,
)
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.stream import (
    CONF_RTSP_TRANSPORT as STREAM_RTSP_TRANSPORT,
)
from homeassistant.components.stream import (
    CONF_USE_WALLCLOCK_AS_TIMESTAMPS as STREAM_WALLCLOCK,
)
from homeassistant.components.stream import (
    DOMAIN as STREAM_DOMAIN,
)
from homeassistant.components.stream import (
    HLS_PROVIDER,
    Stream,
    create_stream,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    CLEANUP_HOUR,
    CLEANUP_MINUTE,
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
    EVENT_SAVED,
    FILE_TIME_FORMAT,
    SIGNAL_UPDATE,
    TEMP_MAX_AGE_MINUTES,
    TEMP_PREFIX,
)
from .helpers import (
    SensorState,
    cleanup_folder,
    cleanup_temp,
    folder_to_media_id,
    pick_label,
    seconds_to_cut,
)

_LOGGER = logging.getLogger(__name__)


def _video_duration(path: str) -> float | None:
    """Return the duration of a video file in seconds (blocking)."""
    import av  # provided by the stream integration

    with av.open(path) as container:
        if container.duration:
            return container.duration / 1_000_000
    return None


def _non_empty(path: str) -> bool:
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as file:
        file.write(data)


class IpCamRecorder:
    """Records events of one camera."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.recording = False
        self.last_event: dict[str, Any] | None = None
        self._stream: Stream | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._current_temp: str | None = None

    # ---- configuration -------------------------------------------------

    @property
    def config(self) -> dict[str, Any]:
        """Merged defaults, data and options."""
        return {**DEFAULT_OPTIONS, **self.entry.data, **self.entry.options}

    @property
    def name(self) -> str:
        """Display name of the camera."""
        return self.entry.title

    @property
    def camera(self) -> str:
        """Camera entity id."""
        return self.config[CONF_CAMERA]

    @property
    def folder(self) -> str:
        """Base folder of this camera."""
        return os.path.normpath(self.config[CONF_FOLDER])

    @property
    def favorites_folder(self) -> str:
        """Name of the favorites sub folder."""
        return str(self.config[CONF_FAVORITES_FOLDER]).strip("/") or "Favorites"

    @property
    def media_id(self) -> str | None:
        """Media source id of the camera folder."""
        return folder_to_media_id(self.folder, self.hass.config.media_dirs)

    def _sensors(self, key: str) -> list[str]:
        return list(self.config.get(key) or [])

    @property
    def all_sensors(self) -> list[str]:
        """All trigger sensors."""
        return (
            self._sensors(CONF_PERSON_SENSORS)
            + self._sensors(CONF_PET_SENSORS)
            + self._sensors(CONF_MOTION_SENSORS)
        )

    def _states(self, entity_ids: list[str]) -> list[SensorState]:
        result = []
        for entity_id in entity_ids:
            if (state := self.hass.states.get(entity_id)) is None:
                continue
            result.append(
                SensorState(state.state == "on", state.last_changed.timestamp())
            )
        return result

    # ---- lifecycle -----------------------------------------------------

    async def async_start(self) -> None:
        """Start listening and keep the stream ready."""
        if sensors := self.all_sensors:
            self._unsubs.append(
                async_track_state_change_event(self.hass, sensors, self._handle_state)
            )
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._async_cleanup,
                hour=CLEANUP_HOUR,
                minute=CLEANUP_MINUTE,
                second=0,
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_cleanup_temp,
                timedelta(minutes=TEMP_MAX_AGE_MINUTES),
            )
        )
        if int(self.config[CONF_LOOKBACK]) > 0:
            self._unsubs.append(async_at_started(self.hass, self._async_prepare_stream))

    async def async_stop(self) -> None:
        """Stop listening and release the stream."""
        while self._unsubs:
            self._unsubs.pop()()
        if self._stream is not None:
            stream = self._stream
            self._stream = None
            stream.dynamic_stream_settings.preload_stream = False
            await stream.stop()
            streams = self.hass.data.get(STREAM_DOMAIN, {}).get("streams")
            if isinstance(streams, list) and stream in streams:
                streams.remove(stream)

    async def _async_prepare_stream(self, _hass: HomeAssistant | None = None) -> None:
        try:
            await self._async_get_stream()
        except HomeAssistantError as err:
            _LOGGER.warning("%s: stream not ready yet (%s)", self.name, err)

    async def _async_get_stream(self) -> Stream:
        """Return our own stream (created once, with our stream options)."""
        if self._stream is not None:
            return self._stream
        config = self.config
        source = (config.get(CONF_STREAM_URL) or "").strip()
        if not source:
            source = await async_get_stream_source(self.hass, self.camera)
        if not source:
            raise HomeAssistantError(f"{self.camera} has no stream source")
        options: dict[str, str | bool | float] = {}
        if transport := config.get(CONF_RTSP_TRANSPORT):
            options[STREAM_RTSP_TRANSPORT] = transport
        if config.get(CONF_WALLCLOCK):
            options[STREAM_WALLCLOCK] = True
        preload = int(config[CONF_LOOKBACK]) > 0
        stream = create_stream(
            self.hass,
            source,
            options,
            DynamicStreamSettings(preload_stream=preload),
            stream_label=f"{DOMAIN}.{self.entry.entry_id}",
        )
        if preload:
            # A running HLS output keeps the last segments for the lookback
            stream.add_provider(HLS_PROVIDER)
            await stream.start()
        self._stream = stream
        return stream

    # ---- events --------------------------------------------------------

    @callback
    def _handle_state(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        new = event.data["new_state"]
        if old is None or new is None or old.state != "off" or new.state != "on":
            return
        if self.recording:
            return
        entity_id = event.data["entity_id"]
        if entity_id in self._sensors(CONF_PERSON_SENSORS):
            kind = "person"
        elif entity_id in self._sensors(CONF_PET_SENSORS):
            kind = "pet"
        else:
            kind = "motion"
        self.recording = True
        self._notify()
        self.entry.async_create_background_task(
            self.hass, self._async_record(kind), f"{DOMAIN} recording {self.name}"
        )

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))

    # ---- recording -----------------------------------------------------

    async def _async_record(self, kind: str) -> None:
        config = self.config
        start = time.time()
        now = dt_util.now()
        stamp = now.strftime(FILE_TIME_FORMAT)
        duration = int(config[CONF_VIDEO_DURATION])
        # Temp files live in the camera folder, the leading ~ marks them as temporary
        temp_base = os.path.join(self.folder, f"{TEMP_PREFIX}{stamp}_{slugify(self.camera)}")
        temp, temp_image = temp_base + ".mp4", temp_base + ".jpg"
        self._current_temp = temp_base
        try:
            await self.hass.async_add_executor_job(
                lambda: os.makedirs(self.folder, exist_ok=True)
            )
            try:
                stream = await self._async_get_stream()
                await stream.async_record(
                    temp, duration=duration, lookback=int(config[CONF_LOOKBACK])
                )
            except HomeAssistantError as err:
                _LOGGER.error("%s: recording failed: %s", self.name, err)

            label = pick_label(
                kind,
                self._states(self._sensors(CONF_PERSON_SENSORS)),
                self._states(self._sensors(CONF_PET_SENSORS)),
                start - 1,
            )
            day_folder = os.path.join(
                self.folder, now.strftime(str(config[CONF_DAY_FOLDER_FORMAT]))
            )
            await self.hass.async_add_executor_job(
                lambda: os.makedirs(day_folder, exist_ok=True)
            )
            base = os.path.join(day_folder, f"{stamp}_[{label}]")
            video, image = base + ".mp4", base + ".jpg"

            has_video = await self.hass.async_add_executor_job(_non_empty, temp)
            has_image = False
            if has_video:
                # Still image at the event moment, counted from the end (lookback varies)
                from_end = max(duration - float(config[CONF_SNAPSHOT_OFFSET]), 1)
                has_image = await self._async_ffmpeg(
                    ["-sseof", f"-{from_end}", "-i", temp, "-frames:v", "1", "-q:v", "2", temp_image],
                    temp_image,
                )
                if has_image:
                    await self.hass.async_add_executor_job(shutil.move, temp_image, image)
                cut = seconds_to_cut(
                    self._states(self.all_sensors),
                    start,
                    duration,
                    float(config[CONF_POST_MOTION]),
                )
                if cut > 1:
                    await self._async_trim(temp, cut)
                await self.hass.async_add_executor_job(shutil.move, temp, video)
            if not has_image:
                try:
                    picture = await async_get_image(self.hass, self.camera)
                    await self.hass.async_add_executor_job(
                        _write_bytes, image, picture.content
                    )
                    has_image = True
                except HomeAssistantError as err:
                    _LOGGER.warning("%s: no still image: %s", self.name, err)

            media_dirs = self.hass.config.media_dirs
            self.last_event = {
                "time": now,
                "label": label,
                "trigger": kind,
                "video": folder_to_media_id(video, media_dirs) if has_video else None,
                "image": folder_to_media_id(image, media_dirs) if has_image else None,
                "video_path": video if has_video else None,
                "image_path": image if has_image else None,
            }
            self.hass.bus.async_fire(
                EVENT_SAVED,
                {
                    "entry_id": self.entry.entry_id,
                    "camera": self.camera,
                    "name": self.name,
                    **{k: v for k, v in self.last_event.items() if k != "time"},
                    "time": now.isoformat(),
                },
            )
        except Exception:
            _LOGGER.exception("%s: unexpected error while recording", self.name)
        finally:
            self._current_temp = None
            self.recording = False
            self._notify()

    async def _async_ffmpeg(self, args: list[str], output: str) -> bool:
        binary = get_ffmpeg_manager(self.hass).binary
        process = await asyncio.create_subprocess_exec(
            binary,
            "-y",
            "-loglevel",
            "error",
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            _LOGGER.warning(
                "%s: ffmpeg failed: %s", self.name, stderr.decode(errors="ignore").strip()
            )
            return False
        return await self.hass.async_add_executor_job(_non_empty, output)

    async def _async_trim(self, path: str, cut: float) -> None:
        try:
            length = await self.hass.async_add_executor_job(_video_duration, path)
        except Exception as err:  # noqa: BLE001  # any decoder error: keep the file
            _LOGGER.warning("%s: could not read video length: %s", self.name, err)
            return
        if not length or length - cut <= 1:
            return
        trimmed = path + ".cut.mp4"
        ok = await self._async_ffmpeg(
            ["-i", path, "-t", f"{length - cut:.1f}", "-c", "copy", "-movflags", "+faststart", trimmed],
            trimmed,
        )
        if ok:
            await self.hass.async_add_executor_job(os.replace, trimmed, path)

    # ---- cleanup -------------------------------------------------------

    async def _async_cleanup(self, _now: Any = None) -> None:
        await self._async_cleanup_temp()
        days = float(self.config[CONF_RETENTION_DAYS])
        if days <= 0:
            return
        deleted = await self.hass.async_add_executor_job(
            cleanup_folder,
            self.folder,
            self.favorites_folder,
            days,
            str(self.config[CONF_DAY_FOLDER_FORMAT]),
        )
        _LOGGER.debug("%s: deleted %s old files", self.name, deleted)

    async def _async_cleanup_temp(self, _now: Any = None) -> None:
        # Files of running recordings are never deleted, however long they take:
        # skip those of every camera of this integration, not only this one.
        running = [
            entry.runtime_data._current_temp
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if isinstance(getattr(entry, "runtime_data", None), IpCamRecorder)
            and entry.runtime_data._current_temp
        ]
        await self.hass.async_add_executor_job(
            cleanup_temp, self.folder, TEMP_MAX_AGE_MINUTES, running
        )
