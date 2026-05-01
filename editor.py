import os
import random
import subprocess
import json
from config import (
    CROSSFADE_DURATION,
    OUTPUT_DIR,
    OUTPUT_FILENAME,
    VIDEO_ENCODER,
    ENCODER_FLAGS,
)

# Dynamic pacing: target clip duration (seconds) by speech rate (words/sec)
# Fast speech → shorter clips (more cuts), slow speech → longer clips
def _target_duration(words_per_sec: float, segment_duration: float) -> float:
    """
    Return the ideal clip display duration based on speech pace.
    Never shorter than 3s, never longer than the segment itself.
    """
    if words_per_sec > 2.8:
        target = 6.0   # fast/dense narration — quick cuts
    elif words_per_sec > 1.8:
        target = 10.0  # normal pace
    elif words_per_sec > 0.8:
        target = 15.0  # slow/contemplative
    else:
        target = 20.0  # very slow or silence — hold image
    return min(target, max(3.0, segment_duration))


def _select_transition(index: int, total_clips: int) -> str:
    """Always use smooth fade transitions — clean documentary style."""
    if index >= total_clips - 2:
        return "fadeblack"
    return random.choice(["fade", "dissolve", "fadeblack"])


def get_audio_duration(audio_path: str) -> float:
    """Return duration of audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for audio {audio_path!r}:\n{result.stderr.strip()}")
    return float(json.loads(result.stdout)["format"]["duration"])


def build_video(clip_paths: list[str], audio_path: str,
                segments: list[dict] | None = None) -> str:
    """
    Build final video using FFmpeg concat demuxer for frame-accurate timing.

    Each clip is anchored to its exact start_sec in the audio timeline.
    Speech rate (words_per_sec) drives dynamic cut density per section.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)

    # Validate clips — skip any that are corrupt or missing
    valid_pairs = [(p, s) for p, s in zip(clip_paths, segments or [None] * len(clip_paths))
                   if _is_valid_clip(p)]
    if len(valid_pairs) < len(clip_paths):
        bad = len(clip_paths) - len(valid_pairs)
        print(f"[editor] WARNING: {bad} corrupt/missing clip(s) skipped before compositing.")
    if not valid_pairs:
        raise RuntimeError("No valid clips to composite.")
    clip_paths = [p for p, _ in valid_pairs]
    segments = [s for _, s in valid_pairs] if segments else None

    audio_duration = get_audio_duration(audio_path)
    print(f"[editor] Audio duration: {audio_duration:.3f}s")

    if len(clip_paths) == 1:
        _attach_audio(clip_paths[0], audio_path, output_path)
        print(f"[editor] Done! Output saved to: {output_path}")
        return output_path

    # Build a timeline of clip entries, each anchored to its audio timestamp.
    # If segments carry start_sec/end_sec, use those as anchors.
    # Otherwise, lay clips end-to-end (legacy fallback).
    timeline = _build_timeline(clip_paths, segments, audio_duration)

    print(f"[editor] Timeline: {len(timeline)} entries covering {timeline[-1]['end']:.2f}s")
    for entry in timeline:
        wps = entry.get("words_per_sec", -1)
        pace = f"{wps:.1f}w/s" if wps >= 0 else "n/a"
        print(f"  [{entry['start']:.2f}s-{entry['end']:.2f}s] ({entry['end']-entry['start']:.1f}s, {pace}) → {os.path.basename(entry['path'])}")

    # Render each timeline entry to a normalized clip of exact duration
    rendered = _render_timeline(timeline)

    # Concatenate rendered clips with xfade transitions
    _concat_with_xfade(rendered, audio_path, audio_duration, output_path)

    # Cleanup rendered temp clips
    for r in rendered:
        if os.path.exists(r):
            try:
                os.remove(r)
            except OSError:
                pass

    print(f"[editor] Done! Output saved to: {output_path}")
    return output_path


def _build_timeline(clip_paths: list[str], segments: list[dict] | None,
                    audio_duration: float) -> list[dict]:
    """
    Build a precise timeline of {path, start, end, words_per_sec} entries.

    If segments have start_sec/end_sec, each clip is anchored exactly there.
    Speech rate drives sub-segmentation: fast sections get more cuts.
    """
    cf = CROSSFADE_DURATION

    if not segments or not all(s and "start_sec" in s and "end_sec" in s for s in segments):
        # Legacy: lay clips end-to-end
        timeline = []
        cursor = 0.0
        for path in clip_paths:
            dur = _get_duration(path)
            timeline.append({"path": path, "start": cursor, "end": cursor + dur, "words_per_sec": 0.0})
            cursor += dur - cf
        return timeline

    timeline = []
    for path, seg in zip(clip_paths, segments):
        seg_start = seg["start_sec"]
        seg_end = min(seg["end_sec"], audio_duration)
        seg_dur = seg_end - seg_start
        if seg_dur <= 0:
            continue

        wps = seg.get("words_per_sec", 0.0)
        clip_dur = _get_duration(path)

        # How long should this clip be displayed?
        # Use speech-rate-based target, capped to segment and actual clip length
        target = _target_duration(wps, seg_dur)
        display_dur = min(target, seg_dur, clip_dur)
        display_dur = max(display_dur, cf * 2 + 0.1)  # never shorter than 2x crossfade

        timeline.append({
            "path": path,
            "start": seg_start,
            "end": seg_start + display_dur,
            "words_per_sec": wps,
        })

    if not timeline:
        return [{"path": p, "start": i * 10.0, "end": (i + 1) * 10.0, "words_per_sec": 0.0}
                for i, p in enumerate(clip_paths)]

    # Close any gaps between entries and ensure full audio coverage
    for i in range(len(timeline) - 1):
        gap = timeline[i + 1]["start"] - timeline[i]["end"]
        if gap > 0.1:
            # Extend current clip to bridge gap (hold last frame)
            timeline[i]["end"] = timeline[i + 1]["start"]
        elif gap < -cf:
            # Overlap — trim current clip back
            timeline[i]["end"] = timeline[i + 1]["start"] + cf

    # Extend last clip to cover full audio
    if timeline[-1]["end"] < audio_duration:
        timeline[-1]["end"] = audio_duration

    return timeline


def _render_timeline(timeline: list[dict]) -> list[str]:
    """
    Re-encode each timeline entry to its exact display duration.
    Returns list of temp file paths in the same order.
    """
    rendered = []
    for i, entry in enumerate(timeline):
        display_dur = entry["end"] - entry["start"]
        out = entry["path"].replace(".mp4", f"_r{i}.mp4")
        clip_dur = _get_duration(entry["path"])

        if clip_dur >= display_dur - 0.05:
            # Clip is long enough — just trim to exact duration
            subprocess.run([
                "ffmpeg", "-y",
                "-i", entry["path"],
                "-t", f"{display_dur:.6f}",
                "-c:v", VIDEO_ENCODER,
                *ENCODER_FLAGS.get(VIDEO_ENCODER, []),
                "-an", "-loglevel", "error",
                out,
            ], check=True)
        else:
            # Clip too short — loop it to fill the needed duration
            subprocess.run([
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", entry["path"],
                "-t", f"{display_dur:.6f}",
                "-c:v", VIDEO_ENCODER,
                *ENCODER_FLAGS.get(VIDEO_ENCODER, []),
                "-an", "-loglevel", "error",
                out,
            ], check=True)
        rendered.append(out)
    return rendered


def _concat_with_xfade(rendered: list[str], audio_path: str,
                        audio_duration: float, output_path: str):
    """
    Concatenate rendered clips with xfade transitions and mux audio.
    All clips are already exact-duration so offsets are deterministic.
    """
    cf = CROSSFADE_DURATION
    durations = [_get_duration(p) for p in rendered]

    inputs = []
    for p in rendered:
        inputs.extend(["-i", p])

    # Build xfade filter chain
    filter_parts = []
    offsets = []
    cumulative = 0.0
    for i in range(len(rendered) - 1):
        cumulative += durations[i] - cf
        offsets.append(round(cumulative, 6))

    total_transitions = len(rendered) - 1

    if len(rendered) == 2:
        t = _select_transition(0, total_transitions)
        filter_parts.append(f"[0][1]xfade=transition={t}:duration={cf}:offset={offsets[0]}[vout]")
        print(f"[editor] Transition 1/{total_transitions}: {t} @ {offsets[0]:.3f}s")
    else:
        t = _select_transition(0, total_transitions)
        filter_parts.append(f"[0][1]xfade=transition={t}:duration={cf}:offset={offsets[0]}[v01]")
        print(f"[editor] Transition 1/{total_transitions}: {t} @ {offsets[0]:.3f}s")

        for i in range(2, len(rendered)):
            prev_label = f"v{i-2:02d}{i-1:02d}" if i > 2 else "v01"
            is_last = (i == len(rendered) - 1)
            out_label = "vout" if is_last else f"v{i-1:02d}{i:02d}"
            t = _select_transition(i - 1, total_transitions)
            print(f"[editor] Transition {i}/{total_transitions}: {t} @ {offsets[i-1]:.3f}s")
            filter_parts.append(
                f"[{prev_label}][{i}]xfade=transition={t}"
                f":duration={cf}:offset={offsets[i-1]}[{out_label}]"
            )

    filter_complex = ";".join(filter_parts)

    print(f"[editor] Compositing {len(rendered)} clips → {output_path}")
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", f"{len(rendered)}:a",
        "-c:v", VIDEO_ENCODER,
        *ENCODER_FLAGS.get(VIDEO_ENCODER, []),
        "-c:a", "aac",
        "-t", str(audio_duration),
        "-loglevel", "warning",
        output_path,
    ]
    subprocess.run(cmd, check=True)


def _get_duration(path: str) -> float:
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path!r}:\n{result.stderr.strip()}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _is_valid_clip(path: str) -> bool:
    """Return True if path exists and ffprobe can read it."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        _get_duration(path)
        return True
    except Exception:
        return False


def _attach_audio(video_path: str, audio_path: str, output_path: str):
    """For single clip — just mux video + audio."""
    audio_duration = get_audio_duration(audio_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-t", str(audio_duration),
        "-loglevel", "error",
        output_path,
    ]
    subprocess.run(cmd, check=True)
