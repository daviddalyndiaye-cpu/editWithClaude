"""Step 3: plan.json -> projects/<slug>/media/shot_<id>.* + sources.json + contact sheets.

Sources: YouTube (Creative Commons filter only) and Wikimedia Commons. Every download is
re-measured (resolution / aspect) and recorded for credits. Contact sheets are for a human
(or Claude) to LOOK at before building - roughly 1 in 5 automatic picks is off-topic.
"""
import json, os, re, subprocess, sys, shutil, random, time
import truststore; truststore.inject_into_ssl()
import requests

CC_FILTER = "EgIwAQ%253D%253D"  # YouTube search filter: Creative Commons
MAX_USES_PER_VIDEO = 6
# User-approved (2026-10-02): reuse the Chrome login so YouTube stops answering "confirm you're not a bot".
# Set FETCH_COOKIES_BROWSER="" to disable.
COOKIES_BROWSER = os.environ.get("FETCH_COOKIES_BROWSER", "chrome")


def _yt_base():
    o = {"quiet": True, "no_warnings": True, "sleep_requests": 3.0, "sleep_interval": 8, "max_sleep_interval": 16,
         "retries": 1, "extractor_retries": 1}
    if os.path.exists("cookies.txt"):            # exported by the user (most reliable on Windows)
        o["cookiefile"] = "cookies.txt"
    elif COOKIES_BROWSER:
        o["cookiesfrombrowser"] = (COOKIES_BROWSER,)
    return o


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True).stdout
    d = json.loads(out or "{}")
    s = (d.get("streams") or [{}])[0]
    return s.get("width", 0), s.get("height", 0), float((d.get("format") or {}).get("duration") or 0)


def yt_candidates(query, min_dur, limit=8, cc=True):
    """cc=False (plan "any_license": true) searches all of YouTube; reviews/walkthroughs are then allowed because
    for a niche subject they are the only footage (talking heads are still rejected frame by frame)."""
    import yt_dlp
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}" + (f"&sp={CC_FILTER}" if cc else "")
    with yt_dlp.YoutubeDL({**_yt_base(), "extract_flat": True, "playlistend": limit}) as y:
        info = y.extract_info(url, download=False)
    bad = ("vlog", "reaction", "tiktok", "tutorial", "how to", "explained", "review", "episode", "interview",
           "podcast", "conference", "forum", "unboxing", "tips", "q&a", "live", "lesson", "course", "documentary", "talk", "pakistan", "restores", "restoration", "infoku", "how it works", "making")
    good = ("footage", "b-roll", "broll", "drone", "timelapse", "time-lapse", "4k", "cinematic", "aerial", "stock")
    if not cc:
        bad = ("reaction", "tiktok", "podcast", "shorts", "#shorts", "live")
    out = [e for e in (info or {}).get("entries", [])
           if e.get("id") and min_dur + 6 <= (e.get("duration") or 0) <= 3600
           and not any(b in (e.get("title") or "").lower() for b in bad)]
    out.sort(key=lambda e: -sum(g in (e.get("title") or "").lower() for g in good))
    return out


def yt_download(vid, dest, start, dur):
    import yt_dlp
    opts = {
        **_yt_base(), "overwrites": True, "outtmpl": dest,
        "format": "bv*[height>=720][ext=mp4]+ba[ext=m4a]/b[height>=720][ext=mp4]/bv*[height>=720]+ba/b[height>=720]",
        "merge_output_format": "mp4",
        "download_ranges": yt_dlp.utils.download_range_func(None, [(start, start + dur)]),
        "force_keyframes_at_cuts": True,
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
    return info


def wiki_image(query, dest):
    """Largest usable Commons image for the query. Returns metadata or None."""
    r = requests.get("https://commons.wikimedia.org/w/api.php", params={
        "action": "query", "generator": "search", "gsrsearch": query, "gsrnamespace": 6,
        "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|size|extmetadata",
        "iiurlwidth": 2560, "format": "json"},
        headers={"User-Agent": "editWithClaude/1.0"}, timeout=30).json()
    for page in (r.get("query", {}).get("pages", {}) or {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url or not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
            continue
        if ii.get("width", 0) < 1600:
            continue
        _qw = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
        _title = (page.get("title") or "").lower() + " " + str((ii.get("extmetadata", {}).get("ImageDescription") or {}).get("value", "")).lower()
        if _qw and sum(w in _title for w in _qw) < min(2, len(_qw)):
            continue                                        # loose keyword match -> not the subject, skip
        if (page.get("title") or "").lower().endswith((".pdf", ".djvu", ".tif", ".tiff")):
            continue
        data = requests.get(url, headers={"User-Agent": "editWithClaude/1.0"}, timeout=60).content
        open(dest, "wb").write(data)
        meta = ii.get("extmetadata", {})
        return {"title": page.get("title"), "url": ii.get("descriptionurl"),
                "license": (meta.get("LicenseShortName") or {}).get("value", ""),
                "author": (meta.get("Artist") or {}).get("value", "")}
    return None


CHROME = os.path.expanduser(r"~\.cache\hyperframes\chrome\chrome-headless-shell")


def pick_starts(total, dur, taken):
    """Start offsets inside the BODY of a video (skip intro/outro where talking heads and slates live),
    best-first (middle of the video), avoiding passages already used by other shots."""
    long_video = total >= 90
    lo = min(25.0, total * 0.15) if long_video else 3.0
    hi = total - dur - (max(15.0, total * 0.1) if long_video else 2.0)
    if hi < lo:
        return []
    cands = [lo + (hi - lo) * k / 3 for k in range(4)]
    cands.sort(key=lambda s: abs(s - (lo + hi) / 2))
    return [s for s in cands if not any(s < b + 2 and s + dur > a - 2 for a, b in taken)]


_GENERIC = set("stock footage 4k drone b-roll broll no copyright free video hd cinematic aerial shot close up view of the a an in on at and with".split())


def title_relevant(query, title):
    """The clip's title must share at least one meaningful word with the query (kills 'village drone view' for 'trawler')."""
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) > 2 and w not in _GENERIC]
    if not words:
        return True
    t = (title or "").lower()
    return any(w in t or w.rstrip("s") in t for w in words)


_FACE = {}


def has_talking_head(path):
    """True if a large frontal face shows in any of 3 sampled frames (vlogger / presenter / interview)."""
    import cv2
    if "c" not in _FACE:
        _FACE["c"] = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    w, h, d = _probe(path)
    tmp = path + ".chk.jpg"
    try:
        for frac in (0.12, 0.5, 0.88):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(d * frac, 0.2):.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=640:-1", tmp], capture_output=True)
            img = cv2.imread(tmp)
            if img is None:
                continue
            faces = _FACE["c"].detectMultiScale(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 1.1, 6, minSize=(48, 48))
            if any(fw > 0.09 * img.shape[1] for (_, _, fw, _) in faces):
                return True
        return False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def web_screenshot(url, dest, height=1080):
    """Full-HD screenshot of a web page with headless Chrome. Returns metadata or None."""
    import glob as _g
    exe = (_g.glob(os.path.join(CHROME, "*", "*", "chrome-headless-shell.exe")) or [None])[0]
    if not exe:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code != 200:
            return None
    except Exception:
        return None
    subprocess.run([exe, "--headless", "--disable-gpu", "--hide-scrollbars", f"--screenshot={os.path.abspath(dest)}",
                    f"--window-size=1920,{height}", "--virtual-time-budget=6000", url], capture_output=True, timeout=60)
    if not os.path.exists(dest) or os.path.getsize(dest) < 20000:
        return None
    return {"title": url, "url": url, "license": "web screenshot", "author": ""}


_YACHT_RE = re.compile(r"(yacht|trawler|boat|vessel|cruiser|passagemaker|explorer|\b\d{2}\b)", re.I)
_DISTRICT_RE = re.compile(r"(station|s-tog|\btog\b|metro|copenhagen|k.benhavn|denmark|bicycle|bike|school|bus line|teglholmen|manhole|apartment|building|construction|aberdeen)", re.I)


def photo_subject_ok(subject, title, tags=""):
    """A photo only counts if it shows the SUBJECT itself, not a namesake (Nordhavn is also a Copenhagen district)."""
    t = f"{title} {tags}".lower()
    s = (subject or "").lower().split(" ")[0]
    if not s or s not in t:
        return False
    if _DISTRICT_RE.search(t):
        return False
    return bool(_YACHT_RE.search(t.replace(s, " ")))


def openverse_image(query, dest, min_w=900, exclude=None, subject=None):
    """Real photo from Openverse (Flickr, Wikimedia...). Commercial use OK; 'no derivatives' licences are skipped
    because we crop and zoom. Returns metadata (with credit info) or None."""
    try:
        r = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": query, "license_type": "commercial", "page_size": 20},
                         headers={"User-Agent": "editWithClaude/1.0"}, timeout=25)
        if r.status_code != 200:
            return None
        q_words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
        for it in r.json().get("results", []):
            lic = (it.get("license") or "").lower()
            if "nd" in lic.split("-") or (it.get("width") or 0) < min_w:
                continue
            text = f"{it.get('title','')} {' '.join(t.get('name','') for t in it.get('tags') or [])}".lower()
            if q_words and sum(w in text for w in q_words) < min(2, len(q_words)):   # >=2 query words must really appear
                continue
            if subject and not photo_subject_ok(subject, it.get("title") or "", " ".join(t.get("name", "") for t in it.get("tags") or [])):
                continue
            url = it.get("url")
            if not url or (exclude and (it.get("foreign_landing_url") or url) in exclude):
                continue
            try:
                data = requests.get(url, headers={"User-Agent": "editWithClaude/1.0"}, timeout=40).content
            except Exception:
                continue
            if len(data) < 60_000:
                continue
            open(dest, "wb").write(data)
            return {"title": it.get("title"), "url": it.get("foreign_landing_url") or url,
                    "license": f"CC {lic.upper()}", "author": it.get("creator") or ""}
    except Exception:
        return None
    return None


STOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library", "stock")
_STOCK_STOP = {"footage", "broll", "b-roll", "drone", "stock", "video", "clip", "shot", "the", "and", "with", "of", "a", "on", "in"}


def local_stock(shot, dest, dur, used_stock):
    """Fallback: a clip from library/stock whose keywords overlap the shot's searches (stock.json, tools/import_stock.py).
    Needs >= 2 matching words (or 1 for a one-word query); each library clip is used at most twice per video."""
    try:
        idx = json.load(open(os.path.join(STOCK_DIR, "stock.json")))
    except Exception:
        return None
    toks = set()
    for q in shot.get("queries", []) + [shot.get("must_show") or ""]:
        toks |= {t for t in re.findall(r"[a-z]+", q.lower()) if len(t) > 2 and t not in _STOCK_STOP}
    best, score = None, 0
    for it in idx:
        if used_stock.get(it["file"], 0) >= 2:
            continue
        sc = len(toks & set(it.get("words", [])))
        if sc > score:
            best, score = it, sc
    if not best or score < (1 if len(toks) <= 2 else 2):
        return None
    src = os.path.join(STOCK_DIR, best["file"])
    w, h, d = _probe(src)
    start = 0.0 if not used_stock.get(best["file"]) else max(0.0, d - dur)      # second use: take the other end
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", src, "-t", f"{dur:.2f}", "-c", "copy", dest], check=True)
    used_stock[best["file"]] = used_stock.get(best["file"], 0) + 1
    return {"platform": "library", "title": best["file"], "kind": "video", "from": start, "to": start + dur, "query": " ".join(sorted(toks))[:80]}


def web_image(query, dest, subject=None, exclude=None, min_w=1000):
    """Any-license photo from a web image search (plan "any_license": true). Landscape, >= min_w px,
    and the result title must name the subject."""
    from PIL import Image
    import html as _h
    try:
        r = requests.get("https://www.bing.com/images/search", params={"q": query, "qft": "+filterui:imagesize-large", "form": "IRFLTR"},
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}, timeout=30)
    except Exception:
        return None
    subj = (subject or "").lower().split(" ")[0]
    for m in re.finditer(r'm="(\{[^"]+\})"', r.text):
        try:
            meta = json.loads(_h.unescape(m.group(1)))
        except Exception:
            continue
        url, title, page = meta.get("murl"), meta.get("t") or "", meta.get("purl") or ""
        if not url or (exclude and url in exclude):
            continue
        if subj and subj not in (title + " " + page + " " + url).lower():
            continue
        try:
            b = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            if b.status_code != 200 or len(b.content) < 40000:
                continue
            import io as _io
            with Image.open(_io.BytesIO(b.content)) as im:       # decode in memory: no open file handle on Windows
                w, h = im.size
                if w < min_w or w / max(h, 1) < 1.2:
                    continue
                im.convert("RGB").save(dest, "JPEG", quality=92)
        except Exception:
            if os.path.exists(dest):
                os.remove(dest)
            continue
        return {"title": title[:120], "url": url, "page": page, "author": page.split("/")[2] if page.count("/") > 2 else "", "license": "unknown (any-license mode)"}
    return None


def fetch(slug, redo=None):
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    total = json.load(open(os.path.join(root, "words.json"), encoding="utf-8"))["duration"] + 0.5
    shots_ = plan["shots"]
    for a, b in zip(shots_, shots_[1:]):
        a["end"] = b["start"]
    shots_[-1]["end"] = total
    media = os.path.join(root, "media")
    os.makedirs(media, exist_ok=True)
    reg_path = os.path.join(root, "sources.json")
    reg = json.load(open(reg_path, encoding="utf-8")) if os.path.exists(reg_path) else {}
    used = {}  # video id -> [(start,end)]
    for sid, s in reg.items():
        if s.get("platform") == "youtube":
            used.setdefault(s["id"], []).append((s["from"], s["to"]))

    used_photos = {v.get("url") for v in reg.values() if v.get("kind") == "image"}
    used_stock = {}
    for v in reg.values():
        if v.get("platform") == "library":
            used_stock[v["title"]] = used_stock.get(v["title"], 0) + 1
    subj_word = (plan.get("subject") or "").strip().lower().split(" ")[0]
    photo_every = plan.get("photo_every", 3)
    any_lic = plan.get("any_license", False)

    for si, shot in enumerate(plan["shots"]):
        sid = str(shot["id"])
        if shot["kind"] == "card":
            continue
        if redo is not None and int(sid) not in redo:
            if sid in reg:
                continue
        elif redo is None and sid in reg and reg[sid].get("file") and os.path.exists(os.path.join(root, reg[sid]["file"])):
            continue
        if redo is not None and sid in reg:
            s_old = reg.pop(sid)
            shot.setdefault('avoid', []).append(s_old.get('id'))
            used[s_old.get("id")] = [u for u in used.get(s_old.get("id"), []) if u != (s_old["from"], s_old["to"])]

        dur = shot["end"] - shot["start"] + 1.5
        done = False
        if shot["kind"] == "screenshot":
            dest = os.path.join(media, f"shot_{sid}.png")
            print(f"[fetch] shot {sid}: screenshot {shot.get('url')}")
            meta = web_screenshot(shot.get("url", ""), dest)
            if meta:
                reg[sid] = {"platform": "web", **meta, "file": f"media/shot_{sid}.png", "from": 0, "to": 0,
                            "kind": "image", "query": shot.get("url")}
                print("   OK screenshot"); done = True
            elif shot.get("queries"):
                shot["kind"] = "image"                       # fall back to a Commons image
        # every Nth subject-specific shot gets a REAL PHOTO of the subject (also saves YouTube requests)
        if (not done and shot["kind"] == "video" and photo_every and subj_word and si % photo_every == 1
                and shot.get("queries") and subj_word in shot["queries"][0].lower()):
            base_q = [x for x in shot["queries"][:2] if subj_word in x.lower()][0]
            toks = [t for t in re.split(r"\W+", base_q) if t]
            step = [base_q] + ([" ".join(toks[:2])] if len(toks) > 2 else [])
            for q in dict.fromkeys(step):
                dest = os.path.join(media, f"shot_{sid}.jpg")
                meta = None; plat = "openverse"
                meta = openverse_image(q, dest, exclude=used_photos, subject=plan.get("subject"))
                if not meta and any_lic:
                    meta = web_image(q, dest, subject=plan.get("subject"), exclude=used_photos); plat = "web-image"
                if not meta:
                    try:
                        meta = wiki_image(q, dest); plat = "wikimedia"
                    except Exception:
                        meta = None
                    if meta and (meta.get("url") in used_photos or not photo_subject_ok(plan.get("subject"), meta.get("title") or "")):
                        meta = None
                if meta:
                    used_photos.add(meta.get("url"))
                    reg[sid] = {"platform": plat, **meta, "file": f"media/shot_{sid}.jpg", "from": 0, "to": 0,
                                "kind": "image", "query": q}
                    print(f"[fetch] shot {sid}: photo '{q}' -> {meta.get('title','')[:50]}")
                    done = True
                    break
        if shot["kind"] == "image" and not done:
            for q in ([shot.get("wiki")] if shot.get("wiki") else []) + shot.get("queries", []):
                print(f"[fetch] shot {sid}: commons image '{q}'")
                dest = os.path.join(media, f"shot_{sid}.jpg")
                try:
                    meta = wiki_image(q, dest)
                except Exception as e:
                    meta = None
                plat = "wikimedia"
                if not meta:
                    meta = openverse_image(q, dest); plat = "openverse"
                if meta:
                    reg[sid] = {"platform": plat, **meta, "file": f"media/shot_{sid}.jpg", "from": 0, "to": 0,
                                "kind": "image", "query": q}
                    print(f"   OK wiki {meta['title']}"); done = True
                    break
            if not done:
                print(f"   no usable image -> searching video footage instead")
        for q in shot.get("queries", []):
            if done:
                break
            print(f"[fetch] shot {sid}: yt '{q}'")
            time.sleep(4.0)                                   # YouTube throttles fast search bursts (returns empty lists)
            try:
                cands = yt_candidates(q, dur, cc=not (any_lic and subj_word and subj_word in q.lower()))
            except Exception as e:
                print("   search failed:", str(e)[:80]); continue
            _marine = re.compile(r"(yacht|boat|trawler|ship|marina|harbou?r|sail|ocean|sea|cruis|vessel|shipyard|explorer)", re.I)
            cands = [c for c in cands if title_relevant(q, c.get("title")) or _marine.search(c.get("title") or "")]
            subj = (plan.get("subject") or "").strip().lower().split(" ")[0]
            if subj and subj in q.lower():                      # subject query: the video itself must be about the subject
                cands = [c for c in cands if subj in (c.get("title") or "").lower()]
            for c in cands:
                vid = c["id"]
                if len(used.get(vid, [])) >= MAX_USES_PER_VIDEO or vid in shot.get("avoid", []):
                    continue
                taken = used.get(vid, [])
                total = c.get("duration") or 0
                starts = pick_starts(total, dur, taken)[:3]
                dest = os.path.join(media, f"shot_{sid}.mp4")
                for start in starts:
                    try:
                        info = yt_download(vid, dest, start, dur)
                    except Exception as e:
                        print("   download failed:", str(e)[:70]); break
                    if "creative commons" not in (info.get("license") or "").lower() and not any_lic:
                        os.remove(dest); break
                    w, h, d = _probe(dest)
                    if h < 700 or w / max(h, 1) < 1.5 or d < dur - 1:
                        print(f"   rejected {w}x{h} {d:.1f}s"); os.remove(dest); break
                    if has_talking_head(dest):
                        print(f"   talking head at {start:.0f}s -> trying another moment")
                        os.remove(dest); continue
                    reg[sid] = {"platform": "youtube", "id": vid, "title": info.get("title"),
                                "channel": info.get("uploader") or info.get("channel"),
                                "url": f"https://www.youtube.com/watch?v={vid}", "license": info.get("license"),
                                "file": f"media/shot_{sid}.mp4", "from": start, "to": start + dur, "kind": "video",
                                "query": q}
                    used.setdefault(vid, []).append((start, start + dur))
                    print(f"   OK  {info.get('title','')[:60]} @ {start:.0f}s")
                    done = True
                    break
                if done:
                    break
            if done:
                break
        if not done and (shot.get("wiki") or shot["kind"] == "image"):
            for q in ([shot.get("wiki")] if shot.get("wiki") else []) + shot.get("queries", []):
                dest = os.path.join(media, f"shot_{sid}.jpg")
                meta = wiki_image(q, dest)
                if meta:
                    reg[sid] = {"platform": "wikimedia", **meta, "file": f"media/shot_{sid}.jpg",
                                "from": 0, "to": 0, "kind": "image", "query": q}
                    print(f"   OK wiki {meta['title']}")
                    done = True
                    break
        if not done and any_lic and subj_word and any(subj_word in q.lower() for q in shot.get("queries", [])):
            for q in [x for x in shot.get("queries", []) if subj_word in x.lower()]:
                dest = os.path.join(media, f"shot_{sid}.jpg")
                meta = web_image(q, dest, subject=plan.get("subject"), exclude=used_photos)
                if meta:
                    used_photos.add(meta["url"])
                    reg[sid] = {"platform": "web-image", **meta, "file": f"media/shot_{sid}.jpg", "from": 0, "to": 0, "kind": "image", "query": q}
                    print(f"[fetch] shot {sid}: web photo '{q}' -> {meta['title'][:50]}"); done = True
                    break
        if not done:
            meta = local_stock(shot, os.path.join(media, f"shot_{sid}.mp4"), dur, used_stock)
            if meta:
                reg[sid] = {**meta, "file": f"media/shot_{sid}.mp4"}
                print(f"[fetch] shot {sid}: library clip {meta['title']}"); done = True
        if not done:
            print(f"[fetch] shot {sid}: NOTHING FOUND -> will render as card")
            reg[sid] = {"platform": "none", "file": None, "kind": "card", "from": 0, "to": 0}
        json.dump(reg, open(reg_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(reg, open(reg_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    sheets(slug)


def sheets(slug):
    """Contact sheets (6 per row) with the shot id + query printed on each thumbnail."""
    from PIL import Image, ImageDraw
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8"))
    tmp = os.path.join(root, "_thumbs"); os.makedirs(tmp, exist_ok=True)
    tiles = []
    for shot in plan["shots"]:
        sid = str(shot["id"]); s = reg.get(sid)
        if not s or not s.get("file"):
            continue
        src = os.path.join(root, s["file"]); th = os.path.join(tmp, f"{sid}.jpg")
        if s["kind"] == "video":
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2", "-i", src, "-frames:v", "1",
                            "-vf", "scale=480:270:force_original_aspect_ratio=increase,crop=480:270", th])
        else:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-frames:v", "1",
                            "-vf", "scale=480:270:force_original_aspect_ratio=increase,crop=480:270", th])
        if os.path.exists(th):
            tiles.append((sid, shot, s, th))
    per = 12
    for n in range(0, len(tiles), per):
        chunk = tiles[n:n + per]
        sheet = Image.new("RGB", (480 * 3, 310 * ((len(chunk) + 2) // 3)), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for i, (sid, shot, s, th) in enumerate(chunk):
            x, y = (i % 3) * 480, (i // 3) * 310
            sheet.paste(Image.open(th), (x, y))
            d.text((x + 4, y + 273), f"#{sid} want: {shot.get('must_show', shot.get('queries', [''])[0])[:62]}", fill=(255, 255, 0))
            d.text((x + 4, y + 291), f"got: {(s.get('title') or '')[:68]}", fill=(180, 220, 255))
        p = os.path.join(root, f"sheet_{n // per + 1}.jpg"); sheet.save(p, quality=88)
        print("[sheets]", p)


if __name__ == "__main__":
    slug = sys.argv[1]
    redo = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
    fetch(slug, redo)
