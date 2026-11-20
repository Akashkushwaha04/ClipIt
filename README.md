# ⚡ CLIP IT — AI Short-Form Video Generator & Studio

> Open-source self-hosted clone of Opus Clip, Klap, and PeakCut. Built for high-volume creator workflows, automated viral moment extraction, live stream ingest, dynamic ASS subtitles, and multi-platform publishing.

---

## 🌟 Key Features

- **⚡ Fast Offline Speech-to-Text:** Accurate word-level timestamps powered by `sherpa-onnx` (Nemo Parakeet TDT 0.6B INT8) and `faster-whisper`.
- **🔥 Dynamic "Big Text" Hook Overlay:** Bold 2–5 word viral hook banner styled in ASS subtitles with sub-5-second fast re-burn (`< 5s`) without re-encoding the entire video.
- **🎨 Word-by-Word Animated Captions:** Animated karaoke-style highlighting with custom typography presets (**Neon Bounce**, **Anton Hype**, **Poppins Clean**).
- **📐 Intelligent Framing & Facecam Auto-Split:**
  - Stacked 35/65 vertical split layout (Facecam Top / Gameplay Bottom).
  - Center crop 9:16 vertical formatting.
  - Blur background padding & Gameplay PiP.
- **🎮 32+ Gaming Recognition Signatures:** Automatic signature detection for GTA 6, GTA 5, Fortnite, Valorant, Minecraft, CS2, CoD, Apex Legends, Elden Ring, and more.
- **📡 Live Stream Ingest & Real-Time Clipping:**
  - Continuous rolling circular disk buffer (6s chunks, 15–20 min retention).
  - IRC chat velocity spike tracking (`msg/s`) & viral trigger word scanning (*"clip that"*, *"W"*, *"clip it"*, *"pog"*, *"LMAO"*).
- **📋 Multi-Platform Auto-Posting & Scheduling Queue:**
  - Automated publishing for **YouTube Shorts**, **Instagram Reels**, and **TikTok**.
  - Enforces time spacing rules ($\ge 45\text{ min}$) and daily channel upload caps (max 5/day).
- **🤖 Multi-Provider AI Fallback Chain & Local Ollama:**
  - Zero-cost offline processing with local Ollama (`http://localhost:11434`).
  - Seamless fallback cascade (`gemini/gemini-2.5-flash,ollama/llama3.2,groq/llama-3.3-70b-versatile,claude/claude-3-5-sonnet`).
  - Real-time token usage and cost ledger.
- **🛡️ Strict Creator Review & Workspaces:**
  - Individual creator profiles with custom branding, layout, style, and auto-post rules.
  - Creator approval toggle preventing unauthorized auto-uploads.
- **💾 Storage Safety Telemetry:** Automatic free disk space monitoring ($< 5\text{ GB}$ warning) and zero-downtime data migration.

---

## 🏗️ Architecture

```
CLIP IT
├── studio/             # Backend media engine & FastAPI server
│   ├── asr_worker.py   # Isolated subprocess ASR transcription pool
│   ├── accounts.py     # OAuth 2.0 & YouTube / TikTok / IG integrations
│   ├── brain.py        # AI moment scouting, SEO generation & Hinglish
│   ├── config.py       # Global environment & directory configuration
│   ├── creators.py     # Multi-creator workspace profiles & autopost rules
│   ├── db.py           # Lightweight native SQLite3 schema with WAL mode
│   ├── facecam.py      # Facecam OpenCV detection & 2-box vertical layout
│   ├── games.py        # 32+ game detection signatures & prompt scouting
│   ├── live.py         # Rolling circular buffer & IRC chat velocity tracker
│   ├── posting.py      # Scheduling queue & multi-platform dispatcher
│   ├── render.py       # FFmpeg 9:16 vertical rendering & ASS subtitle engine
│   ├── storage.py      # Drive storage telemetry & data directory migration
│   ├── transcribe.py   # Audio extraction & offline STT inference
│   └── server.py       # REST API & SSE telemetry endpoints
├── web/                # Vanilla HTML5/CSS3/ES6 single-page web dashboard
│   ├── index.html      # Responsive workspace & modal views
│   ├── app.js          # Client controller, live SSE, & creator workflows
│   └── style.css       # Warm-espresso & vibrant-amber design system
├── tests/              # Comprehensive test suites
│   ├── test_clipforge.py          # 12 base engine unit tests
│   └── test_advanced_features.py  # 6 advanced feature integration tests
└── run.py              # Studio launcher
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+ (Python 3.12 recommended)
- `ffmpeg` with `libass` support

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/clip-it.git
cd clip-it

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Running the Studio
```bash
python run.py
```
Open **http://127.0.0.1:8766/** in your web browser.

---

## 🧪 Testing

Run the full automated test suites:
```bash
python -m unittest tests/test_clipforge.py tests/test_advanced_features.py -v
```

---

## 📄 License
MIT License. Free for personal and commercial creator use.
