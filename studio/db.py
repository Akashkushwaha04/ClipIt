"""ClipForge Studio SQLite Database Layer.

Provides structured persistence for video processing jobs, generated clips,
social accounts, and application settings with WAL mode.
"""
import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from . import config

_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db():
    with _lock, get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_url TEXT,
            title TEXT DEFAULT 'Untitled Video',
            uploader TEXT DEFAULT 'Unknown',
            duration REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            stage TEXT DEFAULT 'queued',
            progress INTEGER DEFAULT 0,
            stage_message TEXT DEFAULT '',
            error TEXT DEFAULT '',
            video_path TEXT,
            audio_path TEXT,
            transcript_json TEXT,
            loudness_json TEXT,
            facecam_json TEXT,
            created_at REAL,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            clip_index INTEGER DEFAULT 0,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            duration REAL NOT NULL,
            score INTEGER DEFAULT 80,
            category TEXT DEFAULT 'highlight',
            hook TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            hashtags_json TEXT DEFAULT '[]',
            highlight_words_json TEXT DEFAULT '[]',
            reason TEXT DEFAULT '',
            layout TEXT DEFAULT 'blur',
            video_file TEXT,
            cover_file TEXT,
            ass_file TEXT,
            youtube_video_id TEXT,
            youtube_url TEXT,
            uploaded_to_youtube INTEGER DEFAULT 0,
            created_at REAL,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            name TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at REAL DEFAULT 0,
            meta_json TEXT DEFAULT '{}',
            created_at REAL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id TEXT PRIMARY KEY,
            clip_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            account_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            privacy TEXT DEFAULT 'public',
            scheduled_time REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            error TEXT DEFAULT '',
            published_url TEXT DEFAULT '',
            created_at REAL,
            FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS clip_analytics (
            clip_id TEXT PRIMARY KEY,
            platform TEXT NOT NULL DEFAULT 'youtube',
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            updated_at REAL,
            FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS creators (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            channels_json TEXT DEFAULT '{}',
            style TEXT DEFAULT 'bounce',
            layout TEXT DEFAULT 'split',
            min_len INTEGER DEFAULT 15,
            max_len INTEGER DEFAULT 60,
            min_score INTEGER DEFAULT 80,
            autopost INTEGER DEFAULT 0,
            daily_cap INTEGER DEFAULT 5,
            post_gap_min INTEGER DEFAULT 45,
            default_tags_json TEXT DEFAULT '[]',
            created_at REAL
        );

        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0.0,
            created_at REAL
        );
        """)
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN creator_id TEXT DEFAULT '';")
        except sqlite3.OperationalError:
            pass  # already exists
        conn.commit()


# Initialize upon module load
init_db()


# --- Job Operations ---

def create_job(job_id: str, source_type: str, source_url: str = "", title: str = "", uploader: str = "") -> dict:
    now = time.time()
    with _lock, get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO jobs (id, source_type, source_url, title, uploader, status, stage, progress, stage_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', 'queued', 0, 'Job initialized', ?, ?)
        """, (job_id, source_type, source_url, title or "Processing Video...", uploader or "ClipForge", now, now))
        conn.commit()
    return get_job(job_id)


def update_job(job_id: str, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_job(job_id)
    kwargs["updated_at"] = time.time()
    cols = []
    vals = []
    for k, v in kwargs.items():
        cols.append(f"{k} = ?")
        if isinstance(v, (dict, list)):
            vals.append(json.dumps(v))
        else:
            vals.append(v)
    vals.append(job_id)
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_job(job_id)


def get_job(job_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for f in ("transcript_json", "loudness_json", "facecam_json"):
            if d.get(f):
                try:
                    d[f.replace("_json", "")] = json.loads(d[f])
                except Exception:
                    d[f.replace("_json", "")] = None
        return d


def list_jobs(limit: int = 50) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        jobs = []
        for r in rows:
            d = dict(r)
            jobs.append(d)
        return jobs


# --- Clip Operations ---

def create_clip(clip_data: dict) -> dict:
    cid = clip_data.get("id") or f"clip_{int(time.time()*1000)}_{clip_data.get('clip_index', 0)}"
    now = time.time()
    with _lock, get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO clips (
                id, job_id, clip_index, start_time, end_time, duration, score, category,
                hook, title, description, tags_json, hashtags_json, highlight_words_json,
                reason, layout, video_file, cover_file, ass_file, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cid,
            clip_data["job_id"],
            clip_data.get("clip_index", 0),
            clip_data["start_time"],
            clip_data["end_time"],
            clip_data.get("duration", clip_data["end_time"] - clip_data["start_time"]),
            clip_data.get("score", 85),
            clip_data.get("category", "highlight"),
            clip_data.get("hook", ""),
            clip_data.get("title", ""),
            clip_data.get("description", ""),
            json.dumps(clip_data.get("tags", [])),
            json.dumps(clip_data.get("hashtags", [])),
            json.dumps(clip_data.get("highlight_words", [])),
            clip_data.get("reason", ""),
            clip_data.get("layout", "blur"),
            clip_data.get("video_file", ""),
            clip_data.get("cover_file", ""),
            clip_data.get("ass_file", ""),
            now
        ))
        conn.commit()
    return get_clip(cid)


def update_clip(clip_id: str, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_clip(clip_id)
    cols = []
    vals = []
    for k, v in kwargs.items():
        cols.append(f"{k} = ?")
        if isinstance(v, (dict, list)):
            vals.append(json.dumps(v))
        else:
            vals.append(v)
    vals.append(clip_id)
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE clips SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_clip(clip_id)


def _hydrate_clip(row) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    for field in ("tags_json", "hashtags_json", "highlight_words_json"):
        clean_key = field.replace("_json", "")
        if d.get(field):
            try:
                d[clean_key] = json.loads(d[field])
            except Exception:
                d[clean_key] = []
        else:
            d[clean_key] = []
    return d


def get_clip(clip_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return _hydrate_clip(row)


def get_clips_by_job(job_id: str) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clips WHERE job_id = ? ORDER BY clip_index ASC", (job_id,)).fetchall()
        return [_hydrate_clip(r) for r in rows]


def list_all_clips(limit: int = 100) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clips ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_hydrate_clip(r) for r in rows]


# --- Account Operations (YouTube / Google OAuth) ---

def save_account(acc: dict):
    now = time.time()
    with _lock, get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO accounts (id, platform, name, access_token, refresh_token, expires_at, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            acc["id"],
            acc.get("platform", "youtube"),
            acc.get("name", "YouTube Channel"),
            acc["access_token"],
            acc.get("refresh_token", ""),
            acc.get("expires_at", 0),
            json.dumps(acc.get("meta", {})),
            now
        ))
        conn.commit()


def get_account(acc_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (acc_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["meta"] = json.loads(d["meta_json"])
        except Exception:
            d["meta"] = {}
        return d


def get_account_by_platform(platform: str = "youtube") -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE platform = ? ORDER BY created_at DESC LIMIT 1", (platform,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["meta"] = json.loads(d["meta_json"])
        except Exception:
            d["meta"] = {}
        return d


def list_accounts() -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY created_at DESC").fetchall()
        accounts = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d["meta_json"])
            except Exception:
                d["meta"] = {}
            accounts.append(d)
        return accounts


def delete_account(acc_id: str):
    with _lock, get_conn() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (acc_id,))
        conn.commit()


# --- Key-Value Settings Operations ---

def get_setting(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not row or row["value"] is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]


def set_setting(key: str, value: Any):
    with _lock, get_conn() as conn:
        val_str = json.dumps(value) if not isinstance(value, str) else value
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val_str))
        conn.commit()


def get_all_settings() -> Dict[str, Any]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        out = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except Exception:
                out[r["key"]] = r["value"]
        return out


# --- Scheduled Posts Operations ---

def create_scheduled_post(post_data: dict = None, **kwargs) -> dict:
    if post_data is None:
        post_data = kwargs
    elif kwargs:
        post_data = {**post_data, **kwargs}
    pid = post_data.get("id") or f"sp_{int(time.time()*1000)}"
    now = time.time()
    with _lock, get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO scheduled_posts (
                id, clip_id, platform, account_id, title, description,
                tags_json, privacy, scheduled_time, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pid,
            post_data["clip_id"],
            post_data.get("platform", "youtube"),
            post_data.get("account_id", ""),
            post_data.get("title", ""),
            post_data.get("description", ""),
            json.dumps(post_data.get("tags", [])),
            post_data.get("privacy", "public"),
            float(post_data["scheduled_time"]),
            post_data.get("status", "pending"),
            now
        ))
        conn.commit()
    return get_scheduled_post(pid)


def get_scheduled_post(post_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["tags"] = json.loads(d.get("tags_json", "[]"))
        except Exception:
            d["tags"] = []
        return d


def list_scheduled_posts(status: Optional[str] = None) -> List[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM scheduled_posts WHERE status = ? ORDER BY scheduled_time ASC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM scheduled_posts ORDER BY scheduled_time ASC").fetchall()
        posts = []
        for r in rows:
            d = dict(r)
            try:
                d["tags"] = json.loads(d.get("tags_json", "[]"))
            except Exception:
                d["tags"] = []
            posts.append(d)
        return posts


def update_scheduled_post(post_id: str, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_scheduled_post(post_id)
    cols = []
    vals = []
    for k, v in kwargs.items():
        cols.append(f"{k} = ?")
        if isinstance(v, (dict, list)):
            vals.append(json.dumps(v))
        else:
            vals.append(v)
    vals.append(post_id)
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE scheduled_posts SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_scheduled_post(post_id)


def delete_scheduled_post(post_id: str):
    with _lock, get_conn() as conn:
        conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        conn.commit()


# --- Video Performance & Analytics Operations ---

def save_clip_analytics(clip_id: str | dict, views: int = 0, likes: int = 0, comments: int = 0, platform: str = "youtube"):
    if isinstance(clip_id, dict):
        d = clip_id
        cid = d.get("clip_id", "")
        platform = d.get("platform", "youtube")
        views = int(d.get("views", 0))
        likes = int(d.get("likes", 0))
        comments = int(d.get("comments", 0))
        clip_id = cid
    now = time.time()
    with _lock, get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO clip_analytics (clip_id, platform, views, likes, comments, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (clip_id, platform, views, likes, comments, now))
        conn.commit()


def get_clip_analytics(clip_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM clip_analytics WHERE clip_id = ?", (clip_id,)).fetchone()
        return dict(row) if row else None


def list_all_analytics() -> Dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clip_analytics").fetchall()
        return {r["clip_id"]: dict(r) for r in rows}


# --- Creator Profiles Operations (Feature 3) ---

def create_creator(
    name: str,
    channels: dict = None,
    style: str = "bounce",
    layout: str = "split",
    min_len: int = 15,
    max_len: int = 60,
    min_score: int = 80,
    autopost: bool = False,
    daily_cap: int = 5,
    post_gap_min: int = 45,
    default_tags: list = None,
    creator_id: Optional[str] = None
) -> dict:
    cid = creator_id or f"creator_{int(time.time()*1000)}"
    channels = channels or {}
    default_tags = default_tags or []
    now = time.time()
    with _lock, get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO creators (
                id, name, channels_json, style, layout, min_len, max_len, min_score,
                autopost, daily_cap, post_gap_min, default_tags_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cid, name.strip(), json.dumps(channels), style, layout,
            int(min_len), int(max_len), int(min_score),
            1 if autopost else 0, int(daily_cap), int(post_gap_min),
            json.dumps(default_tags), now
        ))
        conn.commit()
    return get_creator(cid)


def get_creator(creator_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["channels"] = json.loads(d.get("channels_json") or "{}")
        except Exception:
            d["channels"] = {}
        try:
            d["default_tags"] = json.loads(d.get("default_tags_json") or "[]")
        except Exception:
            d["default_tags"] = []
        d["autopost"] = bool(d.get("autopost", 0))
        return d


def list_creators() -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM creators ORDER BY created_at DESC").fetchall()
        res = []
        for r in rows:
            d = dict(r)
            try:
                d["channels"] = json.loads(d.get("channels_json") or "{}")
            except Exception:
                d["channels"] = {}
            try:
                d["default_tags"] = json.loads(d.get("default_tags_json") or "[]")
            except Exception:
                d["default_tags"] = []
            d["autopost"] = bool(d.get("autopost", 0))
            res.append(d)
        return res


def update_creator(creator_id: str, **kwargs) -> Optional[dict]:
    if not kwargs:
        return get_creator(creator_id)
    cols = []
    vals = []
    for k, v in kwargs.items():
        if k == "channels":
            cols.append("channels_json = ?")
            vals.append(json.dumps(v))
        elif k == "default_tags":
            cols.append("default_tags_json = ?")
            vals.append(json.dumps(v))
        elif k == "autopost":
            cols.append("autopost = ?")
            vals.append(1 if v else 0)
        else:
            cols.append(f"{k} = ?")
            vals.append(v)
    vals.append(creator_id)
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE creators SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_creator(creator_id)


def delete_creator(creator_id: str):
    with _lock, get_conn() as conn:
        conn.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
        conn.commit()


# --- AI Token & Cost Usage Tracking (Feature 5) ---

def record_ai_usage(
    job_id: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost: float = 0.0
) -> dict:
    total_tokens = int(prompt_tokens) + int(completion_tokens)
    now = time.time()
    with _lock, get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO ai_usage (
                job_id, provider, model, prompt_tokens, completion_tokens,
                total_tokens, estimated_cost, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id, provider, model, int(prompt_tokens), int(completion_tokens),
            total_tokens, float(estimated_cost), now
        ))
        conn.commit()
        usage_id = cursor.lastrowid
    return {
        "id": usage_id,
        "job_id": job_id,
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "created_at": now
    }


def get_ai_usage_summary() -> dict:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT provider, model,
                   SUM(prompt_tokens) as p_tokens,
                   SUM(completion_tokens) as c_tokens,
                   SUM(total_tokens) as t_tokens,
                   SUM(estimated_cost) as total_cost,
                   COUNT(*) as call_count
            FROM ai_usage
            GROUP BY provider, model
        """).fetchall()

        by_provider = {}
        total_p = 0
        total_c = 0
        total_t = 0
        total_cost = 0.0
        total_calls = 0

        for r in rows:
            p = r["provider"]
            m = r["model"]
            pt = int(r["p_tokens"] or 0)
            ct = int(r["c_tokens"] or 0)
            tt = int(r["t_tokens"] or 0)
            cost = float(r["total_cost"] or 0.0)
            calls = int(r["call_count"] or 0)

            total_p += pt
            total_c += ct
            total_t += tt
            total_cost += cost
            total_calls += calls

            if p not in by_provider:
                by_provider[p] = {"models": {}, "total_tokens": 0, "total_cost": 0.0, "calls": 0}
            by_provider[p]["total_tokens"] += tt
            by_provider[p]["total_cost"] += cost
            by_provider[p]["calls"] += calls
            by_provider[p]["models"][m] = {
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": tt,
                "estimated_cost": round(cost, 6),
                "calls": calls
            }

        return {
            "total_tokens": total_t,
            "prompt_tokens": total_p,
            "completion_tokens": total_c,
            "total_cost": round(total_cost, 6),
            "total_calls": total_calls,
            "by_provider": by_provider
        }


