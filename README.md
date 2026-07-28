# Volume-Control-Using-Hand-Gestures

Control your system volume by pinching your thumb and index finger together or apart, tracked
live from your webcam using MediaPipe hand landmarks. The distance between the two fingertips
is mapped to a volume percentage, shown on-screen as a live bar plus a numeric readout. Making a
fist toggles mute on/off, and a peace sign (✌️) toggles play/pause for whatever media player is
active. Works on Windows, macOS, and Linux.

> **macOS note:** synthetic media-key presses require Accessibility permission. If play/pause
> doesn't work, add your terminal/IDE to System Settings → Privacy & Security → Accessibility.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

Press `q` to quit, or `p` to pause/resume gesture control (useful if you need to move your hand
near the camera without triggering volume, mute, or play/pause changes). A gesture legend is
always shown at the bottom of the window as a reminder.

### Options

| Flag | Default | Description |
| --- | --- | --- |
| `--camera` | `0` | Camera index to read from |
| `--min-dist` | `15` | Thumb-index distance (px) mapped to 0% volume |
| `--max-dist` | `220` | Thumb-index distance (px) mapped to 100% volume |
| `--calibrate` | off | Run an interactive calibration step (pinch closed, then open, pressing `c` each time) to set min/max distance for your own hand and camera setup instead of the defaults |
| `--detection-confidence` | `0.7` | MediaPipe hand detection confidence threshold |
| `--tracking-confidence` | `0.7` | MediaPipe hand tracking confidence threshold |
| `--smoothing` | `5` | Number of frames averaged to reduce jitter |

Example: `python main.py --calibrate --camera 1 --smoothing 8`

## How it works

1. Captures webcam frames with OpenCV and runs them through MediaPipe Hands to get 21 hand
   landmarks per frame.
2. Measures the pixel distance between the thumb tip (landmark 4) and index fingertip
   (landmark 8), smoothed over recent frames to avoid jumpy volume changes.
3. Maps that distance to a volume percentage and applies it through a small cross-platform
   audio backend (`pycaw` on Windows, `osascript` on macOS, `amixer` on Linux).
4. Detects a closed fist (four fingertips curled below their middle knuckles) to toggle mute,
   and a peace sign (index + middle extended, ring + pinky curled) to send a play/pause media
   key via `pynput`, each with its own cooldown so a held gesture doesn't repeat-fire.
5. Draws the hand skeleton, a volume bar, mute state, an FPS counter, a "no hand detected"
   notice, a brief "Play/Pause" flash, and a gesture legend directly on the video feed.
6. Pressing `p` pauses gesture control entirely (no MediaPipe processing runs while paused),
   so you can reposition your hand or step away without accidentally changing volume/mute state.
