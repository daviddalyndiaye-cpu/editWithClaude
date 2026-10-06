import os
import subprocess
import sys
from dotenv import load_dotenv

try:  # use the OS certificate store (fixes SSL errors behind proxies/antivirus)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
EUROPEANA_API_KEY = os.getenv("EUROPEANA_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
VIMEO_ACCESS_TOKEN = os.getenv("VIMEO_ACCESS_TOKEN")

# Validate keys early
if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
    print("Error: GEMINI_API_KEY not set in .env")
    sys.exit(1)
if not PEXELS_API_KEY or PEXELS_API_KEY == "your_pexels_api_key_here":
    print("Warning: PEXELS_API_KEY not set in .env — Pexels source will be skipped")
    PEXELS_API_KEY = None
if not EUROPEANA_API_KEY:
    print("Warning: EUROPEANA_API_KEY not set in .env — Europeana source will be skipped")
if not SERPER_API_KEY and not SERPAPI_KEY:
    print("Warning: No Google Images API key set — Google search will be skipped")

# Gemini model names
GEMINI_TRANSCRIPTION_MODEL = "gemini-2.5-pro"
GEMINI_QUERY_MODEL = "gemini-3.5-flash"

# Video output settings
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
OUTPUT_FPS = 30

# Segment settings
MIN_SEGMENT_DURATION = 4   # seconds — merge shorter segments
MAX_SEGMENT_DURATION = 9   # seconds — split longer segments

# Query generation settings
QUERY_WORD_RANGE = (3, 6)  # min-max words for Pexels search queries

# Crossfade duration between clips (seconds)
CROSSFADE_DURATION = 0.5

# Transition pools for intelligent selection (VidRush 70/30 strategy)
HOOK_TRANSITIONS = ["zoomin", "fadeblack", "pixelize", "radial", "circlecrop", "dissolve"]
CORE_TRANSITIONS = ["fade", "slideleft", "slideright", "wipeleft", "wiperight", "smoothleft", "smoothright"]
OUTRO_TRANSITIONS = ["fadeblack", "fadewhite", "dissolve"]

# Mood-to-transition bias: maps visual_mood to preferred transition style
MOOD_TRANSITIONS = {
    "energetic": ["pixelize", "zoomin", "slideleft", "radial"],
    "calm": ["fade", "dissolve", "fadewhite"],
    "dramatic": ["fadeblack", "radial", "zoomin", "circlecrop"],
    "professional": ["fade", "wipeleft", "slideright", "dissolve"],
    "playful": ["pixelize", "circlecrop", "smoothleft", "smoothright"],
    "dark": ["fadeblack", "dissolve", "radial"],
    "warm": ["fade", "dissolve", "fadewhite", "smoothright"],
    "cold": ["fadeblack", "wipeleft", "slideleft"],
}

# Video encoder — None = auto-detect (NVENC if available, else libx264)
VIDEO_ENCODER_OVERRIDE = None


def _detect_encoder() -> str:
    """Try NVENC first, fall back to libx264."""
    if VIDEO_ENCODER_OVERRIDE:
        return VIDEO_ENCODER_OVERRIDE
    try:
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, check=True, timeout=10,
        )
        return "h264_nvenc"
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "libx264"


VIDEO_ENCODER = _detect_encoder()

# Extra flags needed per encoder (appended to ffmpeg command)
ENCODER_FLAGS = {
    "h264_nvenc": ["-pix_fmt", "yuv420p"],
    "libx264": ["-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"],
}

# Footage sources — ordered by priority (first = highest priority)
# Available: "google", "wikimedia", "europeana", "ytcc", "archive", "vimeo", "pexels"
# ytcc = YouTube, Creative Commons licensed videos only (via yt-dlp, no key needed)
# vimeo = Vimeo Creative Commons (modern/industrial content, skipped for archival styles)
FOOTAGE_SOURCES = ["google", "wikimedia", "europeana", "ytcc", "archive", "vimeo", "pexels"]

# Parallel download settings
MAX_DOWNLOAD_WORKERS = 3

# Paths
TEMP_DIR = "temp"
OUTPUT_DIR = "output"
OUTPUT_FILENAME = "final_edited.mp4"
