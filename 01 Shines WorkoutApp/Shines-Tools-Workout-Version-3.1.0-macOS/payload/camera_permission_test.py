#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
import cv2

parser = argparse.ArgumentParser()
parser.add_argument('--home', type=Path, required=True)
args = parser.parse_args()

print('\nCamera permission check')
print('macOS may ask: “Terminal would like to access the camera.”')
print('Click Allow. The installer will wait for up to 45 seconds.\n')

selected = None
started = time.time()
while time.time() - started < 45:
    for index in range(4):
        cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        if cap.isOpened():
            received, _ = cap.read()
            cap.release()
            if received:
                selected = index
                break
        else:
            cap.release()
    if selected is not None:
        break
    time.sleep(1.5)

if selected is None:
    print('CAMERA_PERMISSION_NOT_CONFIRMED')
    raise SystemExit(2)

settings_path = args.home / 'data' / 'settings.json'
settings_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if settings_path.exists():
    try:
        data = json.loads(settings_path.read_text())
    except Exception:
        data = {}
data['default_camera'] = selected
settings_path.write_text(json.dumps(data, indent=2))
print(f'CAMERA_READY index={selected}')
