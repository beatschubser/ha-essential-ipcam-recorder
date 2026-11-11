"""Constants for Essential IP Cam Recorder."""

from __future__ import annotations

VERSION = "1.0.0"
DOMAIN = "essential_ipcam_recorder"

CONF_CAMERA = "camera_entity"
CONF_FOLDER = "folder"
CONF_PERSON_SENSORS = "person_sensors"
CONF_PET_SENSORS = "pet_sensors"
CONF_MOTION_SENSORS = "motion_sensors"
CONF_VIDEO_DURATION = "video_duration"
CONF_LOOKBACK = "lookback"
CONF_POST_MOTION = "post_motion"
CONF_SNAPSHOT_OFFSET = "snapshot_offset"
CONF_RETENTION_DAYS = "retention_days"
CONF_RTSP_TRANSPORT = "rtsp_transport"
CONF_WALLCLOCK = "use_wallclock_as_timestamps"
CONF_STREAM_URL = "stream_url"
CONF_DAY_FOLDER_FORMAT = "day_folder_format"
CONF_FAVORITES_FOLDER = "favorites_folder"

DEFAULT_OPTIONS: dict[str, object] = {
    CONF_PERSON_SENSORS: [],
    CONF_PET_SENSORS: [],
    CONF_MOTION_SENSORS: [],
    CONF_VIDEO_DURATION: 60,
    CONF_LOOKBACK: 3,
    CONF_POST_MOTION: 5,
    CONF_SNAPSHOT_OFFSET: 1,
    CONF_RETENTION_DAYS: 7,
    CONF_RTSP_TRANSPORT: "tcp",
    CONF_WALLCLOCK: True,
    CONF_STREAM_URL: "",
    CONF_DAY_FOLDER_FORMAT: "%Y_%m_%d",
    CONF_FAVORITES_FOLDER: "Favorites",
}

RTSP_TRANSPORT_OPTIONS = ["tcp", "udp", "udp_multicast", "http"]

# Label written into file names, in priority order
LABEL_PERSON = "PERSON"
LABEL_PET = "PET"
LABEL_MOTION = "MOTION"

TEMP_PREFIX = "~"  # running recordings in the camera folder: ~<time>_<camera>.mp4
LEGACY_TEMP_FOLDER = "_temp"  # used up to 0.1.1-beta.4, emptied and removed by the cleanup
TEMP_MAX_AGE_MINUTES = 15
CLEANUP_HOUR = 3
CLEANUP_MINUTE = 30

FILE_TIME_FORMAT = "%Y-%m-%d_%H-%M-%S"

EVENT_SAVED = f"{DOMAIN}_event_saved"
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"

SERVICE_TOGGLE_FAVORITE = "toggle_favorite"
ATTR_MEDIA_CONTENT_ID = "media_content_id"

WS_CAMERAS = f"{DOMAIN}/cameras"

CARD_FILENAME = "essential-ipcam-recorder-card.js"
CARD_URL_BASE = f"/{DOMAIN}"

MEDIA_SOURCE_PREFIX = "media-source://media_source/"
