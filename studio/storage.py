"""Storage Protection & Data Directory Management (Feature 6).

Provides proactive disk space monitoring (<5 GB warning), disk usage stats,
and safe data directory migration across local and external drives.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import time
from typing import Dict, Optional, Tuple

from . import config, db

logger = logging.getLogger("clipforge.storage")

MIN_FREE_DISK_GB = 5.0


def drive_of(path: Path | str) -> str:
    """Returns root drive letter or anchor (e.g. 'C:' or '/')."""
    p = Path(path).resolve()
    return p.drive or p.anchor or str(p)


def get_disk_free_gb(path: Optional[Path | str] = None) -> float:
    """Calculates available free space in GB on the target path's drive."""
    target = Path(path or config.DATA_DIR).resolve()
    try:
        usage = shutil.disk_usage(target)
        return round(usage.free / (1024 ** 3), 2)
    except Exception as e:
        logger.warning(f"Failed to check disk usage for {target}: {e}")
        return 50.0  # Safe fallback


def get_storage_info() -> Dict[str, Any]:
    """Returns comprehensive storage metrics for the ClipForge data drive."""
    target = config.DATA_DIR.resolve()
    try:
        usage = shutil.disk_usage(target)
        total_gb = round(usage.total / (1024 ** 3), 2)
        free_gb = round(usage.free / (1024 ** 3), 2)
        used_gb = round(usage.used / (1024 ** 3), 2)
    except Exception:
        total_gb, free_gb, used_gb = 100.0, 50.0, 50.0

    # Calculate actual ClipForge folder size
    app_used_bytes = 0
    try:
        for r, _, files in os.walk(target):
            for f in files:
                try:
                    app_used_bytes += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
    except Exception:
        pass
    app_used_gb = round(app_used_bytes / (1024 ** 3), 2)

    is_low_space = free_gb < MIN_FREE_DISK_GB
    warning = ""
    if is_low_space:
        warning = (f"⚠️ Storage Warning: Only {free_gb:.1f} GB free on drive {drive_of(target)}. "
                   f"ClipForge requires at least {MIN_FREE_DISK_GB:.0f} GB for safe video rendering.")

    return {
        "path": str(target),
        "drive": drive_of(target),
        "total_gb": total_gb,
        "free_gb": free_gb,
        "used_gb": used_gb,
        "app_used_gb": app_used_gb,
        "min_free_gb": MIN_FREE_DISK_GB,
        "is_low_space": is_low_space,
        "warning": warning
    }


def check_disk_space(min_gb: float = MIN_FREE_DISK_GB) -> Tuple[bool, str]:
    """Pre-flight check before video downloads or rendering."""
    free = get_disk_free_gb(config.DATA_DIR)
    if free < min_gb:
        msg = (f"Insufficient disk space ({free:.1f} GB available, {min_gb:.1f} GB required). "
               f"Please free up space on drive {drive_of(config.DATA_DIR)} or move your data folder.")
        return False, msg
    return True, ""


def move_data_dir(new_target_path: str) -> Dict[str, Any]:
    """Safely migrates the ClipForge data directory to another drive or folder."""
    dest = Path(new_target_path).resolve()
    if dest == config.DATA_DIR.resolve():
        return {"status": "unchanged", "message": "Target path is identical to current data directory.", "path": str(dest)}

    dest.mkdir(parents=True, exist_ok=True)

    # Check target drive space
    usage = shutil.disk_usage(dest)
    target_free_gb = usage.free / (1024 ** 3)
    current_size_gb = sum(f.stat().st_size for f in config.DATA_DIR.rglob('*') if f.is_file()) / (1024 ** 3)

    if target_free_gb < current_size_gb + MIN_FREE_DISK_GB:
        raise ValueError(f"Target drive lacks sufficient free space ({target_free_gb:.1f} GB free, needs {current_size_gb + MIN_FREE_DISK_GB:.1f} GB).")

    logger.info(f"Migrating data directory from {config.DATA_DIR} to {dest}...")
    for item in config.DATA_DIR.iterdir():
        target_item = dest / item.name
        if item.is_dir():
            shutil.copytree(str(item), str(target_item), dirs_exist_ok=True)
        else:
            shutil.copy2(str(item), str(target_item))

    # Persist in DB and config
    db.set_setting("custom_data_dir", str(dest))
    config.DATA_DIR = dest
    config.UPLOADS_DIR = dest / "uploads"
    config.CLIPS_DIR = dest / "clips"
    config.MODELS_DIR = dest / "models"
    config.DB_PATH = dest / "clipforge.db"

    return {
        "status": "success",
        "message": f"Successfully migrated data directory to {dest}",
        "new_path": str(dest)
    }
