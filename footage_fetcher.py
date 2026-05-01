import base64
import json
import os
import requests
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types
from config import (
    PEXELS_API_KEY, EUROPEANA_API_KEY, SERPAPI_KEY, SERPER_API_KEY, GEMINI_API_KEY,
    VIMEO_ACCESS_TOKEN, TEMP_DIR,
    OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS,
    VIDEO_ENCODER, ENCODER_FLAGS, FOOTAGE_SOURCES
)

_gemini_client = genai.Client(api_key=GEMINI_API_KEY)

SERPAPI_ENDPOINT = "https://serpapi.com/search"
SERPER_ENDPOINT = "https://google.serper.dev/images"
PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_SEARCH = "https://api.pexels.com/v1/search"
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
EUROPEANA_API = "https://api.europeana.eu/record/v2/search.json"
ARCHIVE_API = "https://archive.org/advancedsearch.php"
VIMEO_API = "https://api.vimeo.com/videos"

MAX_RETRIES = 3
RETRY_DELAY = 2

WIKIMEDIA_HEADERS = {
    "User-Agent": "AutoBRollEditor/1.0 (https://github.com/user/auto-broll; contact@example.com)",
    "Referer": "https://commons.wikimedia.org/",
}
WIKIMEDIA_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://commons.wikimedia.org/",
}



def _parse_style(style: str | None) -> dict:
    if not style:
        return {"media": "video", "grayscale": False, "force_photo": False, "archival": False}
    s = style.lower()

    archival = any(w in s for w in ["archive", "archiv", "historical", "historique", "1900", "1910",
                                     "1920", "1930", "1940", "1950", "vintage", "old photograph"])

    # Images if style explicitly mentions photos/images, OR if archival (archive sources = images)
    explicit_video = any(w in s for w in ["video", "clip", "footage", "film"])
    explicit_image = any(w in s for w in ["photo", "image", "picture", "photograph"])
    if explicit_video:
        media = "video"
    elif explicit_image or archival:
        media = "image"
    else:
        media = "video"

    grayscale = any(w in s for w in ["black and white", "black & white", "noir et blanc",
                                      "grayscale", "b&w", "bw", "noir et blanc"])
    force_photo = archival  # prepend "real historical photograph" to CLIP text

    return {"media": media, "grayscale": grayscale, "force_photo": force_photo, "archival": archival}


def fetch_clip(query: str, duration_needed: float, index: int,
               fallback_queries: list[str] | None = None,
               style: str | None = None,
               segment_text: str | None = None) -> str:
    os.makedirs(TEMP_DIR, exist_ok=True)

    style_opts = _parse_style(style)
    media = style_opts["media"]
    grayscale = style_opts["grayscale"]
    force_photo = style_opts["force_photo"]
    archival = style_opts["archival"]

    if query.strip().startswith("{"):
        try:
            parsed = json.loads(query)
            query = parsed.get("primary_query", query)
            print(f"[footage_fetcher] Fixed JSON query: '{query}'")
        except json.JSONDecodeError:
            query = " ".join(query.split()[:4])

    queries_to_try = [query]
    if fallback_queries:
        queries_to_try.extend(fallback_queries)
    simple_query = " ".join(query.split()[:2])
    if simple_query != query:
        queries_to_try.append(simple_query)

    trimmed_path = os.path.join(TEMP_DIR, f"clip_{index}.mp4")

    # Try each query variant, and for images validate with Gemini Vision
    for attempt, q in enumerate(queries_to_try):
        result = _search_all_sources(q, duration_needed, media, archival=archival)
        if not result:
            print(f"[footage_fetcher] No results for '{q}', trying next query...")
            continue

        media_url, source_used = result
        print(f"[footage_fetcher] Source: {source_used} | query: '{q}' | media: {media}")

        # Vimeo URLs are either direct MP4 or tagged HLS — always produce .mp4
        if source_used == "vimeo" or media_url.startswith("vimeo_hls:"):
            raw_path = os.path.join(TEMP_DIR, f"raw_{index}_a{attempt}.mp4")
        else:
            ext = os.path.splitext(media_url.split("?")[0].split("#")[0])[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".mp4", ".webm", ".ogv"):
                ext = ".jpg"
            raw_path = os.path.join(TEMP_DIR, f"raw_{index}_a{attempt}{ext}")

        downloaded_path = None
        try:
            try:
                if source_used == "vimeo" or media_url.startswith("vimeo_hls:"):
                    _download_vimeo(media_url, raw_path)
                    downloaded_path = raw_path
                else:
                    downloaded_path = _download_with_fallback(
                        media_url, raw_path, source_used, q, duration_needed, media, index
                    )
            except Exception as dl_err:
                print(f"[footage_fetcher] Download failed from {source_used} ({dl_err})")
                continue

            # FFmpeg structural validation for images
            if media == "image" and not _is_valid_image(downloaded_path):
                print(f"[footage_fetcher] Invalid image file from {source_used}")
                continue

            # CLIP relevance scoring — images only
            if media == "image" and segment_text and source_used != "pexels":
                clip_text = segment_text[:200]
                if force_photo:
                    clip_text = "real historical photograph " + clip_text
                score = _clip_score(downloaded_path, clip_text)
                if score >= 0:
                    print(f"[clip] Score {score:.3f} for '{q[:50]}'")
                    if score < CLIP_MIN_SCORE:
                        print(f"[clip] Rejected (score {score:.3f} < {CLIP_MIN_SCORE})")
                        continue
                    if score < CLIP_MIN_SCORE + 0.06:
                        if not _gemini_validates_image(downloaded_path, segment_text):
                            print(f"[clip+gemini] Rejected borderline image from {source_used}")
                            continue
                elif not _gemini_validates_image(downloaded_path, segment_text):
                    print(f"[gemini_vision] Rejected image from {source_used} for '{q[:50]}'")
                    continue

            # Passed all checks — render the clip
            if media == "image":
                _image_to_clip(downloaded_path, trimmed_path, duration_needed, grayscale)
            else:
                _trim(downloaded_path, trimmed_path, duration_needed, grayscale)
            print(f"[footage_fetcher] ✓ Clip {index + 1} accepted (source: {source_used})")
            return trimmed_path

        finally:
            if downloaded_path and os.path.exists(downloaded_path):
                os.remove(downloaded_path)

    # All queries and sources exhausted — last resort: Pexels without Gemini validation
    print(f"[footage_fetcher] All sources rejected — using Pexels last resort for '{query}'")
    if media == "image":
        fallback_url = _search_pexels_photo(query)
    else:
        fallback_url = _search_pexels_video(query, duration_needed)
    if not fallback_url:
        raise RuntimeError(f"No footage found for any query variant of: '{query}'")
    ext = os.path.splitext(fallback_url.split("?")[0])[1].lower() or (".jpg" if media == "image" else ".mp4")
    last_path = os.path.join(TEMP_DIR, f"raw_{index}_last{ext}")
    downloaded_path = None
    try:
        _download(fallback_url, last_path)
        downloaded_path = last_path
        if media == "image":
            _image_to_clip(downloaded_path, trimmed_path, duration_needed, grayscale)
        else:
            _trim(downloaded_path, trimmed_path, duration_needed, grayscale)
    finally:
        if downloaded_path and os.path.exists(downloaded_path):
            os.remove(downloaded_path)
    return trimmed_path


def _is_valid_image(path: str) -> bool:
    """Validate image using FFmpeg probe — the same tool that will process it."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and "video" in result.stdout
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLIP relevance scorer — lazy-loaded on first use
# ---------------------------------------------------------------------------

_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None

def _get_clip():
    """Lazy-load CLIP model on first use."""
    global _clip_model, _clip_preprocess, _clip_tokenizer
    if _clip_model is not None:
        return _clip_model, _clip_preprocess, _clip_tokenizer
    try:
        import open_clip
        import torch
        print("[clip] Loading CLIP model (first use)...")
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai"
        )
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model.eval()
        _clip_model = model
        _clip_preprocess = preprocess
        _clip_tokenizer = tokenizer
        print("[clip] CLIP model loaded.")
        return model, preprocess, tokenizer
    except Exception as e:
        print(f"[clip] Could not load CLIP: {e}")
        return None, None, None


def _clip_score(image_path: str, text: str) -> float:
    """Return CLIP cosine similarity between image and text (0-1). -1 on error."""
    try:
        import torch
        from PIL import Image

        model, preprocess, tokenizer = _get_clip()
        if model is None:
            return -1.0

        image = preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
        tokens = tokenizer([text])

        with torch.no_grad():
            image_features = model.encode_image(image)
            text_features = model.encode_text(tokens)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            score = (image_features @ text_features.T).item()

        return score
    except Exception as e:
        print(f"[clip] Scoring error: {e}")
        return -1.0


# CLIP threshold — images below this score are rejected (0.18 = loose, 0.25 = strict)
CLIP_MIN_SCORE = 0.22


def _gemini_validates_image(path: str, segment_text: str) -> bool:
    """Ask Gemini Vision whether this image matches the segment description.
    Returns True if relevant, False if not. On any error, returns True (fail open)."""
    try:
        with open(path, "rb") as f:
            image_bytes = f.read()
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

        prompt = (
            f'Does this image visually match the following description?\n'
            f'Description: "{segment_text}"\n\n'
            f'Answer with only "yes" or "no". '
            f'Answer "yes" if the image is thematically relevant (same era, subject, or scene). '
            f'Answer "no" only if the image is clearly unrelated.'
        )
        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                prompt,
            ],
        )
        answer = response.text.strip().lower()
        is_valid = answer.startswith("y")
        if not is_valid:
            print(f"[gemini_vision] Rejected image for: '{segment_text[:60]}' (answer: {answer[:20]})")
        return is_valid
    except Exception as e:
        print(f"[gemini_vision] Validation error ({e}) — accepting image by default")
        return True


def _download_with_fallback(url: str, dest: str, source: str, query: str,
                             duration: float, media: str, index: int) -> str:
    """Download url to dest. On 429 from archive sources, fall back to Pexels."""
    try:
        _download(url, dest)
        return dest
    except requests.HTTPError as e:
        if "429" in str(e) and source in ("wikimedia", "europeana", "archive"):
            print(f"[footage_fetcher] {source} rate-limited — falling back to Pexels")
            fallback_url = (_search_pexels_photo(query) if media == "image"
                            else _search_pexels_video(query, duration))
            if not fallback_url:
                raise RuntimeError(f"Pexels fallback also failed for: '{query}'") from e
            ext = os.path.splitext(fallback_url.split("?")[0])[1].lower() or ".jpg"
            fallback_dest = os.path.join(TEMP_DIR, f"raw_{index}_fb{ext}")
            _download(fallback_url, fallback_dest)
            return fallback_dest
        raise


# ---------------------------------------------------------------------------
# Multi-source parallel search
# ---------------------------------------------------------------------------

def _search_all_sources(query: str, duration_needed: float, media: str,
                         archival: bool = False) -> tuple[str, str] | None:
    """
    Run parallel + sequential source search. Returns (url, source_name) or None.
    archival=True skips modern video sources (Vimeo, Pexels video) and prioritizes
    Wikimedia/Europeana/Archive.org which carry historical content.
    """
    tasks = []
    for source in FOOTAGE_SOURCES:
        if source == "google" and media == "image" and (SERPER_API_KEY or SERPAPI_KEY):
            tasks.append(("google", lambda q=query: _search_google(q)))
        elif source == "europeana" and media == "image" and EUROPEANA_API_KEY:
            tasks.append(("europeana", lambda q=query: _search_europeana(q)))
        elif source == "wikimedia":
            tasks.append(("wikimedia", lambda q=query, d=duration_needed, m=media: _search_wikimedia(q, d, m)))
        elif source == "archive":
            tasks.append(("archive", lambda q=query, d=duration_needed, m=media: _search_archive(q, d, m)))
        elif source == "vimeo" and not archival:
            # Vimeo CC — skip for archival/historical styles (no vintage content there)
            tasks.append(("vimeo", lambda q=query, d=duration_needed: _search_vimeo(q, d)))
        elif source == "pexels":
            if media == "image":
                tasks.append(("pexels", lambda q=query: _search_pexels_photo(q)))
            elif not archival:
                # Skip Pexels video for archival styles — it only has modern stock footage
                tasks.append(("pexels", lambda q=query, d=duration_needed: _search_pexels_video(q, d)))

    parallel_sources = {"google", "europeana", "wikimedia"}
    parallel_tasks = [(name, fn) for name, fn in tasks if name in parallel_sources]
    sequential_tasks = [(name, fn) for name, fn in tasks if name not in parallel_sources]

    if parallel_tasks:
        priority_order = [name for name, _ in tasks if name in parallel_sources]
        results: dict[str, str | None] = {}
        with ThreadPoolExecutor(max_workers=len(parallel_tasks)) as pool:
            futures = {pool.submit(fn): name for name, fn in parallel_tasks}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception:
                    results[name] = None
        for name in priority_order:
            if results.get(name):
                return results[name], name

    for name, fn in sequential_tasks:
        url = fn()
        if url:
            return url, name

    return None


# ---------------------------------------------------------------------------
# Europeana
# ---------------------------------------------------------------------------

def _search_google(query: str) -> str | None:
    """Search Google Images via Serper.dev (primary) or SerpAPI (fallback)."""
    url = _search_google_serper(query) if SERPER_API_KEY else None
    if not url and SERPAPI_KEY:
        url = _search_google_serpapi(query)
    return url


def _validate_image_url(url: str) -> bool:
    """HEAD-check a URL — returns True if downloadable image."""
    blocked_domains = {"tiktok.com", "instagram.com", "facebook.com", "twitter.com", "x.com"}
    low = url.lower().split("?")[0]
    if any(low.endswith(ext) for ext in (".pdf", ".gif", ".svg", ".mp4", ".webm")):
        return False
    domain = url.split("/")[2] if "//" in url else ""
    if any(b in domain for b in blocked_domains):
        return False
    try:
        head = requests.head(url, timeout=6, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if head.status_code != 200:
            return False
        content_length = int(head.headers.get("content-length", 0))
        if content_length and content_length < 5000:
            return False
        return True
    except Exception:
        return False


def _search_google_serper(query: str) -> str | None:
    """Search Google Images via Serper.dev API."""
    try:
        resp = requests.post(
            SERPER_ENDPOINT,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[serper] Search failed: {e}")
        return None

    results = data.get("images", [])
    for item in results[:8]:
        url = item.get("imageUrl")
        if not url:
            continue
        if _validate_image_url(url):
            print(f"[serper] Found image for '{query}': {url[:80]}")
            return url
    return None


def _search_google_serpapi(query: str) -> str | None:
    """Search Google Images via SerpAPI (fallback)."""
    params = {
        "engine": "google_images",
        "q": query,
        "api_key": SERPAPI_KEY,
        "safe": "active",
        "tbs": "isz:l",
    }
    try:
        resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[serpapi] Search failed: {e}")
        return None

    for item in data.get("images_results", [])[:8]:
        url = item.get("original")
        if url and _validate_image_url(url):
            print(f"[serpapi] Found image for '{query}': {url[:80]}")
            return url
    return None


def _search_europeana(query: str) -> str | None:
    """Search Europeana for a historically relevant image. Returns direct image URL or None."""
    params = {
        "wskey": EUROPEANA_API_KEY,
        "query": query,
        "qf": "TYPE:IMAGE",
        "rows": "10",
        "profile": "rich",
        "sort": "score desc",
    }
    try:
        resp = requests.get(EUROPEANA_API, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[europeana] Search failed: {e}")
        return None

    items = data.get("items", [])
    for item in items:
        url = None

        # 1. edmIsShownBy — direct source image (best quality)
        shown_by = item.get("edmIsShownBy", [])
        if isinstance(shown_by, list) and shown_by:
            url = shown_by[0]
        elif isinstance(shown_by, str) and shown_by:
            url = shown_by

        # 2. edmPreview — Europeana thumbnail (always available, reliable)
        if not url:
            preview = item.get("edmPreview", [])
            if isinstance(preview, list) and preview:
                # Extract the actual image URL from the thumbnail proxy
                thumb = preview[0]
                # Format: .../url.json?uri=<encoded_url>&type=IMAGE
                if "uri=" in thumb:
                    import urllib.parse
                    encoded = thumb.split("uri=")[1].split("&")[0]
                    url = urllib.parse.unquote(encoded)
                else:
                    url = thumb

        if not url:
            continue

        low = url.lower().split("?")[0]
        if any(low.endswith(ext) for ext in (".pdf", ".gif", ".svg", ".mp4", ".ogv", ".webm")):
            continue

        print(f"[europeana] Found image for '{query}': {url[:80]}")
        return url

    return None


# ---------------------------------------------------------------------------
# Wikimedia Commons (improved: list=search for better relevance ranking)
# ---------------------------------------------------------------------------

def _search_wikimedia(query: str, min_duration: float, media: str) -> str | None:
    if media == "image":
        return _search_wikimedia_image(query)
    else:
        return _search_wikimedia_video(query, min_duration)


def _search_wikimedia_image(query: str) -> str | None:
    """Use list=search (better relevance) instead of generator=search."""
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": f"filetype:bitmap {query}",
        "srnamespace": "6",
        "srlimit": "10",
        "srsort": "relevance",
        "formatversion": "2",
    }
    try:
        resp = requests.get(WIKIMEDIA_API, params=params, headers=WIKIMEDIA_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[wikimedia] Search failed: {e}")
        return None

    hits = data.get("query", {}).get("search", [])
    if not hits:
        return None

    # Fetch thumbnail URLs (1280px) — Wikimedia explicitly recommends thumbnails over originals
    titles = "|".join(h["title"] for h in hits[:5])
    info_params = {
        "action": "query",
        "format": "json",
        "titles": titles,
        "prop": "imageinfo",
        "iiprop": "url|thumburl",
        "iiurlwidth": "1280",
        "formatversion": "2",
    }
    try:
        resp2 = requests.get(WIKIMEDIA_API, params=info_params, headers=WIKIMEDIA_HEADERS, timeout=15)
        resp2.raise_for_status()
        info_data = resp2.json()
    except Exception:
        return None

    for page in info_data.get("query", {}).get("pages", []):
        info = page.get("imageinfo", [{}])[0]
        # Prefer thumbnail URL (avoids rate-limit on originals)
        url = info.get("thumburl") or info.get("url", "")
        if url and any(url.lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
            print(f"[wikimedia] Found image for '{query}': {url[:80]}")
            return url
    return None


def _search_wikimedia_video(query: str, min_duration: float) -> str | None:
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": f"filetype:video {query}",
        "srnamespace": "6",
        "srlimit": "10",
        "srsort": "relevance",
        "formatversion": "2",
    }
    try:
        resp = requests.get(WIKIMEDIA_API, params=params, headers=WIKIMEDIA_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[wikimedia] Video search failed: {e}")
        return None

    hits = data.get("query", {}).get("search", [])
    if not hits:
        return None

    titles = "|".join(h["title"] for h in hits[:5])
    info_params = {
        "action": "query",
        "format": "json",
        "titles": titles,
        "prop": "videoinfo",
        "viiprop": "url|size|metadata",
        "formatversion": "2",
    }
    try:
        resp2 = requests.get(WIKIMEDIA_API, params=info_params, headers=WIKIMEDIA_HEADERS, timeout=15)
        resp2.raise_for_status()
        info_data = resp2.json()
    except Exception:
        return None

    candidates = []
    for page in info_data.get("query", {}).get("pages", []):
        info = page.get("videoinfo", [{}])[0]
        url = info.get("url", "")
        if not any(url.lower().endswith(ext) for ext in (".mp4", ".webm", ".ogv")):
            continue
        duration = _extract_wikimedia_duration(info.get("metadata", []))
        candidates.append({"url": url, "duration": duration})

    if not candidates:
        return None
    sufficient = [c for c in candidates if c["duration"] is None or c["duration"] >= min_duration]
    pool = sufficient if sufficient else candidates
    best = max(pool, key=lambda c: c["duration"] or 0)
    print(f"[wikimedia] Found video for '{query}': {best['url'][:80]}")
    return best["url"]


def _extract_wikimedia_duration(metadata: list) -> float | None:
    for item in metadata:
        if isinstance(item, dict) and item.get("name") == "length":
            try:
                return float(item["value"])
            except (ValueError, TypeError):
                pass
    return None


# ---------------------------------------------------------------------------
# Archive.org
# ---------------------------------------------------------------------------

def _search_archive(query: str, min_duration: float, media: str) -> str | None:
    mediatype = "movies" if media == "video" else "image"
    params = {
        "q": f"{query} AND mediatype:{mediatype}",
        "fl[]": "identifier,title",
        "rows": "5",
        "output": "json",
    }
    try:
        resp = requests.get(ARCHIVE_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[archive] Search failed: {e}")
        return None

    docs = data.get("response", {}).get("docs", [])
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        url = _get_archive_file_url(identifier, media)
        if url:
            print(f"[archive] Found for '{query}': {url[:80]}")
            return url
    return None


def _get_archive_file_url(identifier: str, media: str) -> str | None:
    try:
        resp = requests.get(f"https://archive.org/metadata/{identifier}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    files = data.get("files", [])
    preferred_exts = [".mp4", ".ogv", ".mpeg", ".avi"] if media == "video" else [".jpg", ".jpeg", ".png"]

    for ext in preferred_exts:
        for f in files:
            if not isinstance(f, dict):
                continue
            name = f.get("name", "")
            if isinstance(name, str) and name.lower().endswith(ext):
                return f"https://archive.org/download/{identifier}/{name}"
    return None


# ---------------------------------------------------------------------------
# Vimeo Creative Commons
# ---------------------------------------------------------------------------

# CC licenses safe for commercial use (attribution required but no restrictions)
_VIMEO_CC_LICENSES = {"by", "by-sa"}
# Also accept non-commercial for personal/educational use
_VIMEO_CC_ALL = {"by", "by-sa", "by-nc", "by-nc-sa", "by-nd", "by-nc-nd"}


def _search_vimeo(query: str, min_duration: float) -> str | None:
    """
    Search Vimeo for CC-licensed videos matching query.
    Returns a special 'vimeo:<video_id>:<hls_url>' token — downloaded separately via HLS.
    """
    if not VIMEO_ACCESS_TOKEN:
        return None

    headers = {"Authorization": f"Bearer {VIMEO_ACCESS_TOKEN}"}
    params = {
        "query": query,
        "filter": "CC",
        "per_page": 10,
        "sort": "relevant",
        "direction": "desc",
        "fields": "uri,name,duration,license,download,files",
    }
    try:
        resp = requests.get(VIMEO_API, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[vimeo] Search failed: {e}")
        return None

    videos = data.get("data", [])
    for video in videos:
        duration = video.get("duration", 0)
        if duration < max(min_duration * 0.5, 3):
            continue  # too short even at half speed

        license_code = (video.get("license") or "").replace("https://creativecommons.org/licenses/", "")
        license_code = license_code.strip("/").split("/")[0]  # e.g. "by-nc-sa"
        if license_code not in _VIMEO_CC_ALL:
            continue

        video_id = video.get("uri", "").split("/")[-1]
        if not video_id:
            continue

        # Try to get a direct download link first (faster than HLS)
        direct_url = _vimeo_direct_url(video_id, headers)
        if direct_url:
            print(f"[vimeo] Found CC video '{video.get('name', '')}' ({duration}s, license: {license_code})")
            return direct_url

        # Fall back to HLS streaming URL
        hls_url = _vimeo_hls_url(video_id, headers)
        if hls_url:
            print(f"[vimeo] Found CC video via HLS '{video.get('name', '')}' ({duration}s)")
            return f"vimeo_hls:{hls_url}"

    return None


def _vimeo_direct_url(video_id: str, headers: dict) -> str | None:
    """Try to get a direct MP4 download URL for a Vimeo video."""
    try:
        resp = requests.get(
            f"https://api.vimeo.com/videos/{video_id}",
            headers=headers,
            params={"fields": "download"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        files = resp.json().get("download", [])
        # Pick best HD quality
        hd = [f for f in files if f.get("quality") in ("hd", "source") and f.get("width", 0) >= 1280]
        sd = [f for f in files if f.get("link")]
        candidates = hd or sd
        if candidates:
            best = max(candidates, key=lambda f: f.get("width", 0))
            return best.get("link")
    except Exception:
        pass
    return None


def _vimeo_hls_url(video_id: str, headers: dict) -> str | None:
    """Get HLS stream URL for a Vimeo video."""
    try:
        resp = requests.get(
            f"https://api.vimeo.com/videos/{video_id}",
            headers=headers,
            params={"fields": "play"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        play = resp.json().get("play", {})
        return play.get("hls", {}).get("link")
    except Exception:
        return None


def _download_vimeo(url: str, dest: str):
    """Download a Vimeo video — direct URL or HLS stream via FFmpeg."""
    if url.startswith("vimeo_hls:"):
        hls_url = url[len("vimeo_hls:"):]
        print(f"[vimeo] Downloading HLS stream via FFmpeg...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", hls_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-loglevel", "error",
            dest,
        ], check=True)
    else:
        _download(url, dest)


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------

def _search_pexels_video(query: str, min_duration: float) -> str | None:
    params = {"query": query, "per_page": 10, "orientation": "landscape"}
    try:
        resp = _request_with_retry(PEXELS_VIDEO_SEARCH, params=params,
                                   headers={"Authorization": PEXELS_API_KEY})
    except Exception as e:
        print(f"[pexels] Video search failed: {e}")
        return None
    data = resp.json()
    for video in data.get("videos", []):
        if video["duration"] >= min_duration:
            file_url = _pick_hd_file(video["video_files"])
            if file_url:
                print(f"[pexels] Found video for '{query}': {video['url']}")
                return file_url
    videos = data.get("videos", [])
    if videos:
        best = max(videos, key=lambda v: v["duration"])
        return _pick_hd_file(best["video_files"])
    return None


def _search_pexels_photo(query: str) -> str | None:
    params = {"query": query, "per_page": 5, "orientation": "landscape"}
    try:
        resp = _request_with_retry(PEXELS_PHOTO_SEARCH, params=params,
                                   headers={"Authorization": PEXELS_API_KEY})
    except Exception as e:
        print(f"[pexels] Photo search failed: {e}")
        return None
    data = resp.json()
    photos = data.get("photos", [])
    if photos:
        url = photos[0].get("src", {}).get("large2x") or photos[0].get("src", {}).get("large")
        if url:
            print(f"[pexels] Found photo for '{query}': {url[:80]}")
        return url
    return None


def _pick_hd_file(video_files: list) -> str | None:
    hd = [f for f in video_files if f.get("quality") == "hd" and f.get("width", 0) >= 1280]
    if hd:
        return max(hd, key=lambda f: f.get("width", 0))["link"]
    if video_files:
        return video_files[0]["link"]
    return None


# ---------------------------------------------------------------------------
# FFmpeg processing
# ---------------------------------------------------------------------------

def _get_video_duration(path: str) -> float:
    """Return video duration in seconds via ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", path,
    ], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}")
    return float(json.loads(result.stdout)["format"]["duration"])


def _extract_mid_frame(video_path: str, frame_path: str) -> bool:
    """Extract a frame from the middle of a video for CLIP scoring. Returns True on success."""
    try:
        dur = _get_video_duration(video_path)
        mid = dur / 2
        result = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(mid),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            "-loglevel", "error",
            frame_path,
        ], capture_output=True, timeout=15)
        return result.returncode == 0 and os.path.exists(frame_path) and os.path.getsize(frame_path) > 0
    except Exception:
        return False


def _build_vf(grayscale: bool) -> str:
    filters = [
        f"fps={OUTPUT_FPS}",
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(iw-{OUTPUT_WIDTH})/2:0",
    ]
    if grayscale:
        filters.append("hue=s=0")
    return ",".join(filters)


def _image_to_clip(src: str, dest: str, duration: float, grayscale: bool):
    """Convert a still image to a static video clip — no zoom, no movement."""
    filters = [
        f"fps={OUTPUT_FPS}",
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(iw-{OUTPUT_WIDTH})/2:0",
    ]
    if grayscale:
        filters.append("hue=s=0")

    encoder_flags = ENCODER_FLAGS.get(VIDEO_ENCODER) or []
    if not isinstance(encoder_flags, list):
        encoder_flags = []

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", src,
        "-t", str(duration),
        "-vf", ",".join(filters),
        "-c:v", VIDEO_ENCODER,
        *encoder_flags,
        "-an",
        "-loglevel", "error",
        dest,
    ]
    subprocess.run(cmd, check=True)


def _trim(src: str, dest: str, duration: float, zoom_direction: str = "in", grayscale: bool = False):
    """Trim, resize/crop, normalize to output specs."""
    vf = _build_vf(grayscale)
    encoder_flags = ENCODER_FLAGS.get(VIDEO_ENCODER) or []
    if not isinstance(encoder_flags, list):
        encoder_flags = []
    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", VIDEO_ENCODER,
        *encoder_flags,
        "-an",
        "-loglevel", "error",
        dest,
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _request_with_retry(url: str, headers: dict | None = None, **kwargs) -> requests.Response:
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=15, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"[footage_fetcher] Request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _download(url: str, dest: str):
    print(f"[footage_fetcher] Downloading to {dest}...")
    is_wikimedia = "wikimedia.org" in url or "wikipedia.org" in url
    headers = WIKIMEDIA_DOWNLOAD_HEADERS if is_wikimedia else {}
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, stream=True, timeout=20, headers=headers)
            if resp.status_code == 429:
                # Raise immediately so caller can fallback — don't waste time waiting
                raise requests.HTTPError(f"429 Too Many Requests", response=resp)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    f.write(chunk)
            return
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"[footage_fetcher] Download failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except requests.HTTPError:
            raise  # propagate immediately, no retry
