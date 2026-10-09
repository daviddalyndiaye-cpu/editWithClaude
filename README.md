# Auto B-Roll Studio

> **LICENSE NOTICE — READ BEFORE INSTALLING.** This tool is proprietary software by **David Daly Ndiaye**, licensed **only to active members of the YTA Expert community, for their own personal use**. It is not open source. Reselling it, or sharing the repository, code, templates or styles with anyone outside the YTA Expert community, is prohibited and may lead to legal action. See [LICENSE](LICENSE).

Turn a **voice-over** into an edited faceless YouTube video: real B-roll footage and photos matched to what's being said, jump-cut zooms, light-leak transitions, animated text overlays timed to the speech, sound effects, and website-screenshot cards. Built to be driven by **Claude Code**.

Pipeline: transcribe (WhisperX) → shot plan (Gemini, or Claude in a session) → find footage (Creative-Commons YouTube, Wikimedia, Openverse photos) → **review** → compose (HyperFrames HTML/GSAP) → render in parts → join.

## Setup (Windows 10/11)

1. Clone the repo, then in PowerShell **inside the repo folder**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
   It installs Python 3.12, FFmpeg and Node.js (via winget) if missing, creates `.venv`, installs Python packages (WhisperX pulls PyTorch, a large download), runs `npm install` for the HyperFrames renderer, downloads its headless Chrome, and creates `.env`.
2. **Gemini key** (free): get one at https://aistudio.google.com/apikey and paste it into `.env` after `GEMINI_API_KEY=`.
3. **YouTube cookies** (needed, YouTube blocks anonymous downloads):
   - In Chrome, install the extension **"Get cookies.txt LOCALLY"**.
   - Open youtube.com while signed in (a secondary Google account is safer), click the extension → **Export**.
   - Save the file as `cookies.txt` in the repo root. It is git-ignored — never share or commit it.
4. **Effects (optional)**: put your own sound effects, light-leak flashes and grid backdrops in `library/` — see `library/README.md`. Without them the tool works, just without SFX/flashes.
5. Check everything: `.venv\Scripts\python.exe -m studio.preflight`

## Make a video

```powershell
powershell -ExecutionPolicy Bypass -File start_app.ps1
```
Open **http://localhost:8765**, drop the voice-over (mp3/wav/m4a), pick an accent colour, and follow the live progress bars. A 20-minute voice-over takes roughly: transcription 5–15 min (CPU), footage search ~1 h, render ~1–1.5 h.

**Leave "Skip manual review" unticked and let Claude review.** The job pauses at *Your review*; in Claude Code say *"review the job at localhost:8765 and approve it"*. Claude follows `CLAUDE.md`: looks at every contact sheet, replaces bad clips, fills gaps, approves, then checks the final video.

The video lands in `projects/<name>/out/<name>.mp4`, with `CREDITS.md` next to it (Creative-Commons clips need credit in your video description).

## Using it with Claude Code

Open Claude Code in this folder. `CLAUDE.md` holds the full playbook: the 5-step process, the review checklist, and every known pitfall (YouTube rate limits, Gemini 503s, render size limits). Useful commands Claude uses:

| Command | What it does |
|---|---|
| `python -m studio.preflight` | checks disk space, cookies, tools, effects |
| `python -m studio.review sheets <slug>` | contact sheets of every clip → `projects/<slug>/rv_N.jpg` |
| `python -m studio.review fill <slug> 3,7,12` | fill bad/empty shots with on-topic clips already in the job |
| `python -m studio.fetch <slug> 3,7,12` | re-search footage for specific shots |
| `python -m studio.hf_build <slug>` | compose a project into HyperFrames HTML |

## Good to know

- **Niche subjects** (a specific boat brand, a small company) have little free footage: expect generic-but-related shots and some repeats. Your own photos fix that.
- **YouTube rate limits**: the fetcher is deliberately slow (pauses between searches). If you see "Sign in to confirm you're not a bot", re-export `cookies.txt` or wait ~1 hour.
- **Gemini free tier** is often busy (503) — the tool retries and rotates models automatically.
- **Licensing**: footage is filtered to Creative-Commons YouTube videos and CC photos; you are still responsible for credits and for checking anything you monetise.
- The old one-command FFmpeg pipeline (`main.py`, `editor.py`, …) is still here but the web app + `studio/` is the maintained path.
