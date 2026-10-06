# CLAUDE.md — Auto B-Roll Studio (read this before touching a video)

Voice-over in → edited faceless video out. Web app: `start_app.ps1` → http://localhost:8765. Code: `studio/` (pipeline), `app/` (web UI + job runner), `library/` (sfx, light-leak flashes, backdrops). Projects live in `projects/<slug>/`.

## The process that works (follow it every time)
1. **Upload** the audio in the app (or `studio.transcribe`). WhisperX runs on CPU (~0.6× real time).
2. **Plan** (Gemini in the app; Claude in a Claude Code session may write `plan.json` directly). The plan detects one **subject** (e.g. "Nordhavn") and every search must carry it. Shots 4–8 s, mixed kinds: ~55% video, ~35% real photos, ~10% website screenshots. Overlays timed to spoken words. No static text cards, no captions unless asked.
3. **Fetch** (`studio.fetch`): CC YouTube + Wikimedia + Openverse photos. Gentle pacing is mandatory (see pitfalls).
4. **REVIEW — never skip, never leave it to the user.** `python -m studio.review sheets <slug>` → look at **every** contact sheet. Reject: talking heads, slides/text, game or screen captures, namesake places, duplicates, black frames. Replace with `replace` (app API) using new queries, then look again. Fill what is still empty/bad with `python -m studio.review fill <slug> <ids>` (on-topic reuse, ≤2 uses per clip, long shots split in two cuts).
5. **Approve** → build (parts of ≤18 clips) → render each part → join. Then check frames across the whole video and tell the user honestly what is still weak.

## What the renderer does by default
- Jump-cut zooms inside each video shot (wide ↔ punched-in every ~3.5 s); Ken-Burns on photos; screenshot cards pop in over looping grid/topo backdrops then zoom into the data.
- Light-leak flash (`library/fx/burn-XX.mp4`, screen blend) on every 3rd cut (`plan.burns`, 0 disables). Whoosh/impact on cuts, **cha-ching** (`library/sfx/money-*.wav`) on money count-ups.
- Overlays: lower_third, stat (count-up, number must be spoken), tag, list. Plan `"captions": false` by default.

## Hard rules / pitfalls (each one cost hours)
- **Never put ~70+ clips in one HyperFrames composition** → frame extraction fails. Always split (`studio.slice`, ≤18 clips per part) and normalise clips to closed GOP (`hf_build.norm_video`).
- **YouTube rate limits.** Search bursts return *empty* lists and downloads hit "not a bot". Keep ≥4 s between searches, 8–16 s between downloads, never run two fetches at once. Needs `cookies.txt` (exported from Chrome with "Get cookies.txt LOCALLY") in the repo root; Chrome/Edge cookies cannot be read directly on this PC. If blocked, wait ~1 h.
- **Gemini free tier**: per-model daily quota and frequent 503s. Code rotates `gemini-3.5-flash → 3.7 → 3.1-flash-lite → 3.6`. `gemini-2.5-flash` is 404 for this key.
- **Namesakes**: "Nordhavn" is also a Copenhagen district (trains, buses, apartment blocks). Photos must pass `photo_subject_ok` (subject + yacht/boat word, no district words).
- **Talking heads / slides**: `has_talking_head` (OpenCV Haar, needs `opencv-python-headless==4.10.0.84`) rejects big faces; still eyeball sheets for slides and screen recordings.
- Clips are cut from the **body** of a video (`pick_starts`), never from the first seconds (intros) — that was the YouTuber-face bug.
- The review step is Claude's job. The app's "Skip manual review" default only means the AI QC runs and it renders; when a user says a job is waiting, review it yourself.
- Disk: renders need free space (check `Get-PSDrive C`; >5 GB). Clean `projects/*_p*` and `%TEMP%\hyperframes-extract-cache-u` when low.
- PowerShell edits of `job.json` add a BOM — edit with Python. Python heredocs mangle `\b`/`\n` escapes: build regex strings with `chr(92)` or write files with the editor tool.
- Drive shared files hit "too many users" download limits — ask the user to download in the browser and give local paths. Many pack assets are vertical (not usable for 16:9).

## Setup & assets
- First run on a new PC: `setup.ps1` (Python 3.12, FFmpeg, Node, `.venv`, `npm install` → HyperFrames in `./node_modules`, headless Chrome). Then `.env` (GEMINI_API_KEY) and `cookies.txt`. Verify with `python -m studio.preflight`.
- `library/` is NOT in git (licensed packs). Expected names: `library/sfx/{whoosh,impact,pop,money}-*.wav`, `library/fx/burn-*.mp4` (0.3 s flashes on black), `library/bg/bg*-*.mp4` (16:9 dark loops). See `library/README.md`. Missing folders only disable those effects.

## Credits
Every external clip/photo is recorded in `sources.json` → `CREDITS.md` (CC-BY needs credit in the video description). Mention it when delivering.

## Next improvements (agreed backlog)
"Your images" upload (user photos/AI images placed on matching lines) · skip punch-in on slide-like clips · fewer transitions + occasional accent wipe · pointer callouts, quote/timeline/bar-chart overlays · extra SFX from the 71-file pack · more transparent-video overlays.
