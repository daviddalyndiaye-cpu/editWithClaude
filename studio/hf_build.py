"""Step 4 (HyperFrames): plan.json + media -> projects/<slug>/hf/index.html  (then `npx hyperframes render`).

Everything animated is GSAP on a paused timeline, driven by the real word timings:
  shots (video / image with Ken-Burns / animated cards) + transitions (fade, push, zoom-through, whip)
  overlays on footage (lower-third, count-up stat, pop tag), accent wipe + flash on beats,
  word-by-word captions, vignette, SFX.
"""
import html, json, os, re, shutil, subprocess, sys, itertools, wave
from concurrent.futures import ThreadPoolExecutor

W, H = 1920, 1080
T = 0.42  # transition length (s); the incoming clip is fully in exactly at the shot's start
_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library")
SFX_DIR = os.path.join(_LIB, "sfx")
BG_DIR = os.path.join(_LIB, "bg")                 # looping backdrops (grid-dots / grid-warp / topo)
ICON_DIR = os.path.join(_LIB, "icons")             # stickers + icons.json (trigger words), see tools/import_icons.py
FX_DIR = os.path.join(_LIB, "fx")                 # burn-XX.mp4: 0.32 s film-burn / light-leak flashes (screen blend)
SFX_VOL = {"money": 0.22, "riser": 0.16, "type": 0.20, "pop": 0.32, "burn": 0.30, "film": 0.30, "glitch": 0.26, "wipe": 0.40, "tv": 0.22}
MONEY_RE = re.compile(r"[$€£]|cost|price|revenue|sales|billion|million|euro|dollar|sek|usd|profit|margin", re.I)
FONT_DISPLAY = "'Montserrat','Arial Black',sans-serif"
FONT_TEXT = "'Inter','Segoe UI',Arial,sans-serif"
MOVES = ["zoom_in", "pan_right", "zoom_out", "pan_left", "focus", "pan_up", "pan_down"]
TRANS = ["fade", "push", "zoomthru", "whip", "fade", "push"]


def esc(s):
    return html.escape(str(s), quote=True)


class Words:
    def __init__(self, words):
        self.w = words

    def find(self, term, after=0.0, before=1e9):
        term = term.lower().strip(".,!?'\"")
        for x in self.w:
            if x["s"] >= before:
                break
            if x["s"] >= after - 0.01 and x["w"].lower().strip(".,!?'\"").startswith(term):
                return x["s"]
        return None


def auto_icons(shots, words, reg, gap=12.0):
    """Pop a sticker when the narrator says one of its trigger words (library/icons/icons.json).
    At most one every `gap` s, never on cards / screenshot cards / over another overlay, no sticker repeated within 5."""
    try:
        index = json.load(open(os.path.join(ICON_DIR, "icons.json")))
    except Exception:
        return 0
    single, phrases = {}, []
    for it in index:
        for w in it["words"]:
            (phrases.append((w.lower().split(), it["file"])) if " " in w else single.setdefault(w.lower(), it["file"]))
    def match(i):
        for ph, f in phrases:
            if [x["w"].lower().strip(".,!?'\"") for x in words[i:i + len(ph)]] == ph:
                return f
        t = words[i]["w"].lower().strip(".,!?'\"")
        if t in single:
            return single[t]
        for k, f in single.items():
            if k.endswith("*") and t.startswith(k[:-1]) and len(t) >= len(k) - 1:
                return f
        return None
    last_t, recent, n = -1e9, [], 0
    si = 0
    for i, x in enumerate(words):
        t = x["s"]
        while si + 1 < len(shots) and shots[si + 1]["start"] <= t:
            si += 1
        s = shots[si]
        if t - last_t < gap or t < 2.0 or t > s["end"] - 1.6:
            continue
        r = reg.get(str(s["id"]), {})
        if s["kind"] == "card" or not r.get("file") or r.get("platform") == "web" or s.get("layout") == "inset":
            continue
        busy = any(abs((s["start"] + o.get("at", 0.8)) - t) < o.get("dur", 3.2) + 0.5 for o in s.get("overlays", []) if o["type"] != "icon")
        if busy:
            continue
        f = match(i)
        if not f or f in recent:
            continue
        s.setdefault("overlays", []).append({"type": "icon", "file": f, "at": t - s["start"], "dur": 2.4})
        last_t = t; recent = (recent + [f])[-5:]; n += 1
    return n


def motion_js(sel, kind, start, dur):
    """Visible (12-20%) motion on a media clip; transform-origin set in CSS."""
    e = "none"
    if kind == "video":
        # jump-cut rhythm on ONE clip: every ~3.4 s a hard cut that alternates a wide framing and a punched-in framing
        n = max(1, round(dur / 3.4)); seg = dur / n; out = []
        for i in range(n):
            a = start + i * seg
            s0, s1 = (1.04, 1.14) if i % 2 == 0 else (1.28, 1.40)
            out.append(f'tl.fromTo("{sel}",{{scale:{s0}}},{{scale:{s1},duration:{seg:.3f},ease:"{e}"}},{a:.3f});')
        return "".join(out)
    if kind == "zoom_out":
        return f'tl.fromTo("{sel}",{{scale:1.22}},{{scale:1.04,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'
    if kind == "pan_right":
        return f'tl.fromTo("{sel}",{{scale:1.2,xPercent:4}},{{scale:1.2,xPercent:-4,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'
    if kind == "pan_left":
        return f'tl.fromTo("{sel}",{{scale:1.2,xPercent:-4}},{{scale:1.2,xPercent:4,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'
    if kind == "pan_up":
        return f'tl.fromTo("{sel}",{{scale:1.2,yPercent:4}},{{scale:1.2,yPercent:-4,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'
    if kind == "pan_down":
        return f'tl.fromTo("{sel}",{{scale:1.2,yPercent:-4}},{{scale:1.2,yPercent:4,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'
    if kind == "focus":
        return f'tl.fromTo("{sel}",{{scale:1.04}},{{scale:1.24,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'
    return f'tl.fromTo("{sel}",{{scale:1.0}},{{scale:1.18,duration:{dur:.3f},ease:"{e}"}},{start:.3f});'


def norm_video(src, dst):
    """Closed-GOP, 1080p30, no audio: the renderer seeks frame-exactly only with dense keyframes."""
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-an",
                        "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-movflags", "+faststart", dst])
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed on {src}")


def wav_len(path):
    try:
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return 1.0


def build(slug):
    root = os.path.join("projects", slug)
    hf = os.path.join(root, "hf")
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8"))
    wd = json.load(open(os.path.join(root, "words.json"), encoding="utf-8"))
    words = Words(wd["words"])
    da = {"accent": "#2EC4F1", "background": "#0A1220", "text": "#FFFFFF", **plan.get("da", {})}
    shots = plan["shots"]
    total = wd["duration"] + 0.4
    shots[0]["start"] = 0.0
    for a, b in zip(shots, shots[1:]):
        a["end"] = b["start"]
    shots[-1]["end"] = total

    os.makedirs(os.path.join(hf, "media"), exist_ok=True)
    os.makedirs(os.path.join(hf, "audio"), exist_ok=True)
    voice_name = "voice" + os.path.splitext(wd["audio"])[1]
    shutil.copy(wd["audio"], os.path.join(hf, "audio", voice_name))

    vjobs = []                # (source, normalised destination)
    els, js = [], []          # DOM elements in z-order, timeline statements
    sfx_marks = []            # (time, family)
    fx = sorted(os.listdir(FX_DIR)) if os.path.isdir(FX_DIR) else []
    leaks = [x for x in fx if x.startswith("burn-") and x.endswith(".mp4")]      # blue/white light leaks
    films = [x for x in fx if x.startswith("film-") and x.endswith(".mp4")]      # warm orange film burns
    rains = itertools.cycle([x for x in fx if x.startswith("rain-")] or [None])   # falling money on black (screen blend)
    last_rain = -1e9
    try:
        fxmeta = json.load(open(os.path.join(FX_DIR, "fx.json")))   # durations, paired sounds, wipe cover windows
    except Exception:
        fxmeta = {}
    glitches = [x for x in fx if x.startswith("glitch-") and x.endswith(".mp4")] if plan.get("glitch", True) else []
    gcyc = itertools.cycle(glitches) if glitches else None
    wipes = [x for x in fx if x.startswith("wipe-") and x.endswith(".webm")]
    wcyc = itertools.cycle(wipes) if wipes else None
    wipe_every = plan.get("wipes", 7)                    # a shape wipe on every Nth cut (0 disables)
    tvs = [x for x in fx if x.startswith("tv-")  and x.endswith(".mp4")]
    n_flash = 0
    style = plan.get("burn_style", "mix")                 # "mix" | "leak" | "film"
    if style == "leak" or not films:
        burns = leaks
    elif style == "film" or not leaks:
        burns = films
    else:
        burns = [x for pair in itertools.zip_longest(leaks, films) for x in pair if x]
    burn_every = plan.get("burns", 3)                 # a flash on every Nth cut; 0/false disables
    bcyc = itertools.cycle(burns) if burns else None
    burn_els = []
    allbg = sorted(x for x in os.listdir(BG_DIR) if x.endswith(".mp4")) if os.path.isdir(BG_DIR) else []
    dark = [x for x in allbg if "-color-" not in x]        # dark grid / topo loops
    color = [x for x in allbg if "-color-" in x]           # bright coloured grids
    bstyle = plan.get("backdrops", "all")                  # "all" (alternate) | "dark" | "color"
    if bstyle == "dark" or not color:
        bgs = dark or color
    elif bstyle == "color" or not dark:
        bgs = color
    else:
        bgs = [x for pair in itertools.zip_longest(dark, color) for x in pair if x]
    bgcyc = itertools.cycle(bgs) if bgs else None
    mv = itertools.cycle(MOVES); prev_move = None
    tcycle = itertools.cycle(TRANS)
    # ----------------------------------------------------------------------------- shots
    for k, s in enumerate(shots):
        sid = s["id"]; r = reg.get(str(sid), {})
        kind = "image" if s["kind"] == "screenshot" else s["kind"]
        if kind != "card" and not r.get("file"):
            kind = "card"; s.setdefault("card", {"text": s.get("must_show", "")[:60]})
        cs = max(s["start"] - (T if k else 0), 0.0)          # clip start (incoming overlap)
        ce = s["end"]
        dur = ce - cs
        trk = k % 2
        tid = f"s{sid}"
        if kind in ("video", "image"):
            if r["kind"] == "video":
                vjobs.append((os.path.join(root, r["file"]), os.path.join(hf, "media", f"{tid}.mp4")))
                els.append(f'<video id="{tid}" class="clip media" data-start="{cs:.3f}" data-duration="{dur:.3f}" '
                           f'data-track-index="{trk}" data-media-start="0.3" data-volume="0" muted playsinline '
                           f'src="media/{tid}.mp4"></video>')
                js.append(motion_js(f"#{tid}", "video", cs, dur))
            else:
                ext = os.path.splitext(r["file"])[1]
                shutil.copy(os.path.join(root, r["file"]), os.path.join(hf, "media", f"{tid}{ext}"))
                layout = s.get("layout") or ("inset" if r.get("platform") == "web" else "full")
                if layout == "inset":
                    # framed card (website screenshot / document / photo) that pops in over a backdrop
                    pos = "top" if r.get("platform") == "web" else "center"
                    t0 = cs if k else s["start"]        # pop in while the shot fades in, never a bare backdrop
                    focus = s.get("focus", "80% 26%") if r.get("platform") == "web" else "50% 50%"
                    img_html = (f'<div id="{tid}c" class="icard"><img src="media/{tid}{ext}" '
                                f'style="object-position:50% {pos};transform-origin:{focus}" /></div>')
                    bgname = s.get("backdrop") or (next(bgcyc) if (bgs and r.get("platform") == "web") else None)
                    if bgname and bgname != "blur" and os.path.exists(os.path.join(BG_DIR, bgname if bgname.endswith(".mp4") else bgname + ".mp4")):
                        bgname = bgname if bgname.endswith(".mp4") else bgname + ".mp4"
                        shutil.copy(os.path.join(BG_DIR, bgname), os.path.join(hf, "media", f"{tid}bg.mp4"))
                        # looping grid/topo video is the main clip (so the transition applies to it); the card sits above
                        els.append(f'<video id="{tid}" class="clip media bgvid" data-start="{cs:.3f}" data-duration="{dur:.3f}" '
                                   f'data-track-index="{trk}" data-media-start="{(k * 3) % 12}" data-volume="0" muted playsinline src="media/{tid}bg.mp4"></video>')
                        els.append(f'<div id="{tid}w" class="clip imgwrap clear" data-start="{cs:.3f}" data-duration="{dur:.3f}" data-track-index="{trk + 2}">{img_html}</div>')
                    else:
                        els.append(f'<div id="{tid}" class="clip imgwrap" data-start="{cs:.3f}" data-duration="{dur:.3f}" data-track-index="{trk}">'
                                   f'<div class="bgb" style="background-image:url(media/{tid}{ext})"></div>{img_html}</div>')
                        js.append(f'tl.fromTo("#{tid} .bgb",{{scale:1.0}},{{scale:1.12,duration:{dur:.3f},ease:"none"}},{cs:.3f});')
                    js.append(f'tl.fromTo("#{tid}c",{{scale:0.80,opacity:0,y:60,rotation:-1.6}},{{scale:1,opacity:1,y:0,rotation:0,duration:0.6,ease:"back.out(1.7)"}},{t0:.3f});')
                    js.append(f'tl.to("#{tid}c",{{scale:1.07,duration:{max(dur-0.6,0.5):.3f},ease:"none"}},{t0+0.6:.3f});')
                    if r.get("platform") == "web":      # zoom into the data (infobox side) so the numbers are readable
                        js.append(f'tl.fromTo("#{tid}c img",{{scale:1.0}},{{scale:{s.get("zoom",1.75)},duration:{max(dur-1.5,0.8):.3f},ease:"power2.inOut"}},{t0+0.9:.3f});')
                    sfx_marks.append((s["start"] + 0.05, "pop"))
                    if r.get("platform") == "web":
                        sfx_marks.append((t0 + 0.9, "type"))          # keyboard clicks while the camera zooms into the page
                else:
                    m = s.get("movement") or next(mv)
                    if m == prev_move: m = next(mv)
                    prev_move = m
                    els.append(f'<img id="{tid}" class="clip media" data-start="{cs:.3f}" data-duration="{dur:.3f}" '
                               f'data-track-index="{trk}" src="media/{tid}{ext}" />')
                    js.append(motion_js(f"#{tid}", m, cs, dur))
        else:
            els.append(card_html(tid, s, cs, dur, trk))
            js.extend(card_js(tid, s, s["start"], s["end"] - s["start"], words))
        # transition into this shot
        if k:
            tr = s.get("transition") or ("fade" if kind == "card" else next(tcycle))
            a = s["start"] - T
            prev_inset = (shots[k - 1].get("layout") == "inset" or reg.get(str(shots[k - 1]["id"]), {}).get("platform") == "web")
            use_wipe = (wcyc and wipe_every and k % wipe_every == wipe_every // 2 and kind != "card" and tr != "tv"
                        and not prev_inset and s.get("transition") is None) or (tr == "wipe" and wcyc)
            fx_sound = None
            if use_wipe or (tr == "tv" and tvs):
                # a shape wipe / TV-bars clip covers the frame; hard-cut to this shot in the middle of the covered window
                ff = next(wcyc) if use_wipe else tvs[k % len(tvs)]
                m_ = fxmeta.get(ff, {}); fd = m_.get("dur", 1.0)
                cov = m_.get("cover") or [fd * 0.45, fd * 0.55]
                ws = s["start"] - (cov[0] + cov[1]) / 2
                ext = os.path.splitext(ff)[1]
                shutil.copy(os.path.join(FX_DIR, ff), os.path.join(hf, "media", f"sw{k}{ext}"))
                burn_els.append(f'<video id="sw{k}" class="clip shapewipe" data-start="{max(ws,0):.3f}" data-duration="{fd:.3f}" data-track-index="4" '
                                f'data-volume="0" muted playsinline src="media/sw{k}{ext}"></video>')
                js.append(f'tl.fromTo("#{tid}",{{opacity:0}},{{opacity:1,duration:0.02}},{s["start"]:.3f});')
                if m_.get("sfx"):
                    sfx_marks.append((max(ws, 0), "file:" + m_["sfx"]))
                else:
                    sfx_marks.append((a + 0.05, "whoosh"))
                continue
            if burn_every and (burns or glitches) and k % burn_every == 0:
                n_flash += 1
                bf = next(gcyc) if (gcyc and n_flash % 5 == 0) else (next(bcyc) if bcyc else next(gcyc))
                fd = min(fxmeta.get(bf, {}).get("dur", 0.32), 1.1)
                shutil.copy(os.path.join(FX_DIR, bf), os.path.join(hf, "media", f"bn{k}.mp4"))
                bs = max(a + T / 2 - fd / 2, 0.0)                     # flash peak on the cut
                burn_els.append(f'<video id="bn{k}" class="clip burn" data-start="{bs:.3f}" data-duration="{fd:.3f}" data-track-index="9" '
                                f'data-volume="0" muted playsinline src="media/bn{k}.mp4"></video>')
                fx_sound = fxmeta.get(bf, {}).get("sfx")
                if fx_sound:
                    sfx_marks.append((bs, "file:" + fx_sound))
            if tr == "push":
                js.append(f'tl.fromTo("#{tid}",{{x:{W}}},{{x:0,duration:{T},ease:"power3.out"}},{a:.3f});')
            elif tr == "zoomthru":
                js.append(f'tl.fromTo("#{tid}",{{opacity:0}},{{opacity:1,duration:{T},ease:"power2.out"}},{a:.3f});')
            elif tr == "whip":
                js.append(f'tl.fromTo("#{tid}",{{x:{int(W*0.6)},opacity:0.2}},{{x:0,opacity:1,duration:{T},ease:"expo.out"}},{a:.3f});')
            else:
                js.append(f'tl.fromTo("#{tid}",{{opacity:0}},{{opacity:1,duration:{T},ease:"power1.inOut"}},{a:.3f});')
            if not fx_sound:
                sfx_marks.append((a + 0.05, "impact" if kind == "card" else "whoosh"))
            if kind == "card":  # accent wipe + flash on card entries
                els.append(f'<div id="wp{sid}" class="clip wipe" data-start="{a-0.05:.3f}" data-duration="{T+0.6:.3f}" data-track-index="8"></div>')
                js.append(f'tl.fromTo("#wp{sid}",{{xPercent:-105}},{{xPercent:0,duration:0.22,ease:"power3.in"}},{a-0.05:.3f});'
                          f'tl.to("#wp{sid}",{{xPercent:105,duration:0.3,ease:"power3.out"}},{a+0.17:.3f});')

    els.extend(burn_els)                              # above the footage, below overlays/text
    print(f"[hf_build] normalising {len(vjobs)} clips (closed GOP, 1080p30)...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda a: norm_video(*a), vjobs))

    # ------------------------------------------------------------------------ overlays on footage
    if plan.get("icons", True):
        print(f"[hf_build] {auto_icons(shots, wd['words'], reg, plan.get('icon_gap', 12.0))} stickers placed")
    ov_i = 0
    for s in shots:
        for ov in s.get("overlays", []):
            ov_i += 1
            t0 = words.find(ov["at_word"], s["start"], s["end"]) if ov.get("at_word") else None
            if t0 is None:
                t0 = s["start"] + ov.get("at", 0.8) + 0.12
            t0 = max(t0 - 0.12, s["start"] + 0.2)         # land just before the spoken word
            d = min(ov.get("dur", 3.2), s["end"] - t0 - 0.05)
            if d < 0.8:
                continue
            oid = f"ov{ov_i}"
            typ = ov["type"]
            if typ == "lower_third":
                els.append(f'<div id="{oid}" class="clip ovl" data-start="{t0:.3f}" data-duration="{d:.3f}" data-track-index="{10+ov_i%6}">'
                           f'<div id="{oid}w" class="lt"><div class="bar"></div><div class="tx"><div class="k">{esc(ov.get("kicker",""))}</div>'
                           f'<div class="t">{esc(ov["text"])}</div></div></div></div>')
                js.append(f'tl.from("#{oid} .bar",{{scaleY:0,duration:0.3,ease:"power3.out"}},{t0:.3f});'
                          f'tl.from("#{oid} .k",{{x:-40,opacity:0,duration:0.35,ease:"power3.out"}},{t0+0.08:.3f});'
                          f'tl.from("#{oid} .t",{{x:-60,opacity:0,duration:0.4,ease:"power3.out"}},{t0+0.16:.3f});'
                          f'tl.to("#{oid}w",{{opacity:0,x:-30,duration:0.3,ease:"power2.in"}},{t0+d-0.36:.3f});tl.set("#{oid}w",{{opacity:0}},{t0+d-0.05:.3f});')
                sfx_marks.append((t0, "whoosh"))
            elif typ == "stat":
                tgt = ov["value"]
                els.append(f'<div id="{oid}" class="clip ovl" data-start="{t0:.3f}" data-duration="{d:.3f}" data-track-index="{10+ov_i%6}">'
                           f'<div id="{oid}w" class="stat"><div class="n"><span class="v">0</span><span class="u">{esc(ov.get("unit",""))}</span></div>'
                           f'<div class="l">{esc(ov["label"])}</div><div class="r"></div></div></div>')
                js.append(f'tl.from("#{oid}w",{{y:-40,opacity:0,duration:0.35,ease:"back.out(1.6)"}},{t0:.3f});'
                          f'tl.from("#{oid} .r",{{scaleX:0,duration:0.45,ease:"power3.out"}},{t0+0.1:.3f});'
                          f'(function(){{const o={{v:0}};tl.to(o,{{v:{tgt},duration:0.9,ease:"power2.out",'
                          f'onUpdate:function(){{document.querySelector("#{oid} .v").textContent=Math.round(o.v);}}}},{t0+0.1:.3f});}})();'
                          f'tl.to("#{oid}w",{{opacity:0,y:-20,duration:0.3,ease:"power2.in"}},{t0+d-0.36:.3f});tl.set("#{oid}w",{{opacity:0}},{t0+d-0.05:.3f});')
                sfx_marks.append((t0 + 0.1, "money" if MONEY_RE.search(f'{ov.get("unit","")} {ov.get("label","")}') else "impact"))
                sfx_marks.append((t0 + 0.1, "riser"))                # builds up and ends on the number
                rf = next(rains)
                if rf and MONEY_RE.search(f'{ov.get("unit","")} {ov.get("label","")}') and t0 - last_rain > 60 and plan.get("money_rain", True):
                    last_rain = t0; rid = f"rain{ov_i}"
                    shutil.copy(os.path.join(FX_DIR, rf), os.path.join(hf, "media", f"{rid}.mp4"))
                    els.insert(len(els) - 1, f'<video id="{rid}" class="clip burn" data-start="{t0:.3f}" data-duration="2.8" data-track-index="5" '
                               f'data-media-start="1" data-volume="0" muted playsinline src="media/{rid}.mp4"></video>')
                    js.append(f'tl.fromTo("#{rid}",{{opacity:0}},{{opacity:0.9,duration:0.3}},{t0:.3f});tl.to("#{rid}",{{opacity:0,duration:0.5}},{t0+2.25:.3f});')
            elif typ == "list":
                items = ov["items"]
                rows = "".join(f'<div class="li"><i></i>{esc(it["text"])}</div>' for it in items)
                els.append(f'<div id="{oid}" class="clip ovl" data-start="{t0:.3f}" data-duration="{d:.3f}" data-track-index="{10+ov_i%6}">'
                           f'<div id="{oid}w" class="lst"><div class="lk">{esc(ov.get("kicker",""))}</div>{rows}</div></div>')
                js.append(f'tl.from("#{oid}w",{{x:-70,opacity:0,duration:0.35,ease:"power3.out"}},{t0:.3f});')
                n_it = len(items)
                for q, it in enumerate(items):
                    ti = it.get("at")
                    ti = (s["start"] + ti) if ti is not None else t0 + 0.3 + q * (d - 1.0) / max(n_it, 1)
                    ti = min(max(ti, t0 + 0.2), t0 + d - 0.5)
                    js.append(f'tl.from("#{oid} .li:nth-child({q+2})",{{x:-60,opacity:0,duration:0.34,ease:"power3.out"}},{ti:.3f});')
                js.append(f'tl.to("#{oid}w",{{opacity:0,x:-30,duration:0.3,ease:"power2.in"}},{t0+d-0.36:.3f});tl.set("#{oid}w",{{opacity:0}},{t0+d-0.05:.3f});')
                sfx_marks.append((t0, "whoosh"))
            elif typ == "icon":
                src = os.path.join(ICON_DIR, ov["file"])
                if not os.path.exists(src):
                    continue
                shutil.copy(src, os.path.join(hf, "media", f"ic_{ov['file']}"))
                side = "left" if ov_i % 3 == 2 else "right"
                els.append(f'<div id="{oid}" class="clip ovl" data-start="{t0:.3f}" data-duration="{d:.3f}" data-track-index="{10+ov_i%6}">'
                           f'<img id="{oid}w" class="icon {side}" src="media/ic_{esc(ov["file"])}" /></div>')
                rot = -8 if side == "right" else 8
                js.append(f'tl.fromTo("#{oid}w",{{scale:0,rotation:{rot*3}}},{{scale:1,rotation:{rot},duration:0.45,ease:"back.out(2.4)"}},{t0:.3f});'
                          f'tl.to("#{oid}w",{{y:-14,rotation:{-rot/2},duration:{max(d-0.8,0.4):.3f},ease:"sine.inOut"}},{t0+0.45:.3f});'
                          f'tl.to("#{oid}w",{{scale:0,opacity:0,duration:0.25,ease:"back.in(2)"}},{t0+d-0.3:.3f});tl.set("#{oid}w",{{opacity:0}},{t0+d-0.04:.3f});')
                sfx_marks.append((t0, "money" if any(k in ov["file"] for k in ("money", "cash", "coin")) else "pop"))
            elif typ == "tag":
                els.append(f'<div id="{oid}" class="clip ovl" data-start="{t0:.3f}" data-duration="{d:.3f}" data-track-index="{10+ov_i%6}">'
                           f'<div id="{oid}w" class="tag" style="left:{ov.get("x",160)}px;top:{ov.get("y",150)}px"><i></i>{esc(ov["text"])}</div></div>')
                js.append(f'tl.from("#{oid}w",{{scale:0.4,opacity:0,duration:0.38,ease:"back.out(2.2)"}},{t0:.3f});'
                          f'tl.to("#{oid}w",{{opacity:0,scale:0.9,duration:0.25,ease:"power2.in"}},{t0+d-0.32:.3f});tl.set("#{oid}w",{{opacity:0}},{t0+d-0.05:.3f});')
                sfx_marks.append((t0, "pop"))

    # -------------------------------------------------------------------------------- captions
    hide = [(s["start"], s["end"]) for s in shots if s["kind"] == "card" or not reg.get(str(s["id"]), {}).get("file")]
    ws = wd["words"] if plan.get("captions", True) else []; gi = 0; cap_i = 0
    while gi < len(ws):
        grp = ws[gi:gi + 4]
        for q, x in enumerate(grp):
            if x["w"].endswith((".", "?", "!")) and q < len(grp) - 1:
                grp = grp[:q + 1]; break
        gi += len(grp)
        g0 = grp[0]["s"]; g1 = max(grp[-1]["e"], grp[-1]["s"] + 0.25)
        if gi < len(ws):
            g1 = min(g1, ws[gi]["s"] - 0.03)
        g1 = max(g1, g0 + 0.2)
        if any(a <= g0 < b for a, b in hide):
            continue
        cap_i += 1; cid = f"cp{cap_i}"
        spans = "".join(f'<span class="w">{esc(x["w"].upper())}</span>' for x in grp)
        els.append(f'<div id="{cid}" class="clip cap" data-start="{g0:.3f}" data-duration="{g1-g0:.3f}" data-track-index="7">{spans}</div>')
        js.append(f'tl.from("#{cid}",{{y:24,opacity:0,duration:0.14,ease:"power2.out"}},{g0:.3f});')
        for q, x in enumerate(grp):
            e = grp[q + 1]["s"] if q + 1 < len(grp) else g1
            js.append(f'tl.to("#{cid} .w:nth-child({q+1})",{{color:"{da["accent"]}",scale:1.14,duration:0.1,ease:"back.out(3)"}},{x["s"]:.3f});'
                      f'tl.to("#{cid} .w:nth-child({q+1})",{{color:"#ffffff",scale:1,duration:0.1}},{max(e-0.05,x["s"]+0.12):.3f});')

    # ------------------------------------------------------------------------------------ audio
    aud = [f'<audio id="vo" class="clip" data-start="0" data-duration="{total:.3f}" data-track-index="20" '
           f'src="audio/{voice_name}" data-volume="1"></audio>']
    fams = {}
    if os.path.isdir(SFX_DIR):
        for f in sorted(os.listdir(SFX_DIR)):
            fams.setdefault(f.split("-")[0], []).append(f)
    cyc = {k: itertools.cycle(v) for k, v in fams.items()}
    chosen = []                                        # (time, family); a money sound beats a nearby whoosh/impact
    layered, last_riser = [], -1e9                     # type / riser sit under the others, not deduplicated against them
    for t, fam in sorted(sfx_marks):
        if fam.startswith("file:"):
            layered.append((t, fam)); continue
        if fam in ("type", "riser"):
            if fam not in cyc:
                continue
            if fam == "riser":
                f = next(cyc["riser"]); t = t - wav_len(os.path.join(SFX_DIR, f))
                if t < 1.0 or t - last_riser < 75:     # rare: at most one build-up every 75 s
                    continue
                last_riser = t
            layered.append((t, fam))
            continue
        fam = fam if fam in cyc else ("whoosh" if "whoosh" in cyc else None)
        if not fam:
            continue
        if chosen and t - chosen[-1][0] < 1.2:
            if fam == "money":
                chosen[-1] = (t, fam)
            continue
        chosen.append((t, fam))
    chosen = sorted(chosen + layered)
    for n, (t, fam) in enumerate(chosen, 1):
        if fam.startswith("file:"):
            f = fam[5:]; src_dir = FX_DIR
        else:
            f = next(cyc[fam]); src_dir = SFX_DIR
        shutil.copy(os.path.join(src_dir, f), os.path.join(hf, "audio", f))
        aud.append(f'<audio id="fx{n}" class="clip" data-start="{max(t,0):.3f}" data-duration="{wav_len(os.path.join(src_dir, f)):.2f}" data-track-index="{ 27 if fam.startswith("file:") else {"riser": 25, "type": 26}.get(fam, 21 + n % 4)}" '
                   f'src="audio/{f}" data-volume="{SFX_VOL.get(f.split("-")[0], 0.30)}"></audio>')
    n = len(chosen)

    css = CSS.replace("__ACC__", da["accent"]).replace("__BG__", da["background"]).replace("__TX__", da["text"]) \
             .replace("__FD__", FONT_DISPLAY).replace("__FT__", FONT_TEXT)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width={W}, height={H}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>{css}</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{W}" data-height="{H}">
{chr(10).join(els)}
<div id="vig" class="clip vig" data-start="0" data-duration="{total:.3f}" data-track-index="6"></div>
{chr(10).join(aud)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
window.__timelines["main"] = tl;
</script>
</body></html>"""
    open(os.path.join(hf, "index.html"), "w", encoding="utf-8").write(page)
    print(f"[hf_build] {len(shots)} shots, {cap_i} caption groups, {ov_i} overlays, {n} sfx -> {hf}/index.html")


# ------------------------------------------------------------------------------------- cards
def card_html(tid, s, cs, dur, trk):
    c = s.get("card", {})
    typ = c.get("type", "statement")
    k = f'<div class="kk">{esc(c["kicker"])}</div>' if c.get("kicker") else ""
    if typ == "list":
        items = "".join(f'<div class="it"><i></i>{esc(it["text"] if isinstance(it, dict) else it)}</div>' for it in c["items"])
        body = f'{k}<div class="items">{items}</div>'
    elif typ == "stat":
        body = f'{k}<div class="bn"><span class="v">0</span><span class="u">{esc(c.get("unit",""))}</span></div><div class="bl">{esc(c.get("label",""))}</div>'
    else:
        lines = "".join(f'<div class="ln">{esc(l)}</div>' for l in c.get("text", "").split("\n"))
        body = f'{k}<div class="body">{lines}</div><div class="rule"></div>'
    return (f'<div id="{tid}" class="clip card" data-start="{cs:.3f}" data-duration="{dur:.3f}" data-track-index="{trk}">'
            f'<div class="halo"></div><div class="rings"></div><div class="inner">{body}</div></div>')


def card_js(tid, s, t0, d, words):
    c = s.get("card", {}); typ = c.get("type", "statement"); out = []
    out.append(f'tl.fromTo("#{tid} .halo",{{scale:1}},{{scale:1.18,duration:{d+0.4:.2f},ease:"none"}},{t0-0.3:.3f});')
    out.append(f'tl.fromTo("#{tid} .rings",{{scale:1,opacity:0.5}},{{scale:1.12,opacity:0.9,duration:{d+0.4:.2f},ease:"none"}},{t0-0.3:.3f});')
    if c.get("kicker"):
        out.append(f'tl.from("#{tid} .kk",{{y:-20,opacity:0,duration:0.3,ease:"power2.out"}},{t0:.3f});')
    if typ == "list":
        n = len(c["items"]); times = []
        for i, it in enumerate(c["items"]):
            tt = words.find(it["at_word"], t0, t0 + d) if isinstance(it, dict) and it.get("at_word") else None
            times.append(tt if tt is not None else t0 + 0.25 + i * (d - 1.0) / max(n, 1))
        for i, tt in enumerate(times):
            out.append(f'tl.from("#{tid} .it:nth-child({i+1})",{{x:-90,opacity:0,duration:0.38,ease:"power3.out"}},{max(tt-0.1,t0):.3f});')
            out.append(f'tl.from("#{tid} .it:nth-child({i+1}) i",{{scale:0,duration:0.3,ease:"back.out(3)"}},{max(tt-0.05,t0):.3f});')
    elif typ == "stat":
        out.append(f'(function(){{const o={{v:0}};tl.to(o,{{v:{c["value"]},duration:0.9,ease:"power2.out",'
                   f'onUpdate:function(){{document.querySelector("#{tid} .v").textContent=Math.round(o.v);}}}},{t0+0.1:.3f});}})();')
        out.append(f'tl.from("#{tid} .bl",{{y:30,opacity:0,duration:0.4,ease:"power3.out"}},{t0+0.3:.3f});')
    else:
        out.append(f'tl.from("#{tid} .ln",{{yPercent:70,opacity:0,duration:0.36,ease:"power3.out",stagger:0.07}},{t0:.3f});')
        out.append(f'tl.fromTo("#{tid} .rule",{{scaleX:0}},{{scaleX:1,duration:0.45,ease:"power3.out"}},{t0+0.18:.3f});')
    return out


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;background:#000;font-family:__FT__}
.media{position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:cover;transform-origin:50% 35%}
.shapewipe{position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:cover;pointer-events:none}
.burn{position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:cover;mix-blend-mode:screen;pointer-events:none}
.imgwrap{position:absolute;inset:0;overflow:hidden;background:#05080f}
.imgwrap.clear{background:transparent}
.bgb{position:absolute;inset:-6%;background-size:cover;background-position:center;filter:blur(38px) brightness(.30)}
.icard{position:absolute;left:50%;top:50%;width:1440px;height:810px;margin:-405px 0 0 -720px;border-radius:14px;overflow:hidden;
  box-shadow:0 34px 100px rgba(0,0,0,.75);border:2px solid rgba(255,255,255,.14);background:#fff}
.icard img{width:100%;height:100%;object-fit:cover;display:block}
.card{position:absolute;inset:0;overflow:hidden;background:__BG__}
.card .halo{position:absolute;inset:-20%;background:radial-gradient(48% 42% at 50% 42%,color-mix(in srgb,__ACC__ 24%,transparent) 0%,transparent 70%)}
.card .rings{position:absolute;inset:0;background:repeating-radial-gradient(circle at 50% 45%,transparent 0 78px,color-mix(in srgb,__TX__ 6%,transparent) 78px 80px)}
.card .inner{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;padding:0 140px;text-align:center}
.kk{font-weight:700;font-size:38px;letter-spacing:.24em;text-transform:uppercase;color:__ACC__}
.body{font-family:__FD__;font-weight:900;font-size:128px;line-height:1.06;letter-spacing:-.02em;color:__TX__}
.ln{display:block;overflow:visible}
.rule{height:8px;width:220px;background:__ACC__;transform-origin:50% 50%}
.items{display:flex;flex-direction:column;gap:30px;align-items:flex-start}
.it{display:flex;align-items:center;gap:30px;font-family:__FD__;font-size:84px;font-weight:900;color:__TX__;line-height:1.1}
.it i{display:block;width:26px;height:26px;border-radius:50%;background:__ACC__;box-shadow:0 0 28px __ACC__;flex:none}
.bn{font-family:__FD__;font-size:340px;font-weight:900;color:__ACC__;line-height:1}.bn .u{font-size:160px;margin-left:12px}
.bl{font-size:56px;font-weight:700;color:__TX__;letter-spacing:.04em}
.wipe{position:absolute;inset:0;background:__ACC__}
.vig{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse at 50% 45%,transparent 55%,rgba(0,0,0,.55) 100%)}
.cap{position:absolute;left:0;right:0;bottom:92px;text-align:center;white-space:nowrap;font-family:__FD__;font-weight:900;font-size:78px;
  color:#fff;text-shadow:0 4px 0 rgba(0,0,0,.65),0 0 24px rgba(0,0,0,.8);-webkit-text-stroke:2px rgba(0,0,0,.55);letter-spacing:.01em}
.cap .w{display:inline-block;margin:0 .17em}
.ovl{position:absolute;inset:0}
.lt{position:absolute;left:110px;bottom:270px;display:flex;gap:26px;align-items:stretch}
.lt .bar{width:10px;background:__ACC__;border-radius:4px;transform-origin:50% 100%}
.lt .tx{max-width:1250px;background:rgba(8,14,26,.82);padding:18px 34px 20px 28px;border-radius:6px;backdrop-filter:blur(6px)}
.lt .k{font-weight:700;font-size:26px;letter-spacing:.22em;text-transform:uppercase;color:__ACC__}
.lt .t{font-family:__FD__;font-weight:900;font-size:50px;color:#fff;margin-top:4px}
.lst{position:absolute;left:110px;top:110px;min-width:520px;padding:24px 40px 26px;background:rgba(8,14,26,.86);border-radius:8px;border-left:10px solid __ACC__}
.lst .lk{font-weight:700;font-size:28px;letter-spacing:.22em;text-transform:uppercase;color:__ACC__;margin-bottom:12px}
.lst .li{display:flex;align-items:center;gap:20px;font-family:__FD__;font-weight:900;font-size:44px;color:#fff;margin-top:10px}
.lst .li i{display:block;width:16px;height:16px;border-radius:50%;background:__ACC__;flex:none}
.stat{position:absolute;left:110px;top:110px;padding:22px 40px 26px;background:rgba(8,14,26,.82);border-radius:8px}
.stat .n{font-family:__FD__;font-weight:900;font-size:150px;line-height:1;color:__ACC__}.stat .u{font-size:70px;margin-left:12px}
.stat .l{font-weight:700;font-size:34px;letter-spacing:.2em;text-transform:uppercase;color:#fff;margin-top:6px}
.stat .r{height:6px;background:__ACC__;margin-top:14px;transform-origin:0 50%}
.tag{position:absolute;display:flex;align-items:center;gap:16px;padding:16px 34px;border-radius:60px;background:rgba(8,14,26,.85);
  border:3px solid __ACC__;font-family:__FD__;font-weight:900;font-size:46px;color:#fff;letter-spacing:.04em;text-transform:uppercase}
.icon{position:absolute;top:120px;width:300px;height:300px;object-fit:contain;filter:drop-shadow(0 0 3px rgba(0,0,0,.85)) drop-shadow(0 0 14px rgba(0,0,0,.55)) drop-shadow(0 18px 30px rgba(0,0,0,.5))}
.icon.right{right:130px}.icon.left{left:130px}
.tag i{width:18px;height:18px;border-radius:50%;background:__ACC__;box-shadow:0 0 18px __ACC__}
"""

if __name__ == "__main__":
    build(sys.argv[1])
