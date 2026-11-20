"""ClipForge Studio Launcher.

Starts the Uvicorn web server at http://127.0.0.1:8766.
"""
from pathlib import Path
import uvicorn
from studio import config

ROOT = Path(__file__).resolve().parent


def main():
    print("=" * 65)
    print("   🚀 ClipForge Studio - Production-Ready AI Video Studio")
    print("   Open-source self-hosted Opus Clip / Klap / PeakCut clone")
    print("=" * 65)
    print(f"[*] Starting ClipForge Studio server at: http://{config.HOST}:{config.PORT}")
    print(f"[*] Data directory: {config.DATA_DIR}")
    print(f"[*] Output video resolution: {config.OUT_W}x{config.OUT_H} (9:16 vertical shorts)")
    print("=" * 65)

    uvicorn.run(
        "studio.server:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
