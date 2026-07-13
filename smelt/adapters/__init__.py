from .media import extract_media
from .reddit import extract_reddit
from .textdump import extract_text
from .webpage import extract_webpage

# Backwards-compatible alias — YouTube is just one yt-dlp platform now.
extract_youtube = extract_media

__all__ = ["extract_text", "extract_webpage", "extract_media", "extract_reddit", "extract_youtube"]
