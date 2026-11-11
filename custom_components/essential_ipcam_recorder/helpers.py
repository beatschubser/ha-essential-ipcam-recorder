"""Pure helper functions (no Home Assistant state access), easy to test."""

from __future__ import annotations

import os
import re
import shutil
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from .const import (
    FILE_TIME_FORMAT,
    LABEL_MOTION,
    LABEL_PERSON,
    LABEL_PET,
    MEDIA_SOURCE_PREFIX,
)

MEDIA_SUFFIXES = (".jpg", ".mp4")
_STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


@dataclass(frozen=True)
class SensorState:
    """Minimal view of a binary sensor state."""

    is_on: bool
    last_changed: float  # unix timestamp


def pick_label(
    trigger_kind: str,
    person: Iterable[SensorState],
    pet: Iterable[SensorState],
    since: float,
) -> str:
    """Return the most specific label of everything active since `since`.

    A sensor counts if it changed state after `since` (it was on at some point
    during the recording). Sensors stuck "on" from before the recording do not count.
    """

    def active(states: Iterable[SensorState]) -> bool:
        return any(s.last_changed >= since for s in states)

    if trigger_kind == "person" or active(person):
        return LABEL_PERSON
    if trigger_kind == "pet" or active(pet):
        return LABEL_PET
    return LABEL_MOTION


def seconds_to_cut(
    sensors: Iterable[SensorState],
    start: float,
    duration: float,
    post_motion: float,
) -> float:
    """Seconds to cut from the end so the video ends `post_motion` after the last motion.

    The last motion ends when the last sensor switched off. If any sensor is still
    on, motion is ongoing and nothing is cut.
    """
    if post_motion <= 0:
        return 0.0
    last_off = start
    for state in sensors:
        if state.is_on:
            return 0.0
        last_off = max(last_off, state.last_changed)
    return round(max(duration - (last_off + post_motion - start), 0.0), 1)


def folder_to_media_id(folder: str, media_dirs: Mapping[str, str]) -> str | None:
    """Return the media-source id of a folder inside a configured media dir."""
    folder = os.path.normpath(folder)
    for key, base in media_dirs.items():
        base = os.path.normpath(base)
        if folder == base:
            return f"{MEDIA_SOURCE_PREFIX}{key}"
        if folder.startswith(base + os.sep):
            rel = folder[len(base) + 1 :].replace(os.sep, "/")
            return f"{MEDIA_SOURCE_PREFIX}{key}/{rel}"
    return None


def media_id_to_path(media_id: str, media_dirs: Mapping[str, str]) -> str | None:
    """Return the file path of a local media-source id."""
    if not media_id.startswith(MEDIA_SOURCE_PREFIX):
        return None
    key, _, rel = media_id[len(MEDIA_SOURCE_PREFIX) :].partition("/")
    if key not in media_dirs:
        return None
    return os.path.normpath(os.path.join(media_dirs[key], rel))


def is_inside(path: str, folder: str) -> bool:
    """Return True if path is inside folder (after resolving . and ..)."""
    path = os.path.normpath(path)
    folder = os.path.normpath(folder)
    return path.startswith(folder + os.sep)


def favorite_target(
    file_path: str, folder: str, favorites_folder: str, day_folder_format: str
) -> tuple[str, bool]:
    """Return (target folder, now_favorite) for toggling a file's favorite state."""
    parent = os.path.dirname(os.path.normpath(file_path))
    folder = os.path.normpath(folder)
    favorites = os.path.join(folder, favorites_folder)
    if parent == favorites:
        match = _STAMP_RE.search(os.path.basename(file_path))
        if not match:
            raise ValueError("File name has no timestamp")
        day = datetime.strptime(match.group(1), FILE_TIME_FORMAT).strftime(day_folder_format)
        return os.path.join(folder, day), False
    return favorites, True


def move_event_files(stem: str, target: str) -> list[str]:
    """Move <stem>.jpg and <stem>.mp4 into target. Blocking.

    Never overwrites: a file that already exists in target is left untouched.
    """
    os.makedirs(target, exist_ok=True)
    moved = []
    for suffix in MEDIA_SUFFIXES:
        src = stem + suffix
        dst = os.path.join(target, os.path.basename(src))
        if os.path.isfile(src) and not os.path.lexists(dst):
            shutil.move(src, dst)
            moved.append(dst)
    return moved


# Only files written by this integration (or the earlier YAML version) are ever deleted:
#   2026-11-10_20-15-00_[PERSON].mp4 / .jpg   and old style  2026-11-10_20-15-00_person.mp4
EVENT_FILE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_(\[(PERSON|PET|MOTION)\]|person|pet|motion)\.(jpg|mp4)$"
)
# Temp files of a recording: <camera>_<stamp>.mp4, plus .tmp (stream) and .cut.mp4 (trim)
TEMP_FILE_RE = re.compile(
    r"^[a-z0-9_]+_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.mp4(\.tmp|\.cut\.mp4)?$"
)
SYNOLOGY_INDEX = "@eaDir"


def _is_day_folder(name: str, day_folder_format: str) -> bool:
    try:
        datetime.strptime(name, day_folder_format)
    except ValueError:
        return False
    return True


def _real_inside(path: str, folder: str) -> bool:
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([real, base]) == base and real != base


def cleanup_folder(
    folder: str, favorites_folder: str, max_age_days: float, day_folder_format: str
) -> int:
    """Delete old event files and empty day folders. Blocking.

    Deliberately strict, so a badly chosen folder can never lose other data:
    - only direct sub folders whose name is a date in day_folder_format
      (favorites, temp, other cameras and anything else are never entered),
    - no symlinks, nothing outside the camera folder,
    - only files named like an event (EVENT_FILE_RE),
    - only if both the time in the name and the file time are older than the limit,
    - a day folder is only removed when it is empty (os.rmdir, never recursive);
      Synology index folders (@eaDir) inside it are removed first.
    Returns the number of deleted files.
    """
    if max_age_days <= 0 or not os.path.isdir(folder):
        return 0
    limit = time.time() - max_age_days * 86400
    deleted = 0
    with os.scandir(folder) as days:
        day_dirs = [
            entry.path
            for entry in days
            if entry.is_dir(follow_symlinks=False)
            and entry.name != favorites_folder
            and _is_day_folder(entry.name, day_folder_format)
            and _real_inside(entry.path, folder)
        ]
    for day in day_dirs:
        with os.scandir(day) as files:
            for entry in files:
                match = EVENT_FILE_RE.match(entry.name)
                if not match or not entry.is_file(follow_symlinks=False):
                    continue
                stamp = datetime.strptime(match.group(1), FILE_TIME_FORMAT).timestamp()
                try:
                    if stamp < limit and entry.stat(follow_symlinks=False).st_mtime < limit:
                        os.remove(entry.path)
                        deleted += 1
                except FileNotFoundError:
                    continue
        _remove_if_empty(day)
    return deleted


def _remove_if_empty(day: str) -> None:
    try:
        names = os.listdir(day)
        if names == [SYNOLOGY_INDEX]:
            index = os.path.join(day, SYNOLOGY_INDEX)
            if os.path.isdir(index) and not os.path.islink(index):
                shutil.rmtree(index, ignore_errors=True)
        os.rmdir(day)  # fails (and keeps the folder) if anything is left
    except OSError:
        return


def cleanup_temp(temp_folder: str, max_age_minutes: float, keep: str | None = None) -> int:
    """Delete leftover recording temp files older than max_age_minutes. Blocking.

    Only files named like our temp files are touched, never folders or other files.
    """
    if not os.path.isdir(temp_folder) or os.path.islink(temp_folder):
        return 0
    limit = time.time() - max_age_minutes * 60
    deleted = 0
    with os.scandir(temp_folder) as entries:
        for entry in entries:
            if keep and entry.path.startswith(keep):
                continue
            if not TEMP_FILE_RE.match(entry.name) or not entry.is_file(follow_symlinks=False):
                continue
            try:
                if entry.stat(follow_symlinks=False).st_mtime < limit:
                    os.remove(entry.path)
                    deleted += 1
            except FileNotFoundError:
                continue
    return deleted
