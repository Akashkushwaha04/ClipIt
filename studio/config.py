"""ClipForge Studio Configuration.

Centralizes paths, environment settings, model parameters, and output specifications.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()
env = os.environ.get

# --- Directory Paths ---
DATA_DIR = Path(env("CLIPFORGE_DATA") or (ROOT / "data")).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
CLIPS_DIR = DATA_DIR / "clips"
MODELS_DIR = DATA_DIR / "models"
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
DB_PATH = DATA_DIR / "clipforge.db"

# Ensure runtime directories exist
for p in (DATA_DIR, UPLOADS_DIR, CLIPS_DIR, MODELS_DIR, FONTS_DIR):
    p.mkdir(parents=True, exist_ok=True)

# --- Video Output Specifications (9:16 vertical shorts) ---
OUT_W = 1080
OUT_H = 1920
OUT_FPS = 30

# --- Speech Recognition ---
ASR_PROVIDER = env("CLIPFORGE_ASR_PROVIDER", "cpu").strip().lower()
ASR_MODEL_NAME = env("CLIPFORGE_ASR_MODEL", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8")
ASR_MODEL_DIR = MODELS_DIR / ASR_MODEL_NAME

# --- Server Networking ---
HOST = env("CLIPFORGE_HOST", "127.0.0.1")
PORT = int(env("CLIPFORGE_PORT", "8766"))
BASE_URL = env("CLIPFORGE_BASE_URL", f"http://{HOST}:{PORT}").rstrip("/")

# --- AI Provider Defaults ---
AI_PROVIDER = env("CLIPFORGE_AI_PROVIDER", "gemini").strip().lower()
AI_MODEL = env("CLIPFORGE_AI_MODEL", "gemini-2.5-flash")
AI_KEY = env("CLIPFORGE_AI_KEY") or env("GEMINI_API_KEY") or env("OPENAI_API_KEY") or env("ANTHROPIC_API_KEY") or ""

# --- YouTube OAuth 2.0 Settings ---
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", "")
YOUTUBE_REDIRECT_URI = env("YOUTUBE_REDIRECT_URI", f"{BASE_URL}/oauth/youtube/callback")
