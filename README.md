<p align="center">
  <img src="custom_components/essential_ipcam_recorder/brand/icon.png" width="128" alt="Essential IP Cam Recorder">
</p>

<h1 align="center">Essential IP Cam Recorder</h1>

> Tested in daily use with Tapo cameras. Feedback on other cameras is welcome.

Event recordings for Home Assistant cameras: when a motion, person or pet sensor fires, the recorder saves a video with lookback, picks the most specific label, trims the video to the end of the motion, extracts a preview image and shows everything in a bundled timeline card.

## Features

- Video with lookback (seconds before the event) and audio (AAC)
- Labels by priority: person > pet > motion, from all sensors active during the recording
- Trims the video to the last motion plus a configurable tail
- Preview image extracted from the video
- Day folders, protected events (never deleted by the cleanup), daily cleanup
- Timeline card with a large player for all events, filters by camera and type, lock to protect events, two-step delete (admins only, protected events cannot be deleted)
- Entities per camera: `Recording` and `Last event`, plus the event `essential_ipcam_recorder_event_saved` for your own automations

## Requirements

- A camera entity with a stream, and binary sensors for motion, person or pet (e.g. from [Tapo Control](https://github.com/JurajNyiri/HomeAssistant-Tapo-Control))
- A folder inside a Home Assistant media folder, e.g. `/media/IP_Cam/Garden`
- **[go2rtc](https://github.com/AlexxIT/go2rtc)** (add-on or container) if your camera sends audio other than AAC (Tapo: G.711) or allows only few connections
- **A stream URL pointing to go2rtc**, either as custom stream link in your camera integration (Tapo Control: *Custom stream link*) or as *Stream URL* in this integration's options

### go2rtc example

One connection to the camera, audio converted to AAC:

```yaml
streams:
  garden_hd_raw: rtsp://USER:PASSWORD@CAMERA_IP:554/stream1
  garden_hd:
    - rtsp://127.0.0.1:8554/garden_hd_raw
    - ffmpeg:garden_hd_raw#audio=aac
```

Stream URL: `rtsp://127.0.0.1:8554/garden_hd?video=all&audio=aac` with RTSP transport **tcp**.

## Installation

1. HACS → ⋮ → *Custom repositories* → `https://github.com/beatschubser/ha-essential-ipcam-recorder`, type *Integration*
2. Install *Essential IP Cam Recorder*, restart Home Assistant
3. *Settings → Devices & services → Add integration → Essential IP Cam Recorder*, once per camera

## Options

| Option | Default | |
|---|---|---|
| Maximum video length | 60 s | Camera is locked for new events meanwhile |
| Lookback | 3 s | Keeps a stream running; starts at the previous keyframe; 0 = off |
| Keep after last motion | 5 s | 0 = never trim |
| Still image after event | 1 s | |
| Keep recordings | 7 days | Daily at 03:30, protected events are kept; 0 = forever |
| RTSP transport | tcp | |
| Use wallclock as timestamps | on | Fixes corrupted videos from cameras with broken timestamps |
| Stream URL | | Overrides the camera's stream source |
| Folder for protected events | `Protected` | |
| Day folder format | `%Y_%m_%d` | |

## Card

The card is loaded automatically. Without `sources` it shows all recorder cameras:

```yaml
type: custom:essential-ipcam-recorder-card
max_items: 10
default_type: PERSON
```

`play_in_hero` decides where list videos play: `always` (default, large player), `wide` (large player on cards from `hero_min_width` = 600 px, overlay on narrow cards) or `never` (overlay). All settings are available in the visual editor.

## Files

```
<folder>/2026_11_10/2026-11-10_20-15-00_[PERSON].mp4
<folder>/2026_11_10/2026-11-10_20-15-00_[PERSON].jpg
<folder>/Protected/...
<folder>/~2026-11-10_20-15-00_camera_garden.mp4   running recording (temporary)
```

## Notes

- Audio is only recorded if the stream delivers AAC. Other formats are dropped by Home Assistant without a log entry.
- H.265 streams record fine, but not every browser plays them.
- While recording, files start with `~` and stay in the camera folder. When done they are renamed into the day folder. Leftovers (e.g. after a restart) are removed after 15 minutes.
- The cleanup only deletes files named like events inside date-named day folders. Protected events and any other files or folders are never touched.
- Lookback keeps a stream open permanently, which adds network load to the camera.

## License

MIT
