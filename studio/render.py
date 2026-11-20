"""9:16 Vertical Video Renderer, ASS Subtitle Engine, and Big Text Hook Overlays.

Renders vertical shorts (1080x1920) with blurred background padding, 2-box facecam split,
or center crop, burning in animated dynamic karaoke captions and a prominent Big Text Hook banner.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

from . import config, roman

logger = logging.getLogger("clipforge.render")

W, H = config.OUT_W, config.OUT_H

STYLES = {
    "bounce": {
        "label": "Bouncy Neon",
        "font": "Poppins-ExtraBold.ttf",
        "font_name": "Poppins ExtraBold",
        "size": 118,
        "base": "FFFFFF",
        "active": "00FFFF",  # Neon Yellow/Cyan
        "outline": 7,
        "pop": 115,
        "upper": True,
        "per": 3,
    },
    "hype": {
        "label": "Hype Anton",
        "font": "Anton-Regular.ttf",
        "font_name": "Anton",
        "size": 136,
        "base": "FFFFFF",
        "active": "00E5FF",  # Bright Yellow-Orange
        "outline": 7,
        "pop": 118,
        "upper": True,
        "per": 2,
    },
    "clean": {
        "label": "Clean Modern",
        "font": "Poppins-ExtraBold.ttf",
        "font_name": "Poppins ExtraBold",
        "size": 95,
        "base": "FFFFFF",
        "active": "00FF7F",  # Spring Green
        "outline": 5,
        "pop": 108,
        "upper": False,
        "per": 4,
    },
}

HOOK_STYLE = {
    "font": "Poppins-ExtraBold.ttf",
    "font_name": "Poppins ExtraBold",
    "size": 84,
    "text_color": "FFFFFF",
    "box_color": "10151C",  # Sleek dark navy/slate background
    "accent_color": "00E5FF",
    "pad_x": 42,
    "pad_y": 24,
    "radius": 24,
    "max_w": 960,
}

CAP_MAX_W = 980


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _clean_str(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text or ""))).strip()


def _get_font(font_filename: str, size: int) -> ImageFont.FreeTypeFont:
    font_path = config.FONTS_DIR / font_filename
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default()


def _calc_geometry(src_w: int, src_h: int, layout: str) -> Tuple[str, int, int, int]:
    """Calculates vertical positioning: layout, foreground height, hook y-center, caption y-center."""
    if src_h >= src_w and layout != "crop":
        layout = "crop"

    if layout == "blur":
        fg_h = min(H, int(round(W * src_h / src_w / 2)) * 2)
    elif layout == "zoom":
        fg_h = 1050
    else:
        fg_h = H

    top = (H - fg_h) // 2
    if layout in ("crop", "gameplay"):
        return layout, fg_h, 310, 1380
    return layout, fg_h, max(240, top - 180), min(1660, top + fg_h + 170)


def _build_hook_events(hook_text: str, dur: float, y_center: int) -> List[str]:
    """Builds vector rounded pill box and centered bold text for the top Big Text banner."""
    if not hook_text:
        return []

    words = hook_text.strip().split()
    if not words:
        return []

    font_obj = _get_font(HOOK_STYLE["font"], HOOK_STYLE["size"])
    full_str = " ".join(words)
    w_len = font_obj.getlength(full_str)

    lines = [full_str]
    curr_size = HOOK_STYLE["size"]

    if w_len > HOOK_STYLE["max_w"] and len(words) > 1:
        # Split into two lines
        mid = len(words) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        w_len = max(font_obj.getlength(l) for l in lines)

    if w_len > HOOK_STYLE["max_w"]:
        curr_size = max(42, int(curr_size * HOOK_STYLE["max_w"] / w_len))
        font_obj = _get_font(HOOK_STYLE["font"], curr_size)
        w_len = max(font_obj.getlength(l) for l in lines)

    line_h = curr_size * 1.2
    bw = w_len + 2 * HOOK_STYLE["pad_x"]
    bh = line_h * len(lines) + 2 * HOOK_STYLE["pad_y"]
    r = min(HOOK_STYLE["radius"], bh / 2)

    x0 = (W - bw) / 2
    y0 = y_center - bh / 2
    x1 = x0 + bw
    y1 = y0 + bh

    def n(val):
        return f"{val:.0f}"

    # ASS vector drawing command for rounded rectangle
    pill_path = (
        f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} "
        f"b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
        f"l {n(x1)} {n(y1 - r)} "
        f"b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
        f"l {n(x0 + r)} {n(y1)} "
        f"b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
        f"l {n(x0)} {n(y0 + r)} "
        f"b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}"
    )

    span = f"{_ts(0)},{_ts(dur)}"
    events = [
        # Dark pill container with thin neon border outline
        f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(150,0)\\bord4\\3c&H00D7FF&\\c&H{HOOK_STYLE['box_color']}&\\p1}}{pill_path}{{\\p0}}"
    ]

    for i, line in enumerate(lines):
        cy = y_center - line_h * (len(lines) - 1) / 2 + i * line_h
        events.append(
            f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fad(150,0)\\fs{curr_size}\\c&H{HOOK_STYLE['text_color']}&}}{line}"
        )

    return events


def build_ass_subtitles(
    words: List[dict],
    start: float,
    end: float,
    hook_text: str,
    style_key: str = "bounce",
    highlight_words: Optional[List[str]] = None,
    hook_y: int = 310,
    cap_y: int = 1380
) -> str:
    """Builds a complete ASS subtitle file with animated dynamic word highlights and top hook banner."""
    st = STYLES.get(style_key, STYLES["bounce"])
    dur = max(1.0, end - start)
    highlight = set(re.sub(r"\W", "", w.lower()) for w in (highlight_words or []))

    header = f"""[Script Info]
Title: ClipForge Studio Dynamic Subtitles
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font_name']},{st['size']},&H00{st['base']},&H00{st['base']},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{st['outline']},4,5,0,0,0,1
Style: Hook,{HOOK_STYLE['font_name']},{HOOK_STYLE['size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    # 1. Big Text Hook banner
    clean_hook = roman.to_roman(_clean_str(hook_text)).upper()
    events.extend(_build_hook_events(clean_hook, dur, hook_y))

    # 2. Dynamic word-by-word karaoke captions
    inside_words = [
        dict(w, w=_clean_str(roman.to_roman(w["w"])))
        for w in words
        if w["s"] >= start - 0.1 and w["s"] < end
    ]
    inside_words = sorted((w for w in inside_words if w["w"]), key=lambda x: x["s"])

    # Group words into chunks
    groups = []
    curr_group = []
    per_group = st["per"]

    for w in inside_words:
        if curr_group and (
            len(curr_group) >= per_group
            or (w["s"] - curr_group[-1]["e"] > 0.45)
            or (curr_group[-1]["w"][-1:] in ".?!")
        ):
            groups.append(curr_group)
            curr_group = []
        curr_group.append(w)
    if curr_group:
        groups.append(curr_group)

    font_obj = _get_font(st["font"], st["size"])

    for gi, grp in enumerate(groups):
        g_start = max(0.0, grp[0]["s"] - start)
        next_g_start = groups[gi + 1][0]["s"] - start if gi + 1 < len(groups) else dur
        g_end = min(grp[-1]["e"] - start + 0.3, next_g_start)

        if g_end - g_start < 0.05:
            continue

        raw_texts = [re.sub(r"[.,;:]+$", "", x["w"]) for x in grp]
        display_texts = [t.upper() if st["upper"] else t for t in raw_texts]

        # Measure widths
        sizes = [font_obj.getlength(t) for t in display_texts]
        gap = 26
        total_w = sum(sizes) + gap * (len(sizes) - 1)

        # Scale down if exceeds caption margin
        cur_size = st["size"]
        if total_w > CAP_MAX_W:
            scale_ratio = CAP_MAX_W / total_w
            cur_size = max(36, int(cur_size * scale_ratio))
            font_scaled = _get_font(st["font"], cur_size)
            sizes = [font_scaled.getlength(t) for t in display_texts]
            gap = int(gap * scale_ratio)
            total_w = sum(sizes) + gap * (len(sizes) - 1)

        x_cursor = (W - total_w) / 2
        cy = cap_y

        for i, (w_item, disp_text, wd) in enumerate(zip(grp, display_texts, sizes)):
            w_start = max(g_start, w_item["s"] - start)
            w_end = min(g_end, (grp[i + 1]["s"] - start) if i + 1 < len(grp) else g_end)

            center_x = x_cursor + wd / 2
            x_cursor += wd + gap

            pos_tag = f"\\an5\\pos({center_x:.0f},{cy})\\fs{cur_size}"
            is_strong = re.sub(r"\W", "", w_item["w"].lower()) in highlight
            base_col = st["base"]
            active_col = st["active"]

            pop = st["pop"]

            # Waiting
            if w_start - g_start >= 0.02:
                events.append(
                    f"Dialogue: 1,{_ts(g_start)},{_ts(w_start)},Cap,,0,0,0,,{{{pos_tag}\\c&H{base_col}&}}{disp_text}"
                )

            # Active karaoke highlight with animated scale pop
            if w_end - w_start >= 0.02:
                events.append(
                    f"Dialogue: 2,{_ts(w_start)},{_ts(w_end)},Cap,,0,0,0,,{{{pos_tag}\\c&H{active_col}&\\fscx96\\fscy96\\t(0,80,\\fscx{pop}\\fscy{pop})\\t(80,180,\\fscx{pop-6}\\fscy{pop-6})}}{disp_text}"
                )

            # Spoken
            if g_end - w_end >= 0.02:
                events.append(
                    f"Dialogue: 1,{_ts(w_end)},{_ts(g_end)},Cap,,0,0,0,,{{{pos_tag}\\c&H{base_col}&\\fscx100\\fscy100}}{disp_text}"
                )

    return header + "\n".join(events) + "\n"


def _build_filter_graph(layout: str, fg_h: int, facecam: Optional[Tuple[int, int, int, int]] = None) -> str:
    """Builds the FFmpeg video filtergraph string."""
    pip_w = 380
    pip_margin = 28

    def _parse_facecam(fc):
        if not fc:
            return 0, 0, 0, 0
        if isinstance(fc, dict):
            return int(fc.get("x", 0)), int(fc.get("y", 0)), int(fc.get("w", 0)), int(fc.get("h", 0))
        if isinstance(fc, (list, tuple)) and len(fc) == 4:
            return int(fc[0]), int(fc[1]), int(fc[2]), int(fc[3])
        return 0, 0, 0, 0

    fx, fy, fw, fh = _parse_facecam(facecam)

    if layout == "split":
        # Dual-Screen Stacked Layout (Feature 6):
        # Top 35% (672px): Active speaker facecam zoomed in
        # Bottom 65% (1248px): Gameplay or main screen
        top_h = 672
        bot_h = 1248
        if fw > 10 and fh > 10:
            return (
                f"[0:v]fps={config.OUT_FPS},split=2[raw_fc][raw_main];"
                f"[raw_fc]crop={fw}:{fh}:{fx}:{fy},scale={W}:{top_h}:force_original_aspect_ratio=increase,crop={W}:{top_h},setsar=1[top_view];"
                f"[raw_main]scale={W}:{bot_h}:force_original_aspect_ratio=increase,crop={W}:{bot_h},setsar=1[bot_view];"
                f"[top_view][bot_view]vstack=inputs=2[v0];"
            )
        else:
            return (
                f"[0:v]fps={config.OUT_FPS},split=2[raw_top][raw_main];"
                f"[raw_top]crop=iw:ih*0.5:0:0,scale={W}:{top_h}:force_original_aspect_ratio=increase,crop={W}:{top_h},setsar=1[top_view];"
                f"[raw_main]scale={W}:{bot_h}:force_original_aspect_ratio=increase,crop={W}:{bot_h},setsar=1[bot_view];"
                f"[top_view][bot_view]vstack=inputs=2[v0];"
            )

    if layout == "gameplay" and fw > 10 and fh > 10:
        pip_h = max(2, int(round(pip_w * fh / fw)))
        return (
            f"[0:v]fps={config.OUT_FPS},split=2[base][fc];"
            f"[base]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b];"
            f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={pip_w}:{pip_h},setsar=1[p];"
            f"[b][p]overlay={W - pip_w - pip_margin}:{pip_margin}[v0];"
        )

    if layout == "crop":
        return f"[0:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[v0];"

    # Default 'blur' layout: 9:16 background blur + crisp centered foreground
    return (
        f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
        f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,"
        f"scale={W}:{H},eq=brightness=-0.14:saturation=1.15[bg];"
        f"[b]scale={W}:{fg_h}:force_original_aspect_ratio=increase,crop={W}:{fg_h}[fg];"
        f"[bg][fg]overlay=0:(H-h)/2,setsar=1[v0];"
    )


def ensure_whoosh_sfx() -> Path:
    """Synthesizes a subtle, clean 0.4s audio whoosh accent for the Big Text entrance."""
    sfx_path = config.DATA_DIR / "sfx" / "whoosh.wav"
    if sfx_path.exists():
        return sfx_path
    sfx_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import numpy as np
        import soundfile as sf
        sr = 48000
        dur = 0.42
        n_samples = int(sr * dur)
        t = np.linspace(0, dur, n_samples, endpoint=False)
        noise = np.random.normal(0, 0.22, n_samples)
        sweep = np.sin(2 * np.pi * (220 + 750 * (1 - t / dur) ** 2) * t)
        env = (np.sin(np.pi * (t / dur))) ** 2.2
        signal = (0.55 * sweep + 0.45 * noise) * env * 0.45
        sf.write(str(sfx_path), signal.astype(np.float32), sr)
    except Exception as e:
        logger.warning(f"Could not synthesize whoosh SFX: {e}")
    return sfx_path


def render_single_clip(
    src_video: str | Path,
    out_dir: str | Path,
    clip_id: str,
    clip_info: dict,
    words: List[dict],
    src_w: int = 1920,
    src_h: int = 1080
) -> dict:
    """Renders 1080x1920 vertical MP4, animated ASS subtitles, and thumbnail JPG."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src_video = Path(src_video).resolve()
    start = float(clip_info["start"])
    end = float(clip_info["end"])
    dur = max(0.5, end - start)
    layout = clip_info.get("layout", "blur")
    facecam = clip_info.get("facecam")
    add_whoosh = bool(clip_info.get("whoosh", False))

    layout, fg_h, hook_y, cap_y = _calc_geometry(src_w, src_h, layout)

    ass_text = build_ass_subtitles(
        words=words,
        start=start,
        end=end,
        hook_text=clip_info.get("hook", ""),
        style_key=clip_info.get("style", "bounce"),
        highlight_words=clip_info.get("highlight_words", []),
        hook_y=hook_y,
        cap_y=cap_y
    )

    work_dir = Path(tempfile.mkdtemp(prefix="cf_render_"))
    try:
        ass_filename = f"{clip_id}.ass"
        ass_path = work_dir / ass_filename
        ass_path.write_text(ass_text, encoding="utf-8")

        # Copy font assets into relative workdir folder
        f_dir = work_dir / "fonts"
        f_dir.mkdir(parents=True, exist_ok=True)
        for ttf in config.FONTS_DIR.glob("*.ttf"):
            shutil.copyfile(ttf, f_dir / ttf.name)

        fc = _build_filter_graph(layout, fg_h, facecam) + f"[v0]ass={ass_filename}:fontsdir=fonts[v]"

        out_mp4_name = f"{clip_id}.mp4"

        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{start:.2f}",
            "-t", f"{dur:.2f}",
            "-i", str(src_video)
        ]

        # Audio handling: check if Whoosh accent SFX is enabled
        if add_whoosh:
            whoosh_file = ensure_whoosh_sfx()
            if whoosh_file.exists():
                cmd.extend(["-i", str(whoosh_file)])
                fc_with_audio = (
                    fc + ";[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2,"
                    "loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
                )
                cmd.extend([
                    "-filter_complex", fc_with_audio,
                    "-map", "[v]",
                    "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000"
                ])
            else:
                cmd.extend([
                    "-filter_complex", fc,
                    "-map", "[v]",
                    "-map", "0:a:0?",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000"
                ])
        else:
            cmd.extend([
                "-filter_complex", fc,
                "-map", "[v]",
                "-map", "0:a:0?",
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000"
            ])

        cmd.extend([
            "-c:v", "libx264", "-crf", "22", "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            out_mp4_name
        ])

        creation_flags = 0x08000000 if os.name == "nt" else 0
        subprocess.run(cmd, cwd=str(work_dir), check=True, creationflags=creation_flags)

        # Generate cover thumbnail
        cover_name = f"{clip_id}.jpg"
        cover_time = min(1.2, dur / 2.0)
        thumb_cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{cover_time:.2f}",
            "-i", out_mp4_name,
            "-frames:v", "1",
            "-q:v", "3",
            cover_name
        ]
        subprocess.run(thumb_cmd, cwd=str(work_dir), check=True, creationflags=creation_flags)

        # Move artifacts to final out_dir
        final_mp4 = out_dir / out_mp4_name
        final_jpg = out_dir / cover_name
        final_ass = out_dir / ass_filename

        shutil.move(str(work_dir / out_mp4_name), str(final_mp4))
        shutil.move(str(work_dir / cover_name), str(final_jpg))
        shutil.move(str(work_dir / ass_filename), str(final_ass))

        return {
            "video_file": out_mp4_name,
            "cover_file": cover_name,
            "ass_file": ass_filename,
            "video_path": str(final_mp4.resolve()),
            "cover_path": str(final_jpg.resolve()),
            "layout": layout
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def fast_reapply_hook(
    src_video: str | Path,
    out_dir: str | Path,
    clip_id: str,
    clip_info: dict,
    words: List[dict],
    src_w: int = 1920,
    src_h: int = 1080
) -> dict:
    """Fast Big Text Hook re-burn (Feature 2): Re-renders video with updated hook in < 5 seconds."""
    out_dir = Path(out_dir)
    src_video = Path(src_video).resolve()
    start = float(clip_info["start"])
    end = float(clip_info["end"])
    dur = max(0.5, end - start)
    layout = clip_info.get("layout", "blur")
    facecam = clip_info.get("facecam")

    layout, fg_h, hook_y, cap_y = _calc_geometry(src_w, src_h, layout)

    ass_text = build_ass_subtitles(
        words=words,
        start=start,
        end=end,
        hook_text=clip_info.get("hook", ""),
        style_key=clip_info.get("style", "bounce"),
        highlight_words=clip_info.get("highlight_words", []),
        hook_y=hook_y,
        cap_y=cap_y
    )

    work_dir = Path(tempfile.mkdtemp(prefix="cf_fasthook_"))
    try:
        ass_filename = f"{clip_id}.ass"
        ass_path = work_dir / ass_filename
        ass_path.write_text(ass_text, encoding="utf-8")

        f_dir = work_dir / "fonts"
        f_dir.mkdir(parents=True, exist_ok=True)
        for ttf in config.FONTS_DIR.glob("*.ttf"):
            shutil.copyfile(ttf, f_dir / ttf.name)

        fc = _build_filter_graph(layout, fg_h, facecam) + f"[v0]ass={ass_filename}:fontsdir=fonts[v]"

        out_mp4_name = f"{clip_id}.mp4"
        # Uses ultrafast preset for sub-5s render
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{start:.2f}",
            "-t", f"{dur:.2f}",
            "-i", str(src_video),
            "-filter_complex", fc,
            "-map", "[v]",
            "-map", "0:a:0?",
            "-c:a", "copy",
            "-c:v", "libx264", "-crf", "22", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            out_mp4_name
        ]

        creation_flags = 0x08000000 if os.name == "nt" else 0
        subprocess.run(cmd, cwd=str(work_dir), check=True, creationflags=creation_flags)

        # Update cover thumbnail
        cover_name = f"{clip_id}.jpg"
        cover_time = min(1.2, dur / 2.0)
        thumb_cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{cover_time:.2f}",
            "-i", out_mp4_name,
            "-frames:v", "1",
            "-q:v", "3",
            cover_name
        ]
        subprocess.run(thumb_cmd, cwd=str(work_dir), check=True, creationflags=creation_flags)

        final_mp4 = out_dir / out_mp4_name
        final_jpg = out_dir / cover_name
        final_ass = out_dir / ass_filename

        shutil.move(str(work_dir / out_mp4_name), str(final_mp4))
        shutil.move(str(work_dir / cover_name), str(final_jpg))
        shutil.move(str(work_dir / ass_filename), str(final_ass))

        return {
            "video_file": out_mp4_name,
            "cover_file": cover_name,
            "ass_file": ass_filename,
            "video_path": str(final_mp4.resolve()),
            "cover_path": str(final_jpg.resolve()),
            "layout": layout
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

