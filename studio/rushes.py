"""Precise rushes for niche subjects: work from WHOLE real films instead of random search hits.

Generic search finds the wrong boat/car/brand, presenters, subtitles, slides and clips with hidden cuts. What works
(Bering 65 video, 2026-10-09): download a handful of real subject films whole, catalogue every clean camera take, look
at it, and place exact moments on each narration line.

  python -m studio.rushes download <slug> <youtube_id>:<name> [...]   whole films -> projects/<slug>/pool/<name>.mp4
  python -m studio.rushes images   <slug> <urls.json>                 {"group": [url, ...]} -> pool/<group>_<n>.jpg + contact sheet
  python -m studio.rushes strips   <slug> <name> [step_s]             one frame every step s -> pool/strips/<name>_N.jpg
  python -m studio.rushes catalog  <slug> [name ...]                  clean single takes (no cut inside, no big face, not dark)
                                                                       -> pool/cat/cat_NN.jpg sheets + segments.json
  python -m studio.rushes place    <slug> <picks.json>                cut the picked moments into the shots (sources.json + media)
  python -m studio.rushes review   <slug> [id,id,...]                 3 frames per shot (start / middle / end) -> rv/rv_N.jpg

picks.json: {"<shot id>": {"film": "<pool name>", "from": 123.4, "crop": "<optional ffmpeg crop filter,>", "title": "...",
                          "url": "https://www.youtube.com/watch?v=..."}  or  {"image": "<pool image file>", "url": "..."}}
Every pick is a real moment you LOOKED at in the catalog/strip sheets. After placing: run studio.clean_cuts, then review.
"""
import csv, io, json, os, re, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VF = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,format=yuv420p"


def P(slug, *a):
    return os.path.join(ROOT, "projects", slug, *a)


def _dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


# ------------------------------------------------------------------------------------------------ download whole films
def download(slug, specs, height=1080):
    try:
        import truststore; truststore.inject_into_ssl()
    except ImportError:
        pass
    import yt_dlp
    pool = P(slug, "pool"); os.makedirs(pool, exist_ok=True)
    reg_p = os.path.join(pool, "films.json")
    reg = json.load(open(reg_p, encoding="utf-8")) if os.path.exists(reg_p) else {}
    for spec in specs:
        vid, name = spec.split(":", 1) if ":" in spec else (spec, spec)
        if os.path.exists(os.path.join(pool, name + ".mp4")):
            print(name, "already in pool"); continue
        o = {"quiet": True, "no_warnings": True, "noprogress": True, "cookiefile": os.path.join(ROOT, "cookies.txt"),
             "outtmpl": os.path.join(pool, name + ".%(ext)s"), "merge_output_format": "mp4",
             "format": f"bv*[height<={height}][ext=mp4]/bv*[height<={height}]"}
        try:
            with yt_dlp.YoutubeDL(o) as y:
                i = y.extract_info("https://www.youtube.com/watch?v=" + vid)
            reg[name] = {"id": vid, "title": i.get("title", ""), "channel": i.get("channel", ""), "url": "https://www.youtube.com/watch?v=" + vid}
            print(name, int(i.get("duration") or 0), "s", i.get("height"), "p -", i.get("title", "")[:60], flush=True)
        except Exception as e:
            print(name, "FAILED", str(e)[:120], flush=True)
        json.dump(reg, open(reg_p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        time.sleep(10)                                   # YouTube rate limits: keep downloads apart


# ------------------------------------------------------------------------------------------------ real photos
def images(slug, urls_json, min_w=700):
    try:
        import truststore; truststore.inject_into_ssl()
    except ImportError:
        pass
    import requests
    from PIL import Image, ImageDraw
    pool = P(slug, "pool"); os.makedirs(pool, exist_ok=True)
    U = json.load(open(urls_json, encoding="utf-8"))
    jobs = [(k, i, u) for k, v in U.items() for i, u in enumerate(v)]

    def get(j):
        k, i, u = j
        try:
            b = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            im = Image.open(io.BytesIO(b.content)).convert("RGB")
            if im.width < min_w:
                return None
            f = f"{k}_{i}.jpg"; im.save(os.path.join(pool, f), quality=92)
            return [k, i, f, list(im.size), u]
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        res = [r for r in ex.map(get, jobs) if r]
    json.dump(res, open(os.path.join(pool, "img_index.json"), "w"), indent=0)
    rows = list(U); cw, ch = 300, 170; cols = max(len(v) for v in U.values())
    sheet = Image.new("RGB", (cols * cw + 110, len(rows) * ch)); d = ImageDraw.Draw(sheet)
    for y, k in enumerate(rows):
        d.text((2, y * ch + 70), k[:16], fill=(255, 220, 0))
        for r in [r for r in res if r[0] == k]:
            im = Image.open(os.path.join(pool, r[2])); im.thumbnail((cw - 6, ch - 16)); x = 110 + r[1] * cw
            sheet.paste(im, (x, y * ch + 14)); d.text((x, y * ch + 1), f"{r[2]} {r[3][0]}x{r[3][1]}", fill=(0, 255, 255))
    sheet.save(os.path.join(pool, "_img_sheet.jpg"), quality=80)
    print(len(res), "images ->", os.path.join(pool, "_img_sheet.jpg"), "(look at it: reject wrong subject, watermarks, renders)")


# ------------------------------------------------------------------------------------------------ frame strips
def strips(slug, name, step=4.0):
    from PIL import Image, ImageDraw
    src = P(slug, "pool", name + ".mp4"); out = P(slug, "pool", "strips"); os.makedirs(out, exist_ok=True)
    td = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps=1/{step},scale=240:-2", os.path.join(td, "f%05d.jpg")], check=True)
    fs = sorted(os.listdir(td)); cols, per = 10, 12
    w, h = Image.open(os.path.join(td, fs[0])).size; rows = (len(fs) + cols - 1) // cols
    for p in range(0, rows, per):
        n = min(per, rows - p); sh = Image.new("RGB", (cols * w, n * (h + 14))); d = ImageDraw.Draw(sh)
        for i, f in enumerate(fs[p * cols:(p + n) * cols]):
            x, y = (i % cols) * w, (i // cols) * (h + 14)
            sh.paste(Image.open(os.path.join(td, f)), (x, y + 14)); d.text((x + 2, y), f"{(p * cols + i) * step:.0f}", fill=(255, 255, 0))
        sh.save(os.path.join(out, f"{name}_{p // per}.jpg"), quality=75)
    shutil.rmtree(td, ignore_errors=True)
    print(name, len(fs), "frames ->", out)


# ------------------------------------------------------------------------------------------------ clean-take catalog
def catalog(slug, names=None, min_len=3.2):
    """Split every pool film at its own cuts, keep takes >= min_len s without a big face (presenter / interview) and not dark,
    and draw sheets labelled  <index>  <film> <start>-<end>  so exact moments can be picked."""
    import cv2
    from PIL import Image, ImageDraw
    pool = P(slug, "pool"); out = os.path.join(pool, "cat"); os.makedirs(out, exist_ok=True)
    names = names or sorted(f[:-4] for f in os.listdir(pool) if f.endswith(".mp4"))
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cache_p = os.path.join(out, "cuts.json")
    C = json.load(open(cache_p)) if os.path.exists(cache_p) else {}

    def cuts(name):
        src = os.path.join(pool, name + ".mp4")
        p = subprocess.run(["ffmpeg", "-hide_banner", "-i", src, "-vf", "scale=320:-2,select='gt(scene,0.22)',showinfo", "-an", "-f", "null", "-"],
                           capture_output=True, text=True, errors="replace")
        return name, [float(m) for m in re.findall(r"pts_time:([\d.]+)", p.stderr)], _dur(src)
    with ThreadPoolExecutor(4) as ex:
        for name, ts, d in ex.map(cuts, [n for n in names if n not in C]):
            C[name] = {"cuts": ts, "dur": d}; print(name, len(ts), "cuts", flush=True)
    json.dump(C, open(cache_p, "w"))
    segs = []
    for name in names:
        b = [0.0] + C[name]["cuts"] + [C[name]["dur"]]
        segs += [{"film": name, "a": round(a + 0.25, 2), "e": round(e - 0.25, 2)} for a, e in zip(b, b[1:]) if e - a - 0.5 >= min_len]

    def work(i_s):
        i, s = i_s
        src = os.path.join(pool, s["film"] + ".mp4"); face = luma = 0
        for j, frac in enumerate((0.3, 0.75)):
            pth = os.path.join(out, f"t{i}_{j}.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['a'] + (s['e'] - s['a']) * frac:.2f}", "-i", src, "-frames:v", "1",
                            "-vf", "scale=240:-2", pth])
            if os.path.exists(pth):
                g = cv2.cvtColor(cv2.imread(pth), cv2.COLOR_BGR2GRAY); luma += g.mean() / 2
                face = max(face, max([w for (_, _, w, _) in casc.detectMultiScale(g, 1.1, 5, minSize=(28, 28))], default=0))
        s.update(i=i, face=int(face), luma=round(luma, 1))
        return s
    with ThreadPoolExecutor(8) as ex:
        segs = list(ex.map(work, enumerate(segs)))
    json.dump(segs, open(os.path.join(out, "segments.json"), "w"), indent=0)
    keep = [s for s in segs if s["face"] < 40 and s["luma"] > 25]
    TW, TH, cols, per = 240, 135, 4, 48
    for p in range(0, len(keep), per):
        chunk = keep[p:p + per]; rows = (len(chunk) + cols - 1) // cols
        sh = Image.new("RGB", (cols * (2 * TW + 6), rows * (TH + 15)), (18, 18, 18)); d = ImageDraw.Draw(sh)
        for k, s in enumerate(chunk):
            x, y = (k % cols) * (2 * TW + 6), (k // cols) * (TH + 15)
            d.text((x + 2, y + 1), f"{s['i']}  {s['film'][:14]} {s['a']:.1f}-{s['e']:.1f} ({s['e'] - s['a']:.1f}s)", fill=(200, 255, 61))
            for j in range(2):
                f = os.path.join(out, f"t{s['i']}_{j}.jpg")
                if os.path.exists(f):
                    sh.paste(Image.open(f).resize((TW, TH)), (x + j * TW, y + 15))
        sh.save(os.path.join(out, f"cat_{p // per:02d}.jpg"), quality=78)
    print(f"{len(segs)} takes, {len(keep)} usable (no big face, not dark) -> {out}\\cat_NN.jpg")


# ------------------------------------------------------------------------------------------------ place picks
def place(slug, picks_json, tail=1.5):
    """Cut each picked moment into its shot: clip length = shot length + tail (transitions / 0.3 s media start)."""
    plan = json.load(open(P(slug, "plan.json"), encoding="utf-8"))
    total = json.load(open(P(slug, "words.json"), encoding="utf-8"))["duration"] + 0.4
    reg_p = P(slug, "sources.json"); reg = json.load(open(reg_p, encoding="utf-8")) if os.path.exists(reg_p) else {}
    films = json.load(open(P(slug, "pool", "films.json"), encoding="utf-8")) if os.path.exists(P(slug, "pool", "films.json")) else {}
    idx = {r[2]: r[4] for r in json.load(open(P(slug, "pool", "img_index.json")))} if os.path.exists(P(slug, "pool", "img_index.json")) else {}
    S = plan["shots"]; by_id = {str(s["id"]): k for k, s in enumerate(S)}
    os.makedirs(P(slug, "media"), exist_ok=True)
    for sid, pk in json.load(open(picks_json, encoding="utf-8")).items():
        k = by_id[str(sid)]; s = S[k]
        end = S[k + 1]["start"] if k + 1 < len(S) else total
        for f in os.listdir(P(slug, "media")):
            if f.startswith(f"shot_{sid}."):
                os.remove(P(slug, "media", f))
        if "image" in pk:
            dst = f"media/shot_{sid}.jpg"; shutil.copy(P(slug, "pool", pk["image"]), P(slug, dst))
            reg[str(sid)] = {"platform": "web-image", "kind": "image", "file": dst, "from": 0, "to": 0, "title": pk.get("title", pk["image"]),
                             "url": pk.get("url") or idx.get(pk["image"], ""), "query": "hand-picked"}
            s["kind"] = "image"
            continue
        name = pk["film"]; st = float(pk["from"]); dur = end - s["start"] + tail; crop = pk.get("crop", "")
        dst = f"media/shot_{sid}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{st:.2f}", "-i", P(slug, "pool", name + ".mp4"), "-t", f"{dur:.2f}", "-an",
                        "-vf", crop + VF, "-c:v", "libx264", "-crf", "18", "-preset", "fast", P(slug, dst)], check=True)
        f = films.get(name, {})
        reg[str(sid)] = {"platform": "youtube", "id": f.get("id", ""), "title": pk.get("title") or f.get("title", name),
                         "channel": f.get("channel", ""), "url": pk.get("url") or f.get("url", ""), "license": "any (hand-cut)",
                         "file": dst, "from": st, "to": st + dur, "kind": "video", "query": "hand-cut", "pool_src": name, "crop": crop}
        s["kind"] = "video"
        print(f"shot {sid}: {name} @ {st:.1f}s ({dur:.1f}s)")
    json.dump(reg, open(reg_p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(plan, open(P(slug, "plan.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("placed. Next: python -m studio.clean_cuts", slug, "--apply  then  python -m studio.rushes review", slug)


# ------------------------------------------------------------------------------------------------ review sheets
def review(slug, ids=None):
    """Three frames per shot (0.35 s in, middle, end): a presenter, subtitle or cut that appears only mid-shot is caught."""
    from PIL import Image, ImageDraw
    plan = json.load(open(P(slug, "plan.json"), encoding="utf-8"))
    reg = json.load(open(P(slug, "sources.json"), encoding="utf-8"))
    S = plan["shots"]; total = json.load(open(P(slug, "words.json"), encoding="utf-8"))["duration"] + 0.4
    for a, b in zip(S, S[1:]):
        a["end"] = b["start"]
    S[-1]["end"] = total
    want = {int(x) for x in ids.split(",")} if ids else None
    td = tempfile.mkdtemp(); TW, TH = 256, 144

    def frames(s):
        r = reg.get(str(s["id"]))
        if not r or not r.get("file") or not os.path.exists(P(slug, r["file"])):
            return s, None
        f = P(slug, r["file"]); d = s["end"] - s["start"]
        if f.lower().endswith((".jpg", ".png")):
            im = Image.open(f).convert("RGB"); im.thumbnail((TW, TH)); return s, [im]
        out = []
        for k, t in enumerate([0.35, 0.3 + d / 2, 0.3 + d - 0.1]):
            pth = os.path.join(td, f"{s['id']}_{k}.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", f, "-frames:v", "1", "-vf", f"scale={TW}:{TH}", pth])
            out.append(Image.open(pth).convert("RGB") if os.path.exists(pth) else Image.new("RGB", (TW, TH), (255, 0, 0)))
        return s, out
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(frames, [s for s in S if want is None or s["id"] in want]))
    os.makedirs(P(slug, "rv"), exist_ok=True)
    for f in os.listdir(P(slug, "rv")):
        os.remove(P(slug, "rv", f))
    per, cols, cw = 24, 2, 3 * TW + 8
    for p in range(0, len(res), per):
        chunk = res[p:p + per]; rows = (len(chunk) + cols - 1) // cols
        sh = Image.new("RGB", (cols * cw, rows * (TH + 16)), (20, 20, 20)); d = ImageDraw.Draw(sh)
        for i, (s, ims) in enumerate(chunk):
            x, y = (i % cols) * cw, (i // cols) * (TH + 16); r = reg.get(str(s["id"]), {})
            d.text((x + 2, y + 2), f"#{s['id']} {s['start']:.0f}s {'T ' if s.get('template') else ''}{r.get('pool_src') or r.get('title', '')[:18]} "
                                   f"{r.get('from', 0):.0f} | {s.get('must_show', '')[:28]}", fill=(200, 255, 61))
            for k, im in enumerate(ims or []):
                sh.paste(im, (x + k * TW, y + 16))
        sh.save(P(slug, "rv", f"rv_{p // per}.jpg"), quality=80)
    shutil.rmtree(td, ignore_errors=True)
    print((len(res) + per - 1) // per, "sheets ->", P(slug, "rv"), "(look at EVERY frame)")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__); sys.exit()
    cmd, slug = a[0], a[1]
    if cmd == "download":
        download(slug, a[2:])
    elif cmd == "images":
        images(slug, a[2])
    elif cmd == "strips":
        strips(slug, a[2], float(a[3]) if len(a) > 3 else 4.0)
    elif cmd == "catalog":
        catalog(slug, a[2:] or None)
    elif cmd == "place":
        place(slug, a[2])
    elif cmd == "review":
        review(slug, a[2] if len(a) > 2 else None)
    else:
        print(__doc__)
