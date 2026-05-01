"""Bridge between Python pipeline and Remotion renderer."""
import json
import os
import shutil
import subprocess
import sys

from config import (
    TEMP_DIR, OUTPUT_DIR, OUTPUT_FILENAME, OUTPUT_FPS,
    OUTPUT_WIDTH, OUTPUT_HEIGHT, CROSSFADE_DURATION,
)

REMOTION_DIR = os.path.join(os.path.dirname(__file__), "remotion")
REMOTION_PUBLIC = os.path.join(REMOTION_DIR, "public")
TIMELINE_FILE = os.path.join(REMOTION_DIR, "timeline.json")


def _map_transition(ffmpeg_name: str) -> str:
    """Pass FFmpeg transition names through — Remotion side handles mapping."""
    return ffmpeg_name


def generate_timeline(segments: list[dict], clip_paths: list[str],
                      audio_path: str) -> str:
    """Generate timeline.json and copy assets to Remotion public/ folder.
    Returns the path to the timeline JSON file."""
    os.makedirs(REMOTION_PUBLIC, exist_ok=True)

    # Copy audio to public/
    audio_dest = os.path.join(REMOTION_PUBLIC, "audio.mp3")
    shutil.copy2(audio_path, audio_dest)

    # Copy clips to public/ and build segment data
    timeline_segments = []
    for i, (seg, clip_path) in enumerate(zip(segments, clip_paths)):
        clip_filename = f"clip_{i}.mp4"
        clip_dest = os.path.join(REMOTION_PUBLIC, clip_filename)

        # Only copy if source != dest
        if os.path.abspath(clip_path) != os.path.abspath(clip_dest):
            shutil.copy2(clip_path, clip_dest)

        duration = seg["end_sec"] - seg["start_sec"]
        transition = seg.get("visual_mood", "fade")

        # Use the mood-based transition from the editor logic
        from editor import _select_transition
        total_transitions = len(segments) - 1
        transition_name = _select_transition(
            min(i, total_transitions - 1),
            total_transitions,
            seg.get("visual_mood"),
        )

        timeline_segments.append({
            "clipPath": clip_filename,
            "durationSec": round(duration, 3),
            "transition": transition_name,
            "transitionDurationSec": CROSSFADE_DURATION,
            "keyText": seg.get("key_text"),
            "mood": seg.get("visual_mood", "calm"),
        })

    timeline = {
        "fps": OUTPUT_FPS,
        "width": OUTPUT_WIDTH,
        "height": OUTPUT_HEIGHT,
        "audioFile": "audio.mp3",
        "segments": timeline_segments,
    }

    with open(TIMELINE_FILE, "w") as f:
        json.dump(timeline, f, indent=2)

    print(f"[remotion] Timeline generated: {len(timeline_segments)} segments")
    return TIMELINE_FILE


def render(output_path: str | None = None) -> str:
    """Render the video using Remotion CLI. Returns output file path."""
    if output_path is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)

    # Make output path absolute for Remotion
    abs_output = os.path.abspath(output_path)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts", "BRollVideo",
        abs_output,
        f"--props={os.path.basename(TIMELINE_FILE)}",
    ]

    print(f"[remotion] Rendering video...")
    print(f"[remotion] Command: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=REMOTION_DIR,
        capture_output=False,
        text=True,
        shell=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Remotion render failed with exit code {result.returncode}")

    print(f"[remotion] Done! Output: {output_path}")
    return output_path


def cleanup():
    """Remove copied assets from Remotion public/ folder."""
    if os.path.exists(REMOTION_PUBLIC):
        for f in os.listdir(REMOTION_PUBLIC):
            filepath = os.path.join(REMOTION_PUBLIC, f)
            if os.path.isfile(filepath):
                os.remove(filepath)
