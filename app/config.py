from pathlib import Path

DATA_DIR = Path("/app/data")
CHANNELS_FILE = DATA_DIR / "channels.json"
EPG_CACHE_DIR = DATA_DIR / "epg"
EPG_SOURCES_FILE = DATA_DIR / "epg_sources.json"

DEFAULT_FFMPEG_PATH = "ffmpeg"
MAX_STREAMS = 4
STREAM_TIMEOUT = 15

EPG_FETCH_INTERVAL = 3600

DATA_DIR.mkdir(parents=True, exist_ok=True)
EPG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
