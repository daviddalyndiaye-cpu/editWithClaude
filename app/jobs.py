"""Pipeline runner for the web app: audio -> transcript -> plan -> footage -> review -> build -> render -> video.
One heavy job runs at a time. State lives in projects/<slug>/job.json so it survives restarts (resume skips done stages)."""
import glob, json, math, os, re, shutil, subprocess, sys, threading, time, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.join(ROOT, "projects")
HF_PREFIX = ROOT  # `npm install` in the repo root puts HyperFrames in ./node_modules
PART_CLIPS = 18  # clips per render part (HyperFrames chokes on ~70+ clips in one composition)
STAGES = [("upload", "Upload"), ("transcribe", "Transcribe voice"), ("plan", "Plan shots"), ("fetch", "Find footage"),
          ("review", "Your review"), ("build", "Build scenes"), ("render", "Render video"), ("join", "Finish")]

JOBS = {}                     # id -> job dict
RT = {}                       # id -> runtime (process, events)  (not persisted)
QUEUE = []
LOCK = threading.RLock()
WORKER = {"t": None}


# ------------------------------------------------------------------ helpers
def env():
    e = dict(os.environ, PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    extra = []
    for exe in ("ffmpeg.exe", "node.exe"):
        if not shutil.which(exe):
            hits = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg*\bin")) if exe.startswith("ffmpeg") else [r"C:\Program Files\nodejs"]
            extra += hits
    e["PATH"] = os.pathsep.join(extra + [e.get("PATH", "")])
    return e


def pdir(j):
    return os.path.join(PROJ, j["slug"])


def save(j):
    with LOCK:
        os.makedirs(pdir(j), exist_ok=True)
        json.dump({k: v for k, v in j.items()}, open(os.path.join(pdir(j), "job.json"), "w", encoding="utf-8"), indent=1)


def log(j, msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg.rstrip()}"
    with open(os.path.join(pdir(j), "job.log"), "a", encoding="utf-8", errors="replace") as f:
        f.write(line + "\n")


def tail(j, n=60):
    p = os.path.join(pdir(j), "job.log")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()[-n:]


def stage(j, key, status=None, pct=None, detail=None):
    st = j["stages"][key]
    if status:
        st["status"] = status
        if status == "running" and not st.get("started"):
            st["started"] = time.time()
        if status in ("done", "error"):
            st["ended"] = time.time()
    if pct is not None:
        st["pct"] = pct
    if detail is not None:
        st["detail"] = detail
    j["stage"] = key
    save(j)


def run_proc(j, args, cwd=ROOT, poll=None, interval=3.0, filt=None):
    """Run a subprocess, stream its output to the job log, call poll() periodically. Returns exit code."""
    p = subprocess.Popen(args, cwd=cwd, env=env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
    RT[j["id"]]["proc"] = p

    def pump():
        for line in p.stdout:
            line = line.rstrip()
            if line and (filt is None or filt(line)):
                log(j, line[:300])
    t = threading.Thread(target=pump, daemon=True); t.start()
    while p.poll() is None:
        if j.get("cancel"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            raise Cancelled()
        if poll:
            try:
                poll()
            except Exception:
                pass
        time.sleep(interval)
    t.join(2)
    return p.returncode


class Cancelled(Exception):
    pass


def py(*a):
    return [sys.executable, "-u", *a]


def load_json(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


# ------------------------------------------------------------------ stages
def s_transcribe(j):
    words = os.path.join(pdir(j), "words.json")
    if os.path.exists(words):
        return
    t0 = time.time()
    audio = os.path.join(pdir(j), j["audio"])
    dur = j.get("audio_seconds") or 600
    est = max(60, dur * 0.65)                       # CPU WhisperX: roughly 0.65x real time on this PC

    def poll():
        el = time.time() - t0
        stage(j, "transcribe", pct=min(95, int(100 * el / est)), detail=f"{int(el // 60)}m{int(el % 60):02d}s elapsed (CPU, about {int(est // 60)} min expected)")
    rc = run_proc(j, py("-m", "studio.transcribe", audio, j["slug"]), poll=poll,
                  filt=lambda l: "[transcribe]" in l or "rror" in l)
    if rc or not os.path.exists(words):
        raise RuntimeError("Transcription failed (see log)")


def s_plan(j):
    if os.path.exists(os.path.join(pdir(j), "plan.json")):
        return
    o = j["options"]
    code = (f"from studio.plan_gemini import make_plan; make_plan({j['slug']!r}, accent={o['accent']!r}, captions={o['captions']!r})")
    rc = run_proc(j, py("-c", code))
    if rc or not os.path.exists(os.path.join(pdir(j), "plan.json")):
        raise RuntimeError("Planning failed (Gemini unavailable or quota used up - see log)")
    plan = load_json(os.path.join(pdir(j), "plan.json"))
    stage(j, "plan", detail=f"{len(plan['shots'])} shots")


def n_shots(j):
    plan = load_json(os.path.join(pdir(j), "plan.json"), {"shots": []})
    return len([s for s in plan["shots"] if s["kind"] != "card"])


def s_fetch(j, redo=None, qc=True, base=0, span=90):
    """Progress is mapped to [base, base+span]. First pass uses 0-90, the AI swap phase uses 90-100."""
    total = n_shots(j)
    reg_p = os.path.join(pdir(j), "sources.json")
    seen = {"n": 0, "ids": set()}

    def filt(l):
        m = re.match(r"\[fetch\] shot (\d+)", l)
        if m:
            seen["ids"].add(m.group(1)); seen["n"] = len(seen["ids"])
        return l.startswith("[fetch]") or "OK" in l or "rror" in l[:30]

    def poll():
        if redo:
            n = min(seen["n"], len(redo))
            stage(j, "fetch", pct=int(base + span * n / max(len(redo), 1)), detail=f"replacing clip {n}/{len(redo)}")
        else:
            reg = load_json(reg_p, {})
            done = len([k for k, v in reg.items() if v.get("file") or v.get("platform") == "none"])
            stage(j, "fetch", pct=int(span * done / max(total, 1)), detail=f"{done}/{total} shots have footage")
    args = py("-m", "studio.fetch", j["slug"]) + ([",".join(map(str, redo))] if redo else [])
    rc = run_proc(j, args, poll=poll, interval=4, filt=filt)
    if rc:
        raise RuntimeError("Footage search failed (YouTube may be blocking: see log)")
    if not redo:
        poll()
    if qc and not redo and j["options"].get("ai_check", True) and not j.get("qc_done"):
        auto_qc(j)


SUFFIXES = (" b-roll", " drone footage", " stock footage 4k", " footage no copyright")


def rotate_queries(j, ids):
    """New search terms for clips that were rejected: same subject, but phrased the way clean b-roll is titled."""
    plan_p = os.path.join(pdir(j), "plan.json"); plan = load_json(plan_p)
    for s in plan["shots"]:
        if s["id"] in ids:
            base = []
            for q in s.get("queries", []):
                q = re.sub(r"\b(b-roll|drone footage|stock footage 4k|footage no copyright|footage|stock video|stock|drone)\b", "", q, flags=re.I)
                q = " ".join(q.split())
                if q and q not in base:
                    base.append(q)
            tried = s.get("tried", 0)
            if s.get("kind") in ("image", "screenshot"):      # photo searches: plain names, no video words
                s["queries"] = (base[1:] + base[:1]) if len(base) > 1 else base
                s["tried"] = tried + 1
                continue
            new = []
            for i, q in enumerate(base[:3]):
                new.append(q + SUFFIXES[(tried + i) % len(SUFFIXES)])
            for q in base[:2]:
                new.append(q + SUFFIXES[(tried + 2) % len(SUFFIXES)])
            s["queries"] = new or s.get("queries", [])
            s["tried"] = tried + 1
    json.dump(plan, open(plan_p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


SEVERE = ("talking", "person", "presenter", "face", "vlog", "text", "title", "slate", "disclaimer", "subtitle", "logo",
          "watermark", "banner", "black", "blank", "screen", "slide", "diagram", "unrelated")


def auto_qc(j):
    """One AI pass. Replace only the worst offenders (capped at 30% of the clips) - the rest is for the user's review."""
    j["qc_done"] = True; save(j)
    stage(j, "fetch", pct=91, detail="AI is checking the footage...")
    code = f"from studio.qc_gemini import check; import json; print('QCRESULT', json.dumps(check({j['slug']!r})))"
    out = []
    run_proc(j, py("-c", code), filt=lambda l: (out.append(l) or True) and l.startswith("[qc]"))
    try:
        res = json.loads(next(l for l in reversed(out) if l.startswith("QCRESULT")).split(" ", 1)[1])
    except Exception:
        log(j, "[qc] skipped (no result)"); return
    if not res:
        return
    def sev(item):
        why = (item[1] or "").lower()
        return 0 if any(k in why for k in SEVERE) else 1
    ranked = sorted(res.items(), key=sev)
    cap = max(6, int(0.3 * n_shots(j)))
    ids = [int(i) for i, _ in ranked[:cap]]
    log(j, f"[qc] AI flagged {len(res)} clips; replacing the {len(ids)} worst, the rest are left for your review")
    rotate_queries(j, ids)
    s_fetch(j, redo=ids, qc=False, base=92, span=8)


def s_review(j):
    o = j["options"]
    if o.get("auto_approve"):
        return
    ev = RT[j["id"]]["review"]
    while True:
        ev.clear()
        j["status"] = "review"
        stage(j, "review", status="running", pct=0, detail="Waiting for you: check the footage, replace bad clips, then approve")
        while not ev.wait(1.0):
            if j.get("cancel"):
                raise Cancelled()
        action = RT[j["id"]].get("action") or {"type": "approve"}
        if action["type"] == "approve":
            j["status"] = "running"
            return
        if action["type"] == "replace":
            ids = [int(i) for i in action["ids"]]
            rotate_queries(j, ids)
            j["status"] = "running"
            stage(j, "review", detail=f"Replacing {len(ids)} clips...")
            log(j, f"[review] replacing shots {ids}")
            s_fetch(j, redo=ids)


def clean_parts(j):
    for d in glob.glob(os.path.join(PROJ, f"{j['slug']}_p*")):
        link = os.path.join(d, "media")
        if os.path.exists(link):
            subprocess.run(["cmd", "/c", "rmdir", link], capture_output=True)      # junction only, never the target
        shutil.rmtree(d, ignore_errors=True)


def s_build(j):
    clips = n_shots(j)
    parts = max(1, math.ceil(clips / PART_CLIPS))
    j["parts"] = parts
    clean_parts(j)
    stage(j, "build", status="running", pct=0, detail=f"splitting into {parts} part(s)")
    if run_proc(j, py("-m", "studio.slice", j["slug"], str(parts)), filt=lambda l: l.startswith("[slice]")):
        raise RuntimeError("Slicing failed")
    for k in range(1, parts + 1):
        name = f"{j['slug']}_p{k}"
        stage(j, "build", pct=int(100 * (k - 1) / parts), detail=f"composing scene {k}/{parts} (re-encoding clips, animations)")
        if run_proc(j, py("-m", "studio.hf_build", name), filt=lambda l: "[hf_build]" in l or "rror" in l):
            raise RuntimeError(f"Composition failed for part {k}")
        for f in glob.glob(os.path.join(ROOT, "studio", "hf_scaffold", "*")):
            shutil.copy(f, os.path.join(PROJ, name, "hf"))
    stage(j, "build", pct=100)


def s_render(j):
    parts = j["parts"]
    npx = shutil.which("npx.cmd") or "npx.cmd"
    for k in range(1, parts + 1):
        name = f"{j['slug']}_p{k}"
        out = os.path.join(PROJ, name, "out"); os.makedirs(out, exist_ok=True)
        if os.path.exists(os.path.join(out, "part.mp4")):
            continue
        hf = os.path.join(PROJ, name, "hf"); rlog = os.path.join(hf, "render.log")
        if os.path.exists(rlog):
            os.remove(rlog)

        def poll(k=k, rlog=rlog):
            try:
                t = open(rlog, encoding="utf-8", errors="replace").read()[-4000:].replace("\r", "\n")
            except Exception:
                return
            m = re.findall(r"(\d+)%\s+([A-Za-z ]+?)\s*(\d+/\d+)?\s*$", t, re.M)
            if m:
                pct, what, fr = m[-1]
                stage(j, "render", pct=int(100 * ((k - 1) + int(pct) / 100) / parts),
                      detail=f"part {k}/{parts}: {what.strip()} {fr}".strip())
        stage(j, "render", status="running", detail=f"part {k}/{parts}: starting")
        with open(rlog, "w", encoding="utf-8") as lf:
            p = subprocess.Popen([npx, "--prefix", HF_PREFIX, "hyperframes", "render", "-o", os.path.join(out, "part.mp4"), "-q", "draft"],
                                 cwd=hf, env=env(), stdout=lf, stderr=subprocess.STDOUT, creationflags=0x08000000)
        RT[j["id"]]["proc"] = p
        while p.poll() is None:
            if j.get("cancel"):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True); raise Cancelled()
            poll(); time.sleep(4)
        if not os.path.exists(os.path.join(out, "part.mp4")):
            raise RuntimeError(f"Render failed for part {k} (see {name}/hf/render.log)")
        log(j, f"[render] part {k}/{parts} done")
    stage(j, "render", pct=100)


def s_join(j):
    parts = j["parts"]
    out_dir = os.path.join(pdir(j), "out"); os.makedirs(out_dir, exist_ok=True)
    lst = os.path.join(out_dir, "concat.txt")
    open(lst, "w", encoding="ascii").write("\n".join(
        "file '" + os.path.join(PROJ, f"{j['slug']}_p{k}", "out", "part.mp4").replace("\\", "/") + "'" for k in range(1, parts + 1)))
    final = os.path.join(out_dir, f"{j['slug']}.mp4")
    if run_proc(j, ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", final]) or not os.path.exists(final):
        raise RuntimeError("Joining parts failed")
    j["video"] = f"{j['slug']}/out/{j['slug']}.mp4"
    credits(j)


def credits(j):
    reg = load_json(os.path.join(pdir(j), "sources.json"), {})
    rows = ["# Credits (Creative Commons via YouTube / Wikimedia)\n", "| Shot | Title | Channel | Link |", "|---|---|---|---|"]
    for k, v in sorted(reg.items(), key=lambda x: int(x[0])):
        if v.get("url"):
            rows.append(f"| {k} | {v.get('title','')} | {v.get('channel') or v.get('author','')} | {v['url']} |")
    open(os.path.join(pdir(j), "CREDITS.md"), "w", encoding="utf-8").write("\n".join(rows))


RUN = {"transcribe": s_transcribe, "plan": s_plan, "fetch": s_fetch, "review": s_review,
       "build": s_build, "render": s_render, "join": s_join}


def pipeline(j):
    try:
        j["status"] = "running"; j.pop("error", None); j["cancel"] = False
        from studio.preflight import run as _preflight
        _errs, _warns = _preflight()
        for w in _warns:
            log(j, f"[preflight] warning: {w}")
        if _errs:
            raise RuntimeError("Preflight failed: " + " | ".join(_errs))
        for key, _ in STAGES[1:]:
            if j["stages"][key]["status"] == "done":
                continue
            stage(j, key, status="running", pct=0)
            RUN[key](j)
            stage(j, key, status="done", pct=100)
        j["status"] = "done"; j["stage"] = "join"
        log(j, "All done.")
    except Cancelled:
        j["status"] = "cancelled"; log(j, "Cancelled by user")
    except Exception as e:
        j["status"] = "error"; j["error"] = str(e)
        stage(j, j["stage"], status="error", detail=str(e)); log(j, f"ERROR: {e}")
    save(j)


def worker():
    while True:
        with LOCK:
            jid = QUEUE.pop(0) if QUEUE else None
        if jid is None:
            WORKER["t"] = None
            return
        pipeline(JOBS[jid])


def enqueue(jid):
    with LOCK:
        j = JOBS[jid]
        j["status"] = "queued"; save(j)
        if jid not in QUEUE:
            QUEUE.append(jid)
        if WORKER["t"] is None or not WORKER["t"].is_alive():
            WORKER["t"] = threading.Thread(target=worker, daemon=True); WORKER["t"].start()


# ------------------------------------------------------------------ public API
def new_job(title, filename, data, options):
    jid = uuid.uuid4().hex[:8]
    base = re.sub(r"[^a-z0-9]+", "-", (title or os.path.splitext(filename)[0]).lower()).strip("-")[:28] or "video"
    slug = f"{base}-{jid[:4]}"
    j = {"id": jid, "slug": slug, "title": title or os.path.splitext(filename)[0], "created": time.time(),
         "status": "queued", "stage": "upload", "options": options,
         "stages": {k: {"label": l, "status": "pending", "pct": 0, "detail": ""} for k, l in STAGES}}
    os.makedirs(pdir(j), exist_ok=True)
    ext = os.path.splitext(filename)[1].lower() or ".mp3"
    j["audio"] = f"voice{ext}"
    open(os.path.join(pdir(j), j["audio"]), "wb").write(data)
    try:
        j["audio_seconds"] = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                                   os.path.join(pdir(j), j["audio"])], capture_output=True, text=True, env=env()).stdout.strip())
    except Exception:
        j["audio_seconds"] = None
    stage(j, "upload", status="done", pct=100, detail=f"{(len(data)/1e6):.1f} MB")
    JOBS[jid] = j; RT[jid] = {"review": threading.Event()}
    enqueue(jid)
    return j


def load_all():
    for p in glob.glob(os.path.join(PROJ, "*", "job.json")):
        j = load_json(p)
        if not j:
            continue
        if j["status"] in ("running", "queued", "review"):
            j["status"] = "interrupted"
        JOBS[j["id"]] = j; RT[j["id"]] = {"review": threading.Event()}


def view(j, full=False):
    d = {k: j.get(k) for k in ("id", "slug", "title", "created", "status", "stage", "stages", "options", "video", "error", "parts", "audio_seconds")}
    d["order"] = [k for k, _ in STAGES]
    if full:
        d["log"] = tail(j)
    return d


def shots_view(j):
    plan = load_json(os.path.join(pdir(j), "plan.json"), {"shots": []})
    reg = load_json(os.path.join(pdir(j), "sources.json"), {})
    out = []
    for s in plan["shots"]:
        r = reg.get(str(s["id"]), {})
        out.append({"id": s["id"], "start": s["start"], "must_show": s.get("must_show"), "query": r.get("query") or (s.get("queries") or [""])[0],
                    "title": r.get("title"), "url": r.get("url"), "ok": bool(r.get("file")),
                    "thumb": f"{j['slug']}/_thumbs/{s['id']}.jpg" if r.get("file") else None,
                    "overlays": [(o.get("text") or o.get("label") or o.get("kicker") or "") for o in s.get("overlays", [])]})
    return out
