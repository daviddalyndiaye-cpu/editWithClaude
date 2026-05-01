# Auto B-Roll Video Editor

Automatically generates B-roll videos from audio files. Give it a voiceover and it produces a polished video with semantically matching stock footage, crossfade transitions, and the original audio.

## How it works

1. **Transcribe** — Uploads audio to Gemini and gets sentence-level timestamps
2. **Generate queries** — Gemini writes specific Pexels search queries for each segment
3. **Fetch footage** — Downloads and trims HD stock clips from Pexels
4. **Composite** — FFmpeg stitches clips with crossfade transitions and attaches audio

## Requirements

- Python 3.12+
- [FFmpeg](https://ffmpeg.org/download.html) installed and on PATH (with NVENC support for GPU encoding)
- A [Gemini API key](https://aistudio.google.com/apikey)
- A [Pexels API key](https://www.pexels.com/api/) (free)

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
```

Create a `.env` file:

```
GEMINI_API_KEY=your_key_here
PEXELS_API_KEY=your_key_here
```

## Usage

```bash
# Basic run
python main.py --input voice.mp3

# Fresh run (deletes old temp + output files)
python main.py --input voice.mp3 --fresh
```

Output is saved to `output/final_edited.mp4`.

## Caching

The app caches intermediate results in `temp/`:
- Transcription + queries are saved to `segments_cache.json`
- Downloaded clips are saved as `clip_0.mp4`, `clip_1.mp4`, etc.

If the pipeline crashes mid-run, just re-run the same command — it picks up where it left off. Use `--fresh` to start over completely.

## Configuration

Edit `config.py` to change:

| Setting | Default | Description |
|---|---|---|
| `OUTPUT_WIDTH` | 1920 | Video width |
| `OUTPUT_HEIGHT` | 1080 | Video height |
| `OUTPUT_FPS` | 30 | Frame rate |
| `MIN_SEGMENT_DURATION` | 4s | Minimum segment length before merging |
| `MAX_SEGMENT_DURATION` | 15s | Maximum segment length |
| `CROSSFADE_DURATION` | 0.5s | Crossfade between clips |
| `GEMINI_TRANSCRIPTION_MODEL` | gemini-2.5-pro | Model for transcription |
| `GEMINI_QUERY_MODEL` | gemini-2.5-flash | Model for query generation |

## Project structure

```
main.py               — CLI entry point, orchestrates the pipeline
config.py             — Settings, API keys, paths
transcriber.py        — Gemini audio transcription + sentence merging
query_generator.py    — Gemini semantic B-roll query generation
footage_fetcher.py    — Pexels search, download, trim via FFmpeg
editor.py             — FFmpeg crossfade concatenation + audio muxing
```
