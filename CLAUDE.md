# CLAUDE.md

## Project overview

Auto B-Roll Video Editor — a Python CLI tool that takes an audio file (voiceover) and automatically produces a video with semantically matching stock footage from Pexels, using Gemini for transcription and query generation.

## Architecture

Linear pipeline: `main.py` orchestrates 4 steps:

1. `transcriber.py` — Gemini transcribes audio → sentence-level JSON with timestamps → merges into 4-15s segments
2. `query_generator.py` — Gemini generates specific Pexels search queries per segment
3. `footage_fetcher.py` — Pexels API search → download HD clip → FFmpeg trim/resize/crop to 1920x1080@30fps
4. `editor.py` — Pure FFmpeg: `xfade` filter chain for crossfades + audio muxing → `output/final_edited.mp4`

## Key decisions

- **No MoviePy for export** — MoviePy's Python per-frame processing was too slow. All compositing is pure FFmpeg via subprocess.
- **GPU encoding** — Uses `h264_nvenc` (NVIDIA NVENC). Requires an NVIDIA GPU with FFmpeg NVENC support.
- **All clips normalized to 30fps** in `footage_fetcher._trim()` — required for FFmpeg's `xfade` filter (mismatched timebases cause errors).
- **Caching** — `temp/segments_cache.json` stores transcription + queries. Clip files (`temp/clip_N.mp4`) are reused on re-runs. `--fresh` flag wipes everything.

## Tech stack

- Python 3.12+, FFmpeg (with NVENC), Gemini API (`google-genai`), Pexels API
- No heavy Python video libraries in the export path — all video processing is FFmpeg

## Config

All settings in `config.py`. API keys loaded from `.env` (never commit this file).

Model names are configurable: `GEMINI_TRANSCRIPTION_MODEL` and `GEMINI_QUERY_MODEL`.

## Common tasks

```bash
# Run the pipeline
python main.py --input voice.mp3

# Fresh start (delete temp + output)
python main.py --input voice.mp3 --fresh

# Install deps
pip install -r requirements.txt
```

## Pitfalls

- FFmpeg `xfade` filter requires all input clips to have identical fps and resolution — that's why `_trim()` forces `fps=30` and `scale+crop` to 1920x1080.
- On Windows, `shutil.rmtree` can fail on temp files if FFmpeg or Python still holds handles. The cleanup handles this with `gc.collect()` + retry.
- Pexels API: 200 req/hour, 20k req/month. A 20-min video uses ~80-120 requests.
