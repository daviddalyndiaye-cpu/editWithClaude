"""Make every video shot one continuous camera take: no cut, dissolve or black flash inside its visible window.

python -m studio.clean_cuts <slug> [--apply]

For each video shot the clip's visible window (shot length + transition overlap) is scanned with per-frame scene scores.
A frame scoring > HARD is a cut; DISSOLVE_N consecutive frames > SOFT is a dissolve; luma < 18 is a black frame.
 - shots hand-cut from a whole source video in pool/ (sources.json "from") are re-cut: the source is scanned once and the
   nearest clean window (searching outward from the original start, up to +-SEARCH s) is used;
 - other clips: if the clip file itself has a clean sub-window long enough, it is trimmed to it; otherwise reported.
"""
import json, os, re, subprocess, sys

HARD, SOFT, DISSOLVE_N, SEARCH = 0.28, 0.06, 6, 60.0
POOL_IDS = {}


def scores(path, t0=0.0, dur=None):
    """[(t, scene, yavg)] for every frame (t relative to t0)."""
    args = ["ffmpeg", "-v", "info", "-ss", f"{t0:.3f}"] + (["-t", f"{dur:.3f}"] if dur else []) + ["-i", path, "-an", "-vf",
            "scale=320:-2,select='gte(scene,0)',signalstats,metadata=print", "-f", "null", "-"]
    o = subprocess.run(args, capture_output=True, text=True, errors="replace").stderr
    out, cur = [], {}
    for line in o.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            if cur: out.append((cur.get("t", 0), cur.get("s", 0), cur.get("y", 128)))
            cur = {"t": float(m.group(1))}
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m: cur["s"] = float(m.group(1))
        m = re.search(r"lavfi\.signalstats\.YAVG=([\d.]+)", line)
        if m: cur["y"] = float(m.group(1))
    if cur: out.append((cur.get("t", 0), cur.get("s", 0), cur.get("y", 128)))
    return out


def bad_times(sc):
    """Times that must not be visible: hard cuts, dissolve runs, black frames."""
    bad, run = [], 0
    for i, (t, s, y) in enumerate(sc):
        if i == 0:
            continue
        run = run + 1 if s > SOFT else 0
        if s > HARD or run >= DISSOLVE_N or y < 18:
            bad.append(t)
    return bad


def clean_window(bad, start, need, lo, hi):
    """Nearest start >= lo with [start, start+need] free of bad times, searching outward from `start`."""
    step = 0.1
    for k in range(int(SEARCH / step) + 1):
        for cand in ((start + k * step), (start - k * step)):
            if cand < lo or cand + need > hi:
                continue
            if not any(cand - 0.05 <= b <= cand + need + 0.05 for b in bad):
                return round(cand, 2)
    return None


def run(slug, apply=False):
    R = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(R, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(R, "sources.json"), encoding="utf-8"))
    total = json.load(open(os.path.join(R, "words.json"), encoding="utf-8"))["duration"] + 0.4
    S = plan["shots"]
    pool = os.path.join(R, "pool")
    by_id = {}
    for f in (os.listdir(pool) if os.path.isdir(pool) else []):
        if f.endswith(".mp4"):
            by_id.setdefault(f[:-4], os.path.join(pool, f))
    vid_to_file = {}                     # youtube id -> pool file (from the cut scripts' SRC tables)
    for e in reg.values():
        if e.get("query") == "hand-cut" and e.get("id"):
            for name, path in by_id.items():
                vid_to_file.setdefault(e["id"], None)
    cache, fixed, unfixed = {}, [], []
    for i, s in enumerate(S):
        e = reg.get(str(s["id"]), {})
        if e.get("kind") != "video" or s.get("template") or not e.get("file"):
            continue
        play = (S[i + 1]["start"] if i + 1 < len(S) else total) - s["start"] + 0.45
        clip = os.path.join(R, e["file"])
        sc = scores(clip, 0.3, play)                # the renderer starts every clip 0.3 s in (data-media-start)
        if not bad_times(sc):
            continue
        src = e.get("pool_src")
        if src and not os.path.exists(src):
            src = by_id.get(src)                    # pool_src may be the bare film name
        if not src:
            for name, path in by_id.items():
                if e.get("title") and name in json.dumps(e):
                    src = path
        if src and os.path.exists(src):
            if src not in cache:
                cache[src] = bad_times(scores(src))
            dlen = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], capture_output=True, text=True).stdout or 0)
            st = clean_window(cache[src], float(e.get("from", 0)) + 0.3, play + 0.1, 0.0, dlen) if dlen else None
            if st is not None:
                if apply:
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(st - 0.3, 0):.2f}", "-i", src, "-t", f"{play + 1.0:.2f}", "-an",
                                    "-vf", e.get("crop", "") + "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,format=yuv420p",
                                    "-c:v", "libx264", "-crf", "18", "-preset", "fast", clip], check=True)
                    e["from"] = max(st - 0.3, 0)
                fixed.append((s["id"], "re-cut from source", round(st, 1))); continue
        bad = bad_times(sc)
        segs, prev = [], 0.0
        for b in bad + [sc[-1][0] if sc else 0]:
            segs.append((prev, b)); prev = b + 0.05
        best = max(segs, key=lambda x: x[1] - x[0]) if segs else (0, 0)
        if best[1] - best[0] >= play + 0.05:
            if apply:
                tmp = clip + ".tmp.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(best[0] + 0.3 - 0.3, 0):.2f}", "-i", clip, "-t", f"{play + 0.6:.2f}", "-an",
                                "-c:v", "libx264", "-crf", "18", "-preset", "fast", tmp], check=True)
                os.replace(tmp, clip)
            fixed.append((s["id"], "trimmed inside clip", round(best[0], 1)))
        else:
            unfixed.append((s["id"], round(s["start"], 1), round(best[1] - best[0], 1), round(play, 1), e.get("title", "")[:40]))
    if apply:
        json.dump(reg, open(os.path.join(R, "sources.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"[clean_cuts] fixed {len(fixed)}, still dirty {len(unfixed)}")
    for u in unfixed:
        print("   dirty:", u)
    return fixed, unfixed


if __name__ == "__main__":
    run(sys.argv[1], "--apply" in sys.argv)
