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
    TEMP_FOLDER,
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
    """Move <stem>.jpg and <stem>.mp4 into target. Blocking."""
    os.makedirs(target, exist_ok=True)
    moved = []
    for suffix in MEDIA_SUFFIXES:
        src = stem + suffix
        if os.path.exists(src):
            dst = os.path.join(target, os.path.basename(src))
            shutil.move(src, dst)
            moved.append(dst)
    return moved


def cleanup_folder(folder: str, favorites_folder: str, max_age_days: float) -> int:
    """Delete media files older than max_age_days, keep favorites. Blocking.

    Also removes empty day folders. Returns the number of deleted files.
    """
    limit = time.time() - max_age_days * 86400
    deleted = 0
    keep_dirs = {favorites_folder, TEMP_FOLDER}
    for root, dirs, files in os.walk(folder):
        if root == folder:
            dirs[:] = [d for d in dirs if d not in keep_dirs and not d.startswith("@")]
        else:
            dirs[:] = [d for d in dirs if not d.startswith("@")]
        for name in files:
            if not name.lower().endswith((*MEDIA_SUFFIXES, ".tmp")):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getmtime(path) < limit:
                    os.remove(path)
                    deleted += 1
            except FileNotFoundError:
                continue
    for root, dirs, files in os.walk(folder, topdown=False):
        if root == folder or os.path.basename(root) in keep_dirs:
            continue
        if os.path.dirname(root) != folder:
            continue
        try:
            entries = [e for e in os.listdir(root) if not e.startswith("@")]
            if not entries:
                shutil.rmtree(root, ignore_errors=True)
        except FileNotFoundError:
            continue
    return deleted


def cleanup_temp(temp_folder: str, max_age_minutes: float, keep: str | None = None) -> int:
    """Delete leftovers in the temp folder older than max_age_minutes. Blocking."""
    if not os.path.isdir(temp_folder):
        return 0
    limit = time.time() - max_age_minutes * 60
    deleted = 0
    for name in os.listdir(temp_folder):
        path = os.path.join(temp_folder, name)
        if keep and path.startswith(keep):
            continue
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < limit:
                os.remove(path)
                deleted += 1
        except FileNotFoundError:
            continue
    return deleted
