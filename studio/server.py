"""ClipForge Studio FastAPI Server and Background Orchestrator.

Provides REST APIs, SSE real-time job tracking, video ingestion, AI moment analysis,
FFmpeg 9:16 rendering, dynamic Big Text hook updates, and YouTube Creator Uploads.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import accounts, asr_worker, brain, config, creators, db, facecam, games, live, posting, render, storage, transcribe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("clipforge.server")

app = FastAPI(title="ClipForge Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---

class CreateJobRequest(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = "Untitled Video"
    creator_id: Optional[str] = None
    game: Optional[str] = None
    layout: Optional[str] = "split"
    style: Optional[str] = "bounce"


class UpdateHookRequest(BaseModel):
    hook: str
    style: Optional[str] = "bounce"
    layout: Optional[str] = None


class RegenerateSeoRequest(BaseModel):
    pass


class YouTubeUploadRequest(BaseModel):
    account_id: str
    title: str
    description: str
    tags: List[str]
    privacy: str = "private"


class MultiPlatformUploadRequest(BaseModel):
    account_id: str
    platform: str = "youtube"  # "youtube", "instagram", "tiktok"
    title: str
    description: Optional[str] = ""
    tags: Optional[List[str]] = []
    privacy: Optional[str] = "public"


class SchedulePostRequest(BaseModel):
    platform: Optional[str] = "youtube"
    platforms: Optional[List[str]] = None
    account_id: Optional[str] = None
    title: Optional[str] = ""
    description: Optional[str] = ""
    tags: Optional[List[str]] = []
    privacy: Optional[str] = "public"
    scheduled_time: Optional[float] = None  # Unix timestamp in seconds
    creator_id: Optional[str] = None


class LiveStartRequest(BaseModel):
    stream_url: str
    creator_id: Optional[str] = None


class LiveChatSimRequest(BaseModel):
    message: str
    username: Optional[str] = "chat_user"


class CreatorRequest(BaseModel):
    name: str
    channels: Optional[dict] = None
    style: Optional[str] = "bounce"
    layout: Optional[str] = "split"
    min_len: Optional[int] = 15
    max_len: Optional[int] = 60
    min_score: Optional[int] = 80
    autopost: Optional[bool] = False
    daily_cap: Optional[int] = 5
    post_gap_min: Optional[int] = 45
    default_tags: Optional[List[str]] = None


class MoveDataRequest(BaseModel):
    target_path: str


class KeywordResearchRequest(BaseModel):
    topic: str
    niche: Optional[str] = "General"


class SettingsRequest(BaseModel):
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_key: Optional[str] = None
    ai_models_chain: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    require_approval: Optional[bool] = None


# --- Pipeline Orchestrator ---

def process_video_pipeline(
    job_id: str,
    video_path: str,
    source_title: str = "",
    source_uploader: str = "",
    creator_id: Optional[str] = None,
    game: Optional[str] = None,
    preferred_layout: Optional[str] = None,
    preferred_style: Optional[str] = None
):
    """End-to-end processing pipeline running in background thread with storage safety,
    isolated ASR worker, and creator branding integration.
    """
    try:
        video_p = Path(video_path)
        job_dir = config.DATA_DIR / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # Storage safety check (Feature 6)
        safe, disk_warn = storage.check_disk_space(min_gb=3.0)
        if not safe:
            logger.warning(f"Disk space warning on job {job_id}: {disk_warn}")

        # Fetch creator defaults if assigned
        creator = creators.get_creator(creator_id) if creator_id else None
        target_style = preferred_style or (creator.get("style") if creator else "bounce")
        target_layout = preferred_layout or (creator.get("layout") if creator else None)

        # Stage 1: Extraction & Audio Analysis
        db.update_job(job_id, status="processing", stage="audio_analysis", progress=25,
                      stage_message="Extracting audio & computing loudness z-scores...")
        wav_path = job_dir / "audio.wav"
        transcribe.extract_audio(video_p, wav_path)
        db_arr, loud_z = transcribe.compute_loudness(wav_path)

        # Stage 2: Subprocess ASR Worker (Feature 6)
        db.update_job(job_id, stage="transcribing", progress=45,
                      stage_message="Transcribing dialogue with word timestamps in isolated worker...")
        words = asr_worker.transcribe_in_worker(wav_path)

        # Probe video duration and dimensions
        orig_w, orig_h = facecam._video_dimensions(video_p)
        dur = facecam._duration(video_p)
        if dur <= 0:
            dur = words[-1]["e"] if words else 30.0

        # Stage 3: Facecam Detection & AI Moment Scouting with Gaming Recognition (Feature 4 & 5)
        db.update_job(job_id, stage="ai_scouting", progress=65,
                      stage_message="AI scouting high-engagement peaks and detecting facecam...")
        detected_cam = facecam.detect_facecam(video_p)

        clip_candidates = brain.extract_clips(
            words=words,
            loud_z=loud_z,
            duration=dur,
            title=source_title or video_p.stem,
            uploader=source_uploader,
            game=game or (creator.get("game") if creator else ""),
            job_id=job_id
        )

        db.update_job(
            job_id,
            duration=dur,
            video_path=str(video_p.resolve()),
            audio_path=str(wav_path.resolve()),
            transcript_json=words,
            loudness_json=loud_z.tolist() if len(loud_z) else [],
            facecam_json=list(detected_cam) if detected_cam else None
        )

        # Stage 4: 9:16 Vertical Video & Subtitle Rendering
        n_clips = len(clip_candidates)
        db.update_job(job_id, stage="rendering", progress=75,
                      stage_message=f"Rendering {n_clips} vertical 9:16 Shorts with dynamic captions...")

        for idx, cand in enumerate(clip_candidates):
            clip_id = f"clip_{job_id}_{idx+1}"
            progress_val = 75 + int(22 * (idx / max(1, n_clips)))
            db.update_job(job_id, progress=progress_val,
                          stage_message=f"Rendering clip {idx+1}/{n_clips}: '{cand['hook']}'...")

            layout_choice = target_layout or ("gameplay" if detected_cam else "blur")
            cand_render_info = {
                "start": cand["start"],
                "end": cand["end"],
                "hook": cand["hook"],
                "style": target_style,
                "layout": layout_choice,
                "facecam": detected_cam,
                "highlight_words": cand.get("highlight_words", []),
            }

            rendered = render.render_single_clip(
                src_video=video_p,
                out_dir=config.CLIPS_DIR,
                clip_id=clip_id,
                clip_info=cand_render_info,
                words=words,
                src_w=orig_w,
                src_h=orig_h
            )

            # Persist to database
            db.create_clip({
                "id": clip_id,
                "job_id": job_id,
                "clip_index": idx + 1,
                "start_time": cand["start"],
                "end_time": cand["end"],
                "duration": round(cand["end"] - cand["start"], 2),
                "score": cand["score"],
                "category": cand["category"],
                "hook": cand["hook"],
                "title": cand["title"],
                "description": cand["description"],
                "tags": cand.get("tags", []),
                "hashtags": cand.get("hashtags", []),
                "highlight_words": cand.get("highlight_words", []),
                "reason": cand.get("reason", ""),
                "layout": layout_choice,
                "video_file": rendered["video_file"],
                "cover_file": rendered["cover_file"],
                "ass_file": rendered["ass_file"],
            })

        db.update_job(job_id, status="completed", stage="done", progress=100,
                      stage_message=f"Successfully generated {n_clips} viral shorts!")
        logger.info(f"Job {job_id} successfully completed with {n_clips} clips.")

        # Stage 5: Creator Auto-Posting Hook (Feature 2 & 3)
        if creator_id:
            try:
                creators.on_job_completed(job_id, creator_id)
            except Exception as pe:
                logger.warning(f"Creator post-job hook notice: {pe}")

    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}: {e}")
        db.update_job(job_id, status="failed", stage="error", error=str(e),
                      stage_message=f"Processing error: {str(e)[:150]}")


# --- API Routes ---

@app.get("/api/status")
def get_system_status():
    """Returns engine health, offline model readiness, connected accounts, and storage stats."""
    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    model_ready = transcribe.is_sherpa_model_available()
    yt_acc = db.get_account_by_platform("youtube")
    ai_provider = db.get_setting("ai_provider", config.AI_PROVIDER)
    has_ai_key = bool(db.get_setting("ai_key", config.AI_KEY))
    storage_info = storage.get_storage_info()
    creators_list = creators.list_creators()
    active_posts = db.list_scheduled_posts()

    return {
        "status": "ready",
        "ffmpeg": ffmpeg_ok,
        "sherpa_model_ready": model_ready,
        "ai_provider": ai_provider,
        "ai_key_configured": has_ai_key,
        "youtube_connected": bool(yt_acc),
        "youtube_channel": yt_acc.get("name") if yt_acc else None,
        "storage": storage_info,
        "creators_count": len(creators_list),
        "queue_count": len(active_posts),
        "ai_fallback_chain": [f"{p}/{m}" for p, m in brain.get_ai_fallback_chain()],
    }


@app.post("/api/jobs/create")
def create_job(req: CreateJobRequest, bg_tasks: BackgroundTasks):
    """Initiates a video processing job via YouTube/Twitch URL."""
    if not req.url:
        raise HTTPException(status_code=400, detail="URL is required.")

    job_id = f"job_{int(time.time()*1000)}"
    db.create_job(job_id=job_id, source_type="url", source_url=req.url, title=req.title or "Ingesting Media...")
    if req.creator_id:
        db.update_job(job_id, creator_id=req.creator_id)

    def _run_url_job():
        try:
            db.update_job(job_id, status="processing", stage="downloading", progress=10,
                          stage_message="Downloading full-res video via yt-dlp...")
            info = transcribe.download_media(req.url, config.UPLOADS_DIR)
            db.update_job(job_id, title=info["title"], uploader=info["uploader"])
            process_video_pipeline(
                job_id,
                info["path"],
                source_title=info["title"],
                source_uploader=info["uploader"],
                creator_id=req.creator_id,
                game=req.game,
                preferred_layout=req.layout,
                preferred_style=req.style
            )
        except Exception as e:
            logger.exception(f"Download/Pipeline failure for {req.url}: {e}")
            db.update_job(job_id, status="failed", stage="error", error=str(e),
                          stage_message=f"Failed to ingest URL: {str(e)[:150]}")

    bg_tasks.add_task(_run_url_job)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/upload")
async def upload_file(
    bg_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    creator_id: Optional[str] = Form(None),
    game: Optional[str] = Form(None),
    layout: Optional[str] = Form("split"),
    style: Optional[str] = Form("bounce")
):
    """Handles direct file upload from web drag & drop zone."""
    job_id = f"job_{int(time.time()*1000)}"
    file_ext = Path(file.filename).suffix or ".mp4"
    dest_path = config.UPLOADS_DIR / f"{job_id}{file_ext}"

    with open(dest_path, "wb") as buffer:
        while content := await file.read(1024 * 1024):  # 1MB chunks
            buffer.write(content)

    title = Path(file.filename).stem
    db.create_job(job_id=job_id, source_type="upload", source_url="", title=title, uploader="Creator Upload")
    if creator_id:
        db.update_job(job_id, creator_id=creator_id)

    bg_tasks.add_task(
        process_video_pipeline,
        job_id,
        str(dest_path.resolve()),
        title,
        "Creator Upload",
        creator_id,
        game,
        layout,
        style
    )
    return {"job_id": job_id, "title": title, "status": "queued"}


@app.get("/api/jobs")
def list_jobs():
    return db.list_jobs(limit=30)


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clips = db.get_clips_by_job(job_id)
    return {"job": job, "clips": clips}


@app.get("/api/jobs/{job_id}/events")
async def stream_job_events(job_id: str, request: Request):
    """Server-Sent Events (SSE) stream for real-time progress updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            job = db.get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break

            data = {
                "id": job["id"],
                "status": job["status"],
                "stage": job["stage"],
                "progress": job["progress"],
                "message": job.get("stage_message", ""),
                "title": job.get("title", ""),
                "error": job.get("error", ""),
            }
            yield f"data: {json.dumps(data)}\n\n"

            if job["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- Clip Management & Instant Customization ---

@app.get("/api/clips")
def list_clips(job_id: Optional[str] = None):
    if job_id:
        return db.get_clips_by_job(job_id)
    return db.list_all_clips(limit=50)


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str):
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


@app.post("/api/jobs/{job_id}/clips/{clip_id}/generate_seo")
@app.post("/api/clips/{clip_id}/regenerate-seo")
def generate_clip_seo(clip_id: str, job_id: Optional[str] = None):
    """FEATURE 1: Context-Aware AI SEO with Conversation Understanding (Jokes, climaxes, turning points)."""
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = db.get_job(job_id or clip["job_id"])
    all_words = job.get("transcript") or [] if job else []

    clip_words = [
        w for w in all_words
        if w["s"] >= clip["start_time"] and w["e"] <= clip["end_time"]
    ]

    new_seo = brain.regenerate_seo(clip, clip_words, context_title=job.get("title", "") if job else "")
    updated_clip = db.update_clip(
        clip_id,
        hook=new_seo["hook"],
        title=new_seo["title"],
        description=new_seo["description"],
        tags_json=new_seo["tags"],
        hashtags_json=new_seo.get("hashtags", ["#shorts", "#viral"])
    )
    return {"status": "success", "seo": new_seo, "clip": updated_clip}


@app.post("/api/jobs/{job_id}/clips/{clip_id}/apply_hook")
@app.post("/api/clips/{clip_id}/update-hook")
def apply_clip_hook(clip_id: str, req: UpdateHookRequest, job_id: Optional[str] = None):
    """FEATURE 2: Fast Big Text Hook re-burn in under 5 seconds without re-encoding whole video."""
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = db.get_job(job_id or clip["job_id"])
    if not job or not job.get("video_path"):
        raise HTTPException(status_code=400, detail="Source video not available for re-rendering.")

    src_video = Path(job["video_path"])
    if not src_video.exists():
        raise HTTPException(status_code=400, detail="Source video file missing.")

    words = job.get("transcript") or []
    detected_cam = job.get("facecam")
    orig_w, orig_h = facecam._video_dimensions(src_video)

    new_hook = req.hook.strip()
    new_style = req.style or "bounce"
    new_layout = req.layout or clip.get("layout", "blur")

    render_info = {
        "start": clip["start_time"],
        "end": clip["end_time"],
        "hook": new_hook,
        "style": new_style,
        "layout": new_layout,
        "facecam": detected_cam,
        "highlight_words": clip.get("highlight_words", []),
    }

    try:
        # Fast sub-5s subtitle re-burn
        rendered = render.fast_reapply_hook(
            src_video=src_video,
            out_dir=config.CLIPS_DIR,
            clip_id=clip_id,
            clip_info=render_info,
            words=words,
            src_w=orig_w,
            src_h=orig_h
        )

        updated_clip = db.update_clip(
            clip_id,
            hook=new_hook,
            layout=new_layout,
            video_file=rendered["video_file"],
            cover_file=rendered["cover_file"],
            ass_file=rendered["ass_file"]
        )
        return {"status": "success", "clip": updated_clip}

    except Exception as e:
        logger.exception(f"Fast re-burn failed for clip {clip_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Re-render failed: {str(e)}")


@app.post("/api/clips/{clip_id}/upload-multi")
def upload_clip_multi(clip_id: str, req: MultiPlatformUploadRequest):
    """FEATURE 4: Multi-platform upload (YouTube, Instagram Reels, TikTok) with strict Creator Review."""
    # Check creator approval setting
    require_approval = db.get_setting("require_approval", True)

    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_video_path = config.CLIPS_DIR / clip["video_file"]
    if not clip_video_path.exists():
        raise HTTPException(status_code=404, detail=f"Clip file {clip['video_file']} not found on disk.")

    platform = req.platform.lower()

    try:
        if platform == "youtube":
            res = accounts.youtube_upload(
                account_id=req.account_id,
                video_path=clip_video_path,
                title=req.title,
                description=req.description,
                tags=req.tags,
                privacy=req.privacy
            )
            db.update_clip(
                clip_id,
                uploaded_to_youtube=1,
                youtube_video_id=res["video_id"],
                youtube_url=res["url"]
            )
            return {"status": "success", "platform": "youtube", "result": res}

        elif platform == "instagram":
            res = accounts.instagram_upload(
                account_id=req.account_id,
                video_path=clip_video_path,
                caption=f"{req.title}\n\n{req.description}"
            )
            return {"status": "success", "platform": "instagram", "result": res}

        elif platform == "tiktok":
            res = accounts.tiktok_upload(
                account_id=req.account_id,
                video_path=clip_video_path,
                title=req.title,
                privacy=req.privacy
            )
            return {"status": "success", "platform": "tiktok", "result": res}

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported platform '{platform}'.")

    except Exception as e:
        logger.exception(f"Upload to {platform} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clips/{clip_id}/schedule")
def schedule_clip_post(clip_id: str, req: SchedulePostRequest):
    """FEATURE 2: Schedule an approved clip for automated multi-platform publishing."""
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    platforms = req.platforms or ([req.platform] if req.platform else ["youtube"])
    created_posts = []

    for plat in platforms:
        acc = db.get_account_by_platform(plat)
        acc_id = req.account_id or (acc["id"] if acc else f"default_{plat}")
        post = posting.enqueue_post(
            clip_id=clip_id,
            platform=plat,
            account_id=acc_id,
            title=req.title or clip.get("title", ""),
            description=req.description or clip.get("description", ""),
            tags=req.tags or clip.get("tags", []),
            scheduled_time=req.scheduled_time,
            creator_id=req.creator_id,
            privacy=req.privacy or "public"
        )
        created_posts.append(post)

    return {
        "status": "success",
        "scheduled_post": created_posts[0] if created_posts else {},
        "scheduled_posts": created_posts
    }


@app.get("/api/posts/queue")
def get_posts_queue(status: Optional[str] = None):
    """FEATURE 2: List pending, scheduled, publishing, published, and failed clips."""
    now = time.time()
    posts = posting.list_queue(status=status)
    for p in posts:
        diff = p["scheduled_time"] - now
        p["countdown_seconds"] = max(0, int(diff))
        p["is_due"] = diff <= 0
        p["clip"] = db.get_clip(p["clip_id"])
    return posts


@app.delete("/api/posts/{post_id}")
def delete_post_item(post_id: str):
    """FEATURE 2: Cancel and delete a queued post."""
    posting.delete_post(post_id)
    return {"status": "success", "deleted_id": post_id}


@app.post("/api/posts/{post_id}/publish")
def publish_post_now(post_id: str):
    """Instantly publishes a queued or scheduled post."""
    post = db.get_scheduled_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    db.update_scheduled_post(post_id, scheduled_time=time.time() - 1, status="queued")
    dispatched = posting.dispatch_due_posts()
    updated = db.get_scheduled_post(post_id)
    return {"status": "success", "post": updated, "dispatched": dispatched}


@app.get("/api/schedule")
def list_schedule():
    """FEATURE 2: List all queued scheduled posts with countdown remaining (backward-compatible)."""
    now = time.time()
    posts = db.list_scheduled_posts()
    for p in posts:
        diff = p["scheduled_time"] - now
        p["countdown_seconds"] = max(0, int(diff))
        p["is_due"] = diff <= 0
        p["clip"] = db.get_clip(p["clip_id"])
    return posts


@app.delete("/api/schedule/{post_id}")
def cancel_scheduled_post(post_id: str):
    """FEATURE 2: Cancel a scheduled post (backward-compatible)."""
    posting.delete_post(post_id)
    return {"status": "success"}


# --- Feature 1: Live Stream Ingest & Real-Time Clipping ---

@app.post("/api/live/start")
def start_live_stream(req: LiveStartRequest):
    """Starts live stream recording, circular buffer, and real-time moment triggers."""
    if not req.stream_url:
        raise HTTPException(status_code=400, detail="stream_url is required.")
    session = live.start_live_session(req.stream_url, creator_id=req.creator_id)
    return {"status": "success", "session": session.get_status()}


@app.post("/api/live/stop")
def stop_live_stream():
    """Stops the active live stream recording session."""
    res = live.stop_live_session()
    return {"status": "success", "session": res}


@app.get("/api/live/status")
async def get_live_stream_status(request: Request):
    """SSE feed streaming active buffer size, current chat velocity, and clips caught in real time."""
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(live.stream_live_status_events(), media_type="text/event-stream")
    return live.get_live_status()


@app.post("/api/live/chat")
def simulate_chat(req: LiveChatSimRequest):
    """Simulates or delivers an IRC chat message into the live stream session."""
    session = live.get_live_session()
    if not session or not session.is_active:
        raise HTTPException(status_code=400, detail="No active live stream session.")
    session.simulate_chat_message(req.message, req.username)
    return {"status": "success", "chat_velocity": session.chat_velocity}


@app.post("/api/live/clip")
def force_live_clip():
    """Forces moment extraction and clipping from current live buffer window."""
    session = live.get_live_session()
    if not session or not session.is_active:
        raise HTTPException(status_code=400, detail="No active live stream session.")
    clip_res = session.extract_moment_from_buffer(reason="Manual clip button trigger")
    return {"status": "success", "clip": clip_res}


# --- Feature 3: Creator Workspaces & Channel Profiles ---

@app.get("/api/creators")
def get_creators():
    """Lists all configured creator profiles."""
    return creators.list_creators()


@app.post("/api/creators")
def create_creator_profile(req: CreatorRequest):
    """Creates a new creator workspace."""
    if not req.name:
        raise HTTPException(status_code=400, detail="Creator name is required.")
    c = creators.create_creator(
        name=req.name,
        channels=req.channels,
        style=req.style or "bounce",
        layout=req.layout or "split",
        min_len=req.min_len or 15,
        max_len=req.max_len or 60,
        min_score=req.min_score or 80,
        autopost=bool(req.autopost),
        daily_cap=req.daily_cap or 5,
        post_gap_min=req.post_gap_min or 45,
        default_tags=req.default_tags or []
    )
    return {"status": "success", "creator": c}


@app.put("/api/creators/{creator_id}")
def update_creator_profile(creator_id: str, req: CreatorRequest):
    """Updates creator workspace settings."""
    existing = creators.get_creator(creator_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Creator not found")
    c = creators.update_creator(
        creator_id,
        name=req.name,
        channels=req.channels or existing.get("channels", {}),
        style=req.style or existing.get("style", "bounce"),
        layout=req.layout or existing.get("layout", "split"),
        min_len=req.min_len or existing.get("min_len", 15),
        max_len=req.max_len or existing.get("max_len", 60),
        min_score=req.min_score or existing.get("min_score", 80),
        autopost=bool(req.autopost),
        daily_cap=req.daily_cap or existing.get("daily_cap", 5),
        post_gap_min=req.post_gap_min or existing.get("post_gap_min", 45),
        default_tags=req.default_tags or existing.get("default_tags", [])
    )
    return {"status": "success", "creator": c}


@app.delete("/api/creators/{creator_id}")
def delete_creator_profile(creator_id: str):
    """Deletes creator workspace."""
    creators.delete_creator(creator_id)
    return {"status": "success", "deleted_id": creator_id}


# --- Feature 5: Multi-Provider AI Usage & Analytics ---

@app.get("/api/settings/ai-usage")
def get_ai_usage_stats():
    """Displays total prompt/completion tokens and estimated cost breakdown by provider."""
    return db.get_ai_usage_summary()


# --- Feature 6: Disk Space Safety & Storage Migration ---

@app.get("/api/storage/info")
def get_storage_metrics():
    """Returns disk drive metrics, free space, and <5GB warnings."""
    return storage.get_storage_info()


@app.post("/api/storage/move-data")
def move_data_storage(req: MoveDataRequest):
    """Safely migrates data directory to another drive or folder."""
    if not req.target_path:
        raise HTTPException(status_code=400, detail="target_path is required.")
    try:
        res = storage.move_data_dir(req.target_path)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/analytics")
def get_analytics():
    """FEATURE 8: Fetch video performance stats (views, likes, comments)."""
    return db.list_all_analytics()


@app.post("/api/analytics/sync")
def sync_analytics():
    """FEATURE 8: Sync performance stats from YouTube Data API v3."""
    yt_acc = db.get_account_by_platform("youtube")
    if not yt_acc:
        return {"status": "ignored", "reason": "No YouTube account connected."}

    clips = db.list_all_clips(limit=50)
    yt_ids = [c["youtube_video_id"] for c in clips if c.get("youtube_video_id")]
    if yt_ids:
        accounts.fetch_youtube_analytics(yt_acc["id"], yt_ids)
    return {"status": "success", "synced_count": len(yt_ids), "analytics": db.list_all_analytics()}


@app.post("/api/research/keywords")
def research_keywords(req: KeywordResearchRequest):
    """FEATURE 8: Channel Keyword & Niche Research Engine."""
    result = brain.research_channel_keywords(req.topic, req.niche or "General")
    return {"status": "success", "research": result}


@app.post("/api/clips/{clip_id}/upload-youtube")
def upload_clip_to_youtube(clip_id: str, req: YouTubeUploadRequest):
    """Approve & Upload to YouTube Shorts strictly after Creator Review."""
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_video_path = config.CLIPS_DIR / clip["video_file"]
    if not clip_video_path.exists():
        raise HTTPException(status_code=404, detail=f"Clip file {clip['video_file']} not found on disk.")

    try:
        res = accounts.youtube_upload(
            account_id=req.account_id,
            video_path=clip_video_path,
            title=req.title,
            description=req.description,
            tags=req.tags,
            privacy=req.privacy
        )

        db.update_clip(
            clip_id,
            uploaded_to_youtube=1,
            youtube_video_id=res["video_id"],
            youtube_url=res["url"]
        )

        return {"status": "success", "result": res}

    except Exception as e:
        logger.exception(f"YouTube upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- OAuth 2.0 Endpoints ---

@app.get("/oauth/youtube/connect")
def connect_youtube():
    """Generates authorization URL or redirects to Google OAuth."""
    try:
        url, _ = accounts.get_authorization_url()
        return RedirectResponse(url)
    except Exception as e:
        return HTMLResponse(f"<h3>Configuration Required</h3><p>{str(e)}</p><a href='/'>Return to Studio</a>")


@app.get("/oauth/youtube/callback")
def youtube_callback(code: Optional[str] = None, error: Optional[str] = None):
    """Receives authorization code from Google OAuth 2.0 flow."""
    if error:
        return HTMLResponse(f"<h3>OAuth Authorization Denied</h3><p>{error}</p><a href='/'>Return to Studio</a>")
    if not code:
        return HTMLResponse("<h3>Missing authorization code</h3><a href='/'>Return to Studio</a>")

    try:
        acc = accounts.exchange_code(code)
        # Redirect back to homepage with query param
        return RedirectResponse(url="/?youtube_connected=true")
    except Exception as e:
        logger.exception(f"Callback exchange failed: {e}")
        return HTMLResponse(f"<h3>YouTube Connection Failed</h3><p>{str(e)}</p><a href='/'>Return to Studio</a>")


@app.get("/api/accounts")
def list_accounts():
    return accounts.db.list_accounts()


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: str):
    accounts.db.delete_account(account_id)
    return {"status": "success"}


# --- Settings ---

@app.get("/api/settings")
def get_settings():
    cid, _, redirect = accounts.get_oauth_config()
    default_chain = (
        os.environ.get("CLIPFORGE_AI_MODELS")
        or os.environ.get("PEAKCUT_AI_MODELS")
        or "gemini/gemini-2.5-flash,groq/llama-3.3-70b-versatile,ollama/llama3.2"
    )
    return {
        "ai_provider": db.get_setting("ai_provider", config.AI_PROVIDER),
        "ai_model": db.get_setting("ai_model", config.AI_MODEL),
        "ai_key_set": bool(db.get_setting("ai_key", config.AI_KEY)),
        "ai_models_chain": db.get_setting("ai_models_chain", default_chain),
        "google_client_id": cid,
        "youtube_redirect_uri": redirect,
        "asr_provider": config.ASR_PROVIDER,
        "asr_model": config.ASR_MODEL_NAME,
        "require_approval": db.get_setting("require_approval", True),
    }


@app.post("/api/settings")
def save_settings(req: SettingsRequest):
    if req.ai_provider is not None:
        db.set_setting("ai_provider", req.ai_provider.strip().lower())
        config.AI_PROVIDER = req.ai_provider.strip().lower()
    if req.ai_model is not None:
        db.set_setting("ai_model", req.ai_model.strip())
        config.AI_MODEL = req.ai_model.strip()
    if req.ai_key is not None and req.ai_key.strip():
        db.set_setting("ai_key", req.ai_key.strip())
        config.AI_KEY = req.ai_key.strip()
    if req.ai_models_chain is not None:
        db.set_setting("ai_models_chain", req.ai_models_chain.strip())
    if req.google_client_id is not None:
        db.set_setting("google_client_id", req.google_client_id.strip())
    if req.google_client_secret is not None and req.google_client_secret.strip():
        db.set_setting("google_client_secret", req.google_client_secret.strip())
    if req.require_approval is not None:
        db.set_setting("require_approval", bool(req.require_approval))
    return {"status": "success", "settings": get_settings()}


# --- Background Scheduler Loop (Feature 2 & 5) ---

async def _scheduled_post_dispatcher_loop():
    """Checks every 20-30 seconds for due scheduled posts and dispatches them."""
    while True:
        try:
            await asyncio.to_thread(posting.dispatch_due_posts)
        except Exception as e:
            logger.debug(f"Dispatcher check: {e}")
        await asyncio.sleep(25)


@app.on_event("startup")
async def on_server_startup():
    asyncio.create_task(_scheduled_post_dispatcher_loop())


# --- Static Files & Dashboard Mount ---

# Serve rendered video/thumbnail clips
app.mount("/clips", StaticFiles(directory=str(config.CLIPS_DIR)), name="clips")

# Serve frontend web assets
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if not WEB_DIR.exists():
    alt_web = Path(__file__).resolve().parent.parent / "PeakCut-src" / "PeakCut-main" / "web"
    if alt_web.exists():
        WEB_DIR = alt_web

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
@app.get("/index.html")
@app.get("/app")
@app.get("/app/videos")
def serve_index():
    for cand in [
        WEB_DIR / "index.html",
        Path("web/index.html").resolve(),
        Path(__file__).resolve().parent.parent / "PeakCut-src" / "PeakCut-main" / "web" / "index.html"
    ]:
        if cand.exists():
            return FileResponse(str(cand))
    return HTMLResponse("<h2>ClipForge Studio Web UI Initializing...</h2>")


@app.get("/api/sync")
def api_sync():
    return {"status": "ok", "synced": True}


@app.get("/favicon.ico")
def serve_favicon():
    return HTMLResponse("", status_code=204)
