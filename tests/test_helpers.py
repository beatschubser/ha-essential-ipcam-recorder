"""Tests for pure helpers."""

import os
import time

import pytest

from custom_components.essential_ipcam_recorder.helpers import (
    SensorState,
    cleanup_folder,
    cleanup_temp,
    delete_event_files,
    favorite_target,
    folder_to_media_id,
    is_inside,
    media_id_to_path,
    move_event_files,
    pick_label,
    seconds_to_cut,
)

DIRS = {"local": "/media"}


def test_label_priority_and_stuck_sensor():
    start = 1000.0
    stuck = SensorState(True, 500.0)  # on since before the recording
    fresh = SensorState(False, 1030.0)  # person seen and gone during recording
    assert pick_label("motion", [stuck], [], start) == "MOTION"
    assert pick_label("motion", [fresh], [], start) == "PERSON"
    assert pick_label("motion", [], [SensorState(True, 1001)], start) == "PET"
    assert pick_label("person", [], [], start) == "PERSON"


def test_seconds_to_cut():
    start = 1000.0
    assert seconds_to_cut([SensorState(False, 1010)], start, 60, 5) == 45
    assert seconds_to_cut([SensorState(True, 1010)], start, 60, 5) == 0
    assert seconds_to_cut([SensorState(False, 1058)], start, 60, 5) == 0
    assert seconds_to_cut([SensorState(False, 1010)], start, 60, 0) == 0


def test_media_paths():
    assert folder_to_media_id("/media/IP/Garden", DIRS) == "media-source://media_source/local/IP/Garden"
    assert folder_to_media_id("/config/x", DIRS) is None
    assert media_id_to_path("media-source://media_source/local/IP/a.jpg", DIRS) == "/media/IP/a.jpg"
    assert media_id_to_path("media-source://media_source/other/a.jpg", DIRS) is None
    escaped = media_id_to_path("media-source://media_source/local/IP/Garden/../../etc/x", DIRS)
    assert not is_inside(escaped, "/media/IP/Garden")
    assert is_inside("/media/IP/Garden/2026_11_10/a.jpg", "/media/IP/Garden")


def test_favorite_roundtrip(tmp_path):
    folder = tmp_path / "Garden"
    day = folder / "2026_11_10"
    day.mkdir(parents=True)
    stem = day / "2026-11-10_20-15-00_[PERSON]"
    for ext in (".jpg", ".mp4"):
        (stem.parent / (stem.name + ext)).write_bytes(b"x")

    target, fav = favorite_target(str(stem) + ".jpg", str(folder), "Favorites", "%Y_%m_%d")
    assert fav and target == str(folder / "Favorites")
    moved = move_event_files(str(stem), target)
    assert len(moved) == 2

    fav_file = folder / "Favorites" / (stem.name + ".jpg")
    target, fav = favorite_target(str(fav_file), str(folder), "Favorites", "%Y_%m_%d")
    assert not fav and target == str(day)
    move_event_files(str(fav_file)[:-4], target)
    assert (day / (stem.name + ".mp4")).exists()


def _old(path, days=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    t = time.time() - days * 86400
    os.utime(path, (t, t))
    return path


def test_cleanup_only_deletes_old_event_files(tmp_path):
    folder = tmp_path / "IP Cam" / "Garden Cam"  # spaces on purpose
    day = folder / "2026_01_01"
    old_event = _old(day / "2026-01-01_10-00-00_[PERSON].mp4")
    old_style = _old(day / "2026-01-01_10-05-00_motion.jpg")
    foreign = _old(day / "holiday photo.jpg")
    new_name_old_mtime = _old(day / f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_[PET].jpg")
    fav = _old(folder / "Favorites" / "2026-01-01_11-00-00_[PET].mp4")
    temp = _old(folder / "_temp" / "2026-01-01_11-00-00_[PET].mp4")
    other_cam = _old(folder / "Other" / "2026_01_01" / "2026-01-01_12-00-00_[PET].mp4")
    not_a_day = _old(folder / "Archive" / "2026-01-01_12-00-00_[PET].mp4")

    assert cleanup_folder(str(folder), "Favorites", 7, "%Y_%m_%d") == 2
    assert not old_event.exists() and not old_style.exists()
    for kept in (foreign, new_name_old_mtime, fav, temp, other_cam, not_a_day):
        assert kept.exists(), kept
    assert day.exists()  # not empty, so kept


def test_cleanup_removes_only_empty_day_folders(tmp_path):
    folder = tmp_path / "Garden"
    empty_day = folder / "2026_01_01"
    _old(empty_day / "2026-01-01_10-00-00_[PERSON].mp4")
    _old(empty_day / "@eaDir" / "thumb.jpg")
    fresh_day = folder / "2026_01_02"
    fresh = _old(fresh_day / "2026-01-02_10-00-00_[PERSON].mp4", days=1)
    assert cleanup_folder(str(folder), "Favorites", 7, "%Y_%m_%d") == 1
    assert not empty_day.exists()
    assert fresh.exists()


def test_cleanup_ignores_symlinks_and_disabled(tmp_path):
    outside = tmp_path / "outside" / "2026_01_01"
    victim = _old(outside / "2026-01-01_10-00-00_[PERSON].mp4")
    folder = tmp_path / "Garden"
    folder.mkdir()
    (folder / "2026_01_01").symlink_to(outside, target_is_directory=True)
    day = folder / "2026_01_02"
    day.mkdir()
    (day / "2026-01-02_10-00-00_[PERSON].mp4").symlink_to(victim)
    assert cleanup_folder(str(folder), "Favorites", 7, "%Y_%m_%d") == 0
    assert victim.exists()
    assert cleanup_folder(str(folder), "Favorites", 0, "%Y_%m_%d") == 0


def test_cleanup_temp(tmp_path):
    folder = tmp_path / "Garden Cam"
    ours = _old(folder / "~2026-01-01_10-00-00_camera_garden.mp4", days=1)
    ours_tmp = _old(folder / "~2026-01-01_10-00-00_camera_garden.mp4.tmp", days=1)
    ours_jpg = _old(folder / "~2026-01-01_10-00-00_camera_garden.jpg", days=1)
    current = _old(folder / "~2026-01-01_11-00-00_camera_garden.mp4.tmp", days=1)
    other_cam = _old(folder / "~2026-01-01_11-00-00_camera_other.mp4.cut.mp4", days=1)
    young = _old(folder / "~2026-01-01_12-00-00_camera_garden.mp4", days=0)
    foreign = _old(folder / "~notes.txt", days=1)
    event = _old(folder / "2026_01_01" / "~2026-01-01_10-00-00_camera_garden.mp4", days=1)
    legacy = _old(folder / "_temp" / "camera_garden_2026-01-01_10-00-00.mp4", days=1)
    keep = [
        str(folder / "~2026-01-01_11-00-00_camera_garden"),
        str(folder / "~2026-01-01_11-00-00_camera_other"),
    ]
    assert cleanup_temp(str(folder), 15, keep=keep) == 4
    assert not ours.exists() and not ours_tmp.exists() and not ours_jpg.exists()
    assert not legacy.exists() and not legacy.parent.exists()
    for kept in (current, other_cam, young, foreign, event):
        assert kept.exists(), kept


def test_move_never_overwrites(tmp_path):
    src = _old(tmp_path / "a" / "2026-01-01_10-00-00_[PET].jpg")
    dst = tmp_path / "b" / src.name
    dst.parent.mkdir()
    dst.write_bytes(b"keep")
    assert move_event_files(str(src)[:-4], str(dst.parent)) == []
    assert dst.read_bytes() == b"keep" and src.exists()


def test_delete_event_files(tmp_path):
    folder = tmp_path / "Garden Cam"
    img = _old(folder / "2026_01_01" / "2026-01-01_10-00-00_[PERSON].jpg", days=0)
    vid = _old(folder / "2026_01_01" / "2026-01-01_10-00-00_[PERSON].mp4", days=0)
    other = _old(folder / "2026_01_01" / "2026-01-01_11-00-00_[PERSON].mp4", days=0)
    fav = _old(folder / "Protected" / "2026-01-02_10-00-00_[PET].jpg", days=0)
    foreign = _old(folder / "2026_01_01" / "holiday.jpg", days=0)
    nested = _old(folder / "x" / "2026_01_01" / "2026-01-01_10-00-00_[PET].jpg", days=0)
    args = (str(folder), "Protected", "%Y_%m_%d")
    assert len(delete_event_files(str(img), *args)) == 2
    assert not img.exists() and not vid.exists() and other.exists()
    for refused in (fav, foreign, nested, tmp_path / "elsewhere" / "2026-01-01_10-00-00_[PET].jpg"):
        with pytest.raises(PermissionError):
            delete_event_files(str(refused), *args)
    assert fav.exists() and foreign.exists() and nested.exists()
