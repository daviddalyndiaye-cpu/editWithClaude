import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import TEMP_DIR, OUTPUT_DIR, MAX_DOWNLOAD_WORKERS
from transcriber import transcribe, transcribe_and_segment, transcribe_whisperx
from query_generator import generate_queries
from footage_fetcher import fetch_clip
from editor import build_video, get_audio_duration

CACHE_FILE = os.path.join(TEMP_DIR, "segments_cache.json")


def _audio_hash(path: str) -> str:
    """Fast partial hash of audio file (first 64KB) to detect file changes."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()


def _load_cache(audio_path: str) -> list[dict] | None:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            data = json.load(f)
        # Cache is a dict with "audio_hash" and "segments"
        if isinstance(data, dict) and "segments" in data:
            if data.get("audio_hash") == _audio_hash(audio_path):
                return data["segments"]
            else:
                print("[cache] Audio file changed — invalidating cache.")
                return None
        # Legacy format (bare list) — invalidate
        return None
    return None


def _save_cache(segments: list[dict], audio_path: str):
    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"audio_hash": _audio_hash(audio_path), "segments": segments}, f, indent=2)


def _clean_dirs(*dirs: str):
    """Permanently delete directories and all their contents."""
    for d in dirs:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
            print(f"[cleanup] Deleted {d}/")


def _clean_clips_only():
    """Delete only downloaded clips (clip_*.mp4, raw_*) but keep segments_cache.json."""
    if not os.path.exists(TEMP_DIR):
        return
    kept = 0
    deleted = 0
    for fname in os.listdir(TEMP_DIR):
        if fname == "segments_cache.json":
            kept += 1
            continue
        fpath = os.path.join(TEMP_DIR, fname)
        try:
            os.remove(fpath)
            deleted += 1
        except OSError:
            pass
    print(f"[cleanup] Deleted {deleted} clip file(s), kept segments_cache.json")


def main():
    parser = argparse.ArgumentParser(description="Auto B-Roll Video Editor")
    parser.add_argument("--input", required=True, help="Path to input audio file (MP3/WAV/M4A)")
    parser.add_argument("--fresh", action="store_true", help="Delete old temp/output and restart from scratch")
    parser.add_argument("--renderer", choices=["ffmpeg", "remotion"], default="ffmpeg",
                        help="Video renderer: ffmpeg (fast, default) or remotion (richer visuals)")
    parser.add_argument("--style", default=None,
                        help="Visual style in plain language, e.g. 'WW2 black and white archive photos 1940s'")
    args = parser.parse_args()

    audio_path = args.input
    if not os.path.exists(audio_path):
        print(f"Error: audio file not found: {audio_path}")
        sys.exit(1)

    # --fresh: delete clips but preserve transcription cache if audio unchanged
    if args.fresh:
        cached_check = _load_cache(audio_path)
        if cached_check:
            print("[fresh] Same audio detected — keeping transcription cache, deleting clips only.")
            _clean_clips_only()
            _clean_dirs(OUTPUT_DIR)
        else:
            print("[fresh] New audio or no cache — full reset.")
            _clean_dirs(TEMP_DIR, OUTPUT_DIR)

    print("=" * 50)
    print("  Auto B-Roll Video Editor")
    print("=" * 50)

    # Step 1+2: Narrative segmentation (transcribe + queries in one Gemini pass)
    cached = _load_cache(audio_path)
    if cached and all(s.get("query") for s in cached):
        print("\n[1/4] Segments + queries found in cache — skipping.")
        print("[2/4] (included in cache)")
        segments = cached
    else:
        print("\n[1/4] Transcribing with WhisperX (word-level timestamps)...")
        segments = transcribe_whisperx(audio_path, style=args.style)

        if segments:
            print(f"[1/4] WhisperX mode: {len(segments)} blocks with word-accurate timestamps")
            print("[2/4] Queries generated in same pass — skipping separate step.")
            _save_cache(segments, audio_path)
        else:
            print("[1/4] WhisperX unavailable — trying Gemini narrative segmentation...")
            segments = transcribe_and_segment(audio_path, style=args.style)
            if segments:
                print(f"[1/4] Gemini narrative mode: {len(segments)} blocks")
                print("[2/4] Queries generated in same pass — skipping separate step.")
                _save_cache(segments, audio_path)

        if not segments:
            # Fallback to classic pipeline
            print("[1/4] Narrative segmentation failed — falling back to classic pipeline.")
            if cached:
                print("[1/4] Using cached transcription.")
                segments = cached
            else:
                print("[1/4] Transcribing audio (classic mode)...")
                segments = transcribe(audio_path)
                _save_cache(segments, audio_path)

            segments_needing_queries = [s for s in segments if not s.get("query")]
            if not segments_needing_queries:
                print("[2/4] Queries found in cache — skipping.")
            else:
                remaining = len(segments_needing_queries)
                total = len(segments)
                print(f"\n[2/4] Generating B-roll search queries ({remaining}/{total} remaining)...")
                segments = generate_queries(segments, style=args.style,
                                            on_segment_done=lambda segs: _save_cache(segs, audio_path))
                _save_cache(segments, audio_path)

    # Ensure segments cover the full audio duration — extend last segment if needed
    audio_duration = get_audio_duration(audio_path)
    if segments and segments[-1]["end_sec"] < audio_duration - 1.0:
        gap = audio_duration - segments[-1]["end_sec"]
        print(f"[main] Last segment ends at {segments[-1]['end_sec']:.1f}s but audio is {audio_duration:.1f}s "
              f"— extending last segment by {gap:.1f}s")
        segments[-1]["end_sec"] = audio_duration

    # Step 3: Fetch stock footage in parallel (skip clips already downloaded)
    print(f"\n[3/4] Fetching stock footage ({MAX_DOWNLOAD_WORKERS} workers)...")
    print_lock = threading.Lock()
    # Rate-limit Pexels API calls (200/hour = ~1 every 0.3s to be safe)
    api_semaphore = threading.Semaphore(MAX_DOWNLOAD_WORKERS)

    def _fetch_single(i: int, seg: dict, fresh: bool) -> tuple[int, str]:
        duration = seg["end_sec"] - seg["start_sec"]
        trimmed_path = os.path.join(TEMP_DIR, f"clip_{i}.mp4")
        if os.path.exists(trimmed_path) and not fresh:
            with print_lock:
                print(f"  Segment {i + 1}/{len(segments)}: '{seg['query']}' — cached, skipping.")
            return i, trimmed_path
        with print_lock:
            print(f"  Segment {i + 1}/{len(segments)}: '{seg['query']}' ({duration:.1f}s)")
        with api_semaphore:
            path = fetch_clip(seg["query"], duration, i, seg.get("fallback_queries"),
                              style=args.style, segment_text=seg.get("text"))
        return i, path

    results = {}
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_single, i, seg, args.fresh): i
            for i, seg in enumerate(segments)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                idx, path = future.result()
                results[idx] = path
            except Exception as e:
                failed.append(idx)
                print(f"[fetch] ERROR segment {idx + 1}: {type(e).__name__}: {e}")

    if failed:
        failed.sort()
        print(f"\n[fetch] {len(failed)} segment(s) failed: {[i+1 for i in failed]}")
        print("[fetch] Retrying failed segments one by one...")
        for idx in failed:
            seg = segments[idx]
            try:
                _, path = _fetch_single(idx, seg, args.fresh)
                results[idx] = path
                print(f"[fetch] Segment {idx + 1} recovered.")
            except Exception as e:
                print(f"[fetch] Segment {idx + 1} failed again: {e}")
                print(f"[fetch] FATAL: Cannot continue without segment {idx + 1}.")
                sys.exit(1)

    clip_paths = [results[i] for i in range(len(segments))]

    # Step 4: Build final video
    print("\n[4/4] Compositing final video...")
    if args.renderer == "remotion":
        from remotion_bridge import generate_timeline, render, cleanup as remotion_cleanup
        print("[4/4] Using Remotion renderer...")
        generate_timeline(segments, clip_paths, audio_path)
        output_path = render()
        remotion_cleanup()
    else:
        output_path = build_video(clip_paths, audio_path, segments)

    # Cleanup temp files (Windows may hold file handles briefly)
    gc.collect()
    time.sleep(1)
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
        except PermissionError:
            print("[cleanup] Some temp files still locked — skipping cleanup.")

    print("\n" + "=" * 50)
    print(f"  Done! Video saved to: {output_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
