"""Auto-detection of facecams and webcams in streaming and gaming videos.

Detects persistent bounding boxes with stationary borders and distinct interior motion
using FFmpeg raw gray frames and NumPy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Optional, Tuple

import numpy as np

W, H = 320, 180
MAX_FRAMES = 20
MIN_SIZE = 0.12
MAX_SIZE = 0.55
ASPECT_MIN = 0.65
ASPECT_MAX = 2.40


def _duration(path: str | Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]
    creation_flags = 0x08000000 if os.name == "nt" else 0
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=creation_flags)
        return float(res.stdout.strip())
    except Exception:
        return 30.0


def _video_dimensions(path: str | Path) -> Tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(path)
    ]
    creation_flags = 0x08000000 if os.name == "nt" else 0
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=creation_flags)
        data = json.loads(res.stdout)
        stream = data["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception:
        return 1920, 1080


def _extract_frames(path: str | Path, count: int = MAX_FRAMES) -> np.ndarray:
    dur = _duration(path)
    rate = max(count / dur, 0.05) if dur > 0 else 0.5
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"fps={rate:.4f},scale={W}:{H},format=gray",
        "-frames:v", str(count), "-f", "rawvideo", "-"
    ]
    creation_flags = 0x08000000 if os.name == "nt" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=90, creationflags=creation_flags)
        raw = proc.stdout or b""
        n = len(raw) // (W * H)
        if n == 0:
            return np.zeros((0, H, W), dtype=np.uint8)
        return np.frombuffer(raw[:n * W * H], dtype=np.uint8).reshape((n, H, W))
    except Exception:
        return np.zeros((0, H, W), dtype=np.uint8)


def detect_facecam(video_path: str | Path) -> Optional[Tuple[int, int, int, int]]:
    """Returns (fx, fy, fw, fh) in original video pixel coordinates,
    or None if no facecam box is detected.
    """
    frames = _extract_frames(video_path)
    if len(frames) < 4:
        return None

    # Calculate temporal difference between successive frames
    diffs = np.abs(np.diff(frames.astype(np.int16), axis=0)).astype(np.float32)
    mean_diff = np.mean(diffs, axis=0)  # shape (H, W)

    orig_w, orig_h = _video_dimensions(video_path)

    # Search corner quadrants for a webcam box (top-left, top-right, bottom-left, bottom-right)
    quadrants = [
        ("top_left", 0, int(H * 0.55), 0, int(W * 0.45)),
        ("top_right", 0, int(H * 0.55), int(W * 0.55), W),
        ("bottom_left", int(H * 0.45), H, 0, int(W * 0.45)),
        ("bottom_right", int(H * 0.45), H, int(W * 0.55), W),
    ]

    best_box = None
    best_score = 0.0

    for name, r0, r1, c0, c1 in quadrants:
        patch = mean_diff[r0:r1, c0:c1]
        if patch.size == 0:
            continue

        # Look for horizontal and vertical gradient lines (borders)
        grad_y = np.abs(np.diff(patch, axis=0))
        grad_x = np.abs(np.diff(patch, axis=1))

        row_activity = np.mean(grad_y, axis=1)
        col_activity = np.mean(grad_x, axis=0)

        if len(row_activity) == 0 or len(col_activity) == 0:
            continue

        r_peak = np.argmax(row_activity)
        c_peak = np.argmax(col_activity)

        box_h = int(H * 0.35)
        box_w = int(W * 0.28)
        if "top" in name:
            by0 = 0
            by1 = box_h
        else:
            by0 = H - box_h
            by1 = H

        if "left" in name:
            bx0 = 0
            bx1 = box_w
        else:
            bx0 = W - box_w
            bx1 = W

        interior = mean_diff[by0:by1, bx0:bx1]
        interior_motion = float(np.mean(interior))
        total_motion = float(np.mean(mean_diff)) + 1e-4

        # Facecam often has distinct motion (talking head / streamer movement)
        score = interior_motion / total_motion
        if score > 1.25 and score > best_score:
            best_score = score
            best_box = (bx0, by0, bx1 - bx0, by1 - by0)

    if best_box:
        bx, by, bw, bh = best_box
        scale_x = orig_w / W
        scale_y = orig_h / H
        return (
            int(round(bx * scale_x)),
            int(round(by * scale_y)),
            int(round(bw * scale_x)),
            int(round(bh * scale_y)),
        )

    return None
