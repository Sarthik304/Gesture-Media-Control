import argparse
import platform
import subprocess
import sys
import time
from collections import deque
from math import hypot

import cv2
import mediapipe as mp
import numpy as np
from pynput.keyboard import Controller as KeyboardController, Key


class VolumeController:
    """Cross-platform system volume control (Windows/macOS/Linux)."""

    def __init__(self):
        self.system = platform.system()
        if self.system == 'Windows':
            self._init_windows()
        elif self.system not in ('Darwin', 'Linux'):
            raise RuntimeError(f'Unsupported platform: {self.system}')

    def _init_windows(self):
        from comtypes import CLSCTX_ALL, GUID
        from ctypes import cast, POINTER
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        iid = GUID('{5CDF2C82-841E-4546-9722-0CF74078229A}')
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(iid, CLSCTX_ALL, None)
        self._volume = cast(interface, POINTER(IAudioEndpointVolume))
        self._vol_min, self._vol_max = self._volume.GetVolumeRange()[:2]

    def set_volume_percent(self, percent):
        percent = max(0.0, min(100.0, percent))
        if self.system == 'Windows':
            level = np.interp(percent, [0, 100], [self._vol_min, self._vol_max])
            self._volume.SetMasterVolumeLevel(level, None)
        elif self.system == 'Darwin':
            subprocess.run(
                ['osascript', '-e', f'set volume output volume {percent}'],
                check=False,
            )
        elif self.system == 'Linux':
            subprocess.run(
                ['amixer', '-D', 'pulse', 'sset', 'Master', f'{int(percent)}%'],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def set_mute(self, muted):
        if self.system == 'Windows':
            self._volume.SetMute(1 if muted else 0, None)
        elif self.system == 'Darwin':
            state = 'true' if muted else 'false'
            subprocess.run(
                ['osascript', '-e', f'set volume output muted {state}'],
                check=False,
            )
        elif self.system == 'Linux':
            subprocess.run(
                ['amixer', '-D', 'pulse', 'sset', 'Master', 'mute' if muted else 'unmute'],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )


def parse_args():
    parser = argparse.ArgumentParser(description='Control system volume with hand gestures.')
    parser.add_argument('--camera', type=int, default=0, help='camera index (default: 0)')
    parser.add_argument('--min-dist', type=float, default=15,
                         help='thumb-index distance mapped to 0%% volume (default: 15)')
    parser.add_argument('--max-dist', type=float, default=220,
                         help='thumb-index distance mapped to 100%% volume (default: 220)')
    parser.add_argument('--calibrate', action='store_true',
                         help='run an interactive calibration step to set min/max distance '
                              'for your hand and camera distance instead of using the defaults')
    parser.add_argument('--detection-confidence', type=float, default=0.7)
    parser.add_argument('--tracking-confidence', type=float, default=0.7)
    parser.add_argument('--smoothing', type=int, default=5,
                         help='number of frames averaged to reduce jitter (default: 5)')
    return parser.parse_args()


def is_fist(lmList):
    """Rough heuristic: index/middle/ring/pinky tips curled below their pip joints."""
    tips_and_pips = [(8, 6), (12, 10), (16, 14), (20, 18)]
    points = {row[0]: row for row in lmList}
    return all(points[tip][2] > points[pip][2] for tip, pip in tips_and_pips)


def is_peace_sign(lmList):
    """Index and middle fingers extended, ring and pinky curled (V sign)."""
    points = {row[0]: row for row in lmList}
    index_extended = points[8][2] < points[6][2]
    middle_extended = points[12][2] < points[10][2]
    ring_curled = points[16][2] > points[14][2]
    pinky_curled = points[20][2] > points[18][2]
    return index_extended and middle_extended and ring_curled and pinky_curled


def get_pinch_landmarks(img, hands, mpDraw, mpHands):
    """Runs one frame through MediaPipe and returns the landmark list (empty if no hand)."""
    imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = hands.process(imgRGB)
    lmList = []
    if results.multi_hand_landmarks:
        for handlandmark in results.multi_hand_landmarks:
            h, w, _ = img.shape
            for id, lm in enumerate(handlandmark.landmark):
                cx, cy = int(lm.x * w), int(lm.y * h)
                lmList.append([id, cx, cy])
            mpDraw.draw_landmarks(img, handlandmark, mpHands.HAND_CONNECTIONS)
    return lmList


def calibrate(cap, hands, mpDraw, mpHands):
    """Two-step interactive calibration: capture pinch-closed and pinch-open distances.

    Returns (min_dist, max_dist), or None if the user skips with Esc.
    """
    prompts = [
        'Pinch thumb and index finger together, then press "c"',
        'Spread thumb and index finger apart, then press "c"',
    ]
    captured = []
    step = 0
    while step < 2:
        success, img = cap.read()
        if not success:
            return None

        lmList = get_pinch_landmarks(img, hands, mpDraw, mpHands)
        length = None
        if lmList:
            x1, y1 = lmList[4][1], lmList[4][2]
            x2, y2 = lmList[8][1], lmList[8][2]
            cv2.circle(img, (x1, y1), 15, (255, 0, 0), cv2.FILLED)
            cv2.circle(img, (x2, y2), 15, (255, 0, 0), cv2.FILLED)
            cv2.line(img, (x1, y1), (x2, y2), (255, 0, 0), 3)
            length = hypot(x2 - x1, y2 - y1)

        cv2.putText(img, f'Calibration step {step + 1}/2', (30, 50),
                    cv2.FONT_HERSHEY_COMPLEX, 0.9, (0, 255, 255), 2)
        cv2.putText(img, prompts[step], (30, 90),
                    cv2.FONT_HERSHEY_COMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(img, 'Press "Esc" to skip calibration', (30, img.shape[0] - 20),
                    cv2.FONT_HERSHEY_COMPLEX, 0.6, (200, 200, 200), 1)

        cv2.imshow('Image', img)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            return None
        if key == ord('c') and length is not None:
            captured.append(length)
            step += 1

    min_dist, max_dist = sorted(captured)
    if max_dist - min_dist < 10:
        print('Calibration range too small, keeping default min/max distance.', file=sys.stderr)
        return None
    return min_dist, max_dist


def draw_legend(img):
    h = img.shape[0]
    lines = [
        'Pinch: volume   Fist: mute   Peace sign: play/pause',
        '"p": pause gestures   "q": quit',
    ]
    y = h - 15 - (len(lines) - 1) * 20
    for line in lines:
        cv2.putText(img, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += 20


def main():
    args = parse_args()

    try:
        volume_ctl = VolumeController()
    except RuntimeError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f'Error: could not open camera index {args.camera}', file=sys.stderr)
        sys.exit(1)

    mpHands = mp.solutions.hands
    hands = mpHands.Hands(
        max_num_hands=1,
        min_detection_confidence=args.detection_confidence,
        min_tracking_confidence=args.tracking_confidence,
    )
    mpDraw = mp.solutions.drawing_utils

    keyboard_ctl = KeyboardController()

    min_dist, max_dist = args.min_dist, args.max_dist
    if args.calibrate:
        result = calibrate(cap, hands, mpDraw, mpHands)
        if result:
            min_dist, max_dist = result
            print(f'Calibrated distance range: {min_dist:.1f} - {max_dist:.1f}px')

    length_history = deque(maxlen=max(1, args.smoothing))
    muted = False
    paused = False
    last_mute_toggle = 0.0
    mute_cooldown = 1.5
    last_playpause_toggle = 0.0
    playpause_cooldown = 1.0
    prev_frame_time = time.time()

    try:
        while True:
            success, img = cap.read()
            if not success:
                print('Error: failed to read frame from camera', file=sys.stderr)
                break

            if paused:
                cv2.putText(img, 'PAUSED - press "p" to resume', (30, 50),
                            cv2.FONT_HERSHEY_COMPLEX, 1, (0, 165, 255), 2)
            else:
                lmList = get_pinch_landmarks(img, hands, mpDraw, mpHands)

                if lmList:
                    now = time.time()
                    if is_fist(lmList) and now - last_mute_toggle > mute_cooldown:
                        muted = not muted
                        volume_ctl.set_mute(muted)
                        last_mute_toggle = now
                    elif is_peace_sign(lmList) and now - last_playpause_toggle > playpause_cooldown:
                        keyboard_ctl.tap(Key.media_play_pause)
                        last_playpause_toggle = now

                    x1, y1 = lmList[4][1], lmList[4][2]
                    x2, y2 = lmList[8][1], lmList[8][2]
                    cv2.circle(img, (x1, y1), 15, (255, 0, 0), cv2.FILLED)
                    cv2.circle(img, (x2, y2), 15, (255, 0, 0), cv2.FILLED)
                    cv2.line(img, (x1, y1), (x2, y2), (255, 0, 0), 3)

                    length_history.append(hypot(x2 - x1, y2 - y1))
                    length = sum(length_history) / len(length_history)

                    if not muted:
                        volPercent = np.interp(length, [min_dist, max_dist], [0, 100])
                        volume_ctl.set_volume_percent(volPercent)
                    else:
                        volPercent = 0

                    barHeight = np.interp(length, [min_dist, max_dist], [400, 150])
                    cv2.rectangle(img, (50, 150), (85, 400), (255, 0, 0), 3)
                    cv2.rectangle(img, (50, int(barHeight)), (85, 400), (255, 0, 0), cv2.FILLED)
                    label = 'MUTED' if muted else f'{int(volPercent)} %'
                    cv2.putText(img, label, (30, 430),
                                cv2.FONT_HERSHEY_COMPLEX, 1, (255, 0, 0), 2)
                else:
                    cv2.putText(img, 'No hand detected', (30, 50),
                                cv2.FONT_HERSHEY_COMPLEX, 1, (0, 0, 255), 2)

                if time.time() - last_playpause_toggle < 0.8:
                    cv2.putText(img, 'Play/Pause', (250, 50),
                                cv2.FONT_HERSHEY_COMPLEX, 1, (0, 255, 255), 2)

            draw_legend(img)

            now = time.time()
            fps = 1 / (now - prev_frame_time) if now != prev_frame_time else 0
            prev_frame_time = now
            cv2.putText(img, f'FPS: {int(fps)}', (30, 90),
                        cv2.FONT_HERSHEY_COMPLEX, 1, (0, 255, 0), 2)

            cv2.imshow('Image', img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('p'):
                paused = not paused
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
