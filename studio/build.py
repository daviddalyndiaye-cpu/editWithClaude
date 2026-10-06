"""Step 4: plan.json + media -> projects/<slug>/out/final.mp4

Single FFmpeg pass: per-shot motion (zoompan), xfade transitions, title cards,
word-highlight captions (ASS), whoosh/impact SFX on cuts, optional music bed.
"""
import json, os, subprocess, sys, textwrap, itertools
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, T = 1920, 1080, 30, 0.30
FONT_B = r"C:\Windows\Fonts\arialbd.ttf"
SFX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library", "sfx")
TRANSITIONS = ["fade", "slideleft", "smoothleft", "wipeleft", "dissolve", "slideright", "smoothright"]
MOVES = ["zoom_in", "pan_right", "zoom_out", "pan_left", "focus", "pan_up", "pan_down"]


def _hex(c):
    c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def make_card(path, card, da):
    img = Image.new("RGB", (W, H), _hex(da.get("background", "#0B0E14")))
    d = ImageDraw.Draw(img)
    accent, text = _hex(da.get("accent", "#F5B942")), _hex(da.get("text", "#FFFFFF"))
    for i in range(H):  # soft vertical gradient
        k = i / H
        d.line([(0, i), (W, i)], fill=tuple(int(c + 18 * k) for c in img.getpixel((0, i))))
    y = 330
    if card.get("kicker"):
        f = ImageFont.truetype(FONT_B, 46)
        d.rectangle([160, y + 4, 172, y + 50], fill=accent)
        d.text((196, y), card["kicker"].upper(), font=f, fill=accent); y += 110
    if card.get("big"):
        f = ImageFont.truetype(FONT_B, 280)
        d.text((160, y - 20), card["big"], font=f, fill=accent); y += 300
    if card.get("text"):
        f = ImageFont.truetype(FONT_B, 92 if len(card["text"]) < 60 else 72)
        lines = []
        for para in card["text"].split("\n"):
            cur = ""
            for w in para.split():
                if d.textlength((cur + " " + w).strip(), font=f) > W - 320 and cur:
                    lines.append(cur); cur = w
                else:
                    cur = (cur + " " + w).strip()
            lines.append(cur)
        for ln in lines:
            d.text((160, y), ln, font=f, fill=text); y += int(f.size * 1.25)
    img.save(path)


def motion_expr(kind, n):
    """zoompan z/x/y expressions. Amplitude is deliberately visible (~15%)."""
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == "zoom_out":
        return f"1.16-0.14*on/{n}", cx, cy
    if kind == "pan_right":
        return "1.18", f"(iw-iw/zoom)*on/{n}", cy
    if kind == "pan_left":
        return "1.18", f"(iw-iw/zoom)*(1-on/{n})", cy
    if kind == "pan_up":
        return "1.18", cx, f"(ih-ih/zoom)*(1-on/{n})"
    if kind == "pan_down":
        return "1.18", cx, f"(ih-ih/zoom)*on/{n}"
    if kind == "focus":
        return f"1.02+0.2*on/{n}", "iw*0.58-(iw/zoom/2)", "ih*0.45-(ih/zoom/2)"
    return f"1.0+0.16*on/{n}", cx, cy  # zoom_in


def make_ass(path, words, shots, da):
    acc = _hex(da.get("accent", "#F5B942"))
    bgr = lambda c: f"&H00{c[2]:02X}{c[1]:02X}{c[0]:02X}"
    hide = [(s["start"], s["end"]) for s in shots if s["kind"] == "card"]
    ts = lambda t: f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"
    out = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
           "[V4+ Styles]",
           "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
           "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
           "Style: Cap,Arial,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,120,120,110,1",
           "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    i = 0
    while i < len(words):
        grp = words[i:i + 4]
        # break early at sentence end
        for k, w in enumerate(grp):
            if w["w"].endswith((".", "?", "!")) and k < len(grp) - 1:
                grp = grp[:k + 1]; break
        for k, w in enumerate(grp):
            s = w["s"]; e = grp[k + 1]["s"] if k + 1 < len(grp) else max(w["e"], s + 0.2)
            if any(a <= s < b for a, b in hide):
                continue
            txt = " ".join((f"{{\\c{bgr(acc)}}}{x['w'].upper()}{{\\c&H00FFFFFF&}}" if j == k else x["w"].upper())
                           for j, x in enumerate(grp))
            out.append(f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{txt}")
        i += len(grp)
    open(path, "w", encoding="utf-8").write("\n".join(out))


def build(slug):
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8")) if os.path.exists(
        os.path.join(root, "sources.json")) else {}
    wd = json.load(open(os.path.join(root, "words.json"), encoding="utf-8"))
    da = plan.get("da", {})
    shots = plan["shots"]
    audio = os.path.abspath(wd["audio"])
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "csv=p=0", audio], capture_output=True, text=True).stdout)
    # closed continuity: each shot runs to the next one's start
    shots[0]["start"] = 0.0
    for a, b in zip(shots, shots[1:]):
        a["end"] = b["start"]
    shots[-1]["end"] = total

    inputs, chains, labels = [], [], []
    mv = itertools.cycle(MOVES)
    prev_move = None
    for idx, s in enumerate(shots):
        sid = str(s["id"]); last = idx == len(shots) - 1
        L = (s["end"] - s["start"]) + (0 if last else T)
        n = max(int(L * FPS), 2)
        r = reg.get(sid, {})
        kind = "card" if (s["kind"] == "card" or not r.get("file")) and s["kind"] != "image" else s["kind"]
        if kind == "video" and r.get("file") is None:
            kind = "card"
        if kind == "card":
            card = s.get("card") or {"text": (s.get("must_show") or "")[:80]}
            cp = os.path.join(root, "media", f"card_{sid}.png")
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            make_card(cp, card, da)
            src, kind = f"media/card_{sid}.png", "image"
        else:
            src = r["file"]
        i = sum(1 for t in inputs if t == "-i")
        if kind == "video":
            inputs += ["-ss", "0.3", "-i", src]
            m = s.get("movement") or "zoom_in"
            z = "1.12+0.05*on/%d" % n
            chains.append(
                f"[{i}:v]fps={FPS},scale=3200:-2,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='0':d=1:s={W}x{H}:fps={FPS},"
                f"tpad=stop_mode=clone:stop_duration={L:.2f},trim=duration={L:.3f},setpts=PTS-STARTPTS,format=yuv420p[v{idx}]")
        else:
            m = s.get("movement") or next(mv)
            if m == prev_move:
                m = next(mv)
            prev_move = m
            z, x, y = motion_expr(m, n)
            inputs += ["-framerate", str(FPS), "-loop", "1", "-t", f"{L:.3f}", "-i", src]
            chains.append(
                f"[{i}:v]scale=4000:-2,zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS},"
                f"trim=duration={L:.3f},setpts=PTS-STARTPTS,format=yuv420p[v{idx}]")
        labels.append(f"v{idx}")

    # xfade chain: offset_k = start_{k+1}  (see derivation: accumulated length - T)
    cur = labels[0]; tcycle = itertools.cycle(TRANSITIONS); trans_times = []
    for k in range(1, len(shots)):
        s = shots[k]
        tr = s.get("transition") or ("fadeblack" if k == 1 or s["kind"] == "card" else next(tcycle))
        out = f"x{k}"
        chains.append(f"[{cur}][{labels[k]}]xfade=transition={tr}:duration={T}:offset={s['start']:.3f}[{out}]")
        cur = out; trans_times.append((s["start"], s))
    ass = os.path.join(root, "captions.ass")
    make_ass(ass, wd["words"], shots, da)
    chains.append(f"[{cur}]ass=captions.ass[vout]")

    # audio: voice + sfx on cuts + optional music
    a_idx = len(inputs) // 1  # placeholder, computed below
    n_in = sum(1 for t in inputs if t == "-i")
    inputs += ["-i", audio]; voice = n_in; n_in += 1
    mix = [f"[{voice}:a]volume=1.0[a0]"]; amix_in = ["[a0]"]
    sfx_files = {k: os.path.join(SFX_DIR, f) for k in ("whoosh", "impact")
                 for f in os.listdir(SFX_DIR) if f.startswith(k)} if os.path.isdir(SFX_DIR) else {}
    wh = sorted(f for f in os.listdir(SFX_DIR) if f.startswith("whoosh")) if os.path.isdir(SFX_DIR) else []
    imp = sorted(f for f in os.listdir(SFX_DIR) if f.startswith("impact")) if os.path.isdir(SFX_DIR) else []
    wcyc = itertools.cycle(wh) if wh else None
    last_sfx = -9
    for t, s in trans_times:
        if t - last_sfx < 2.0:
            continue
        f = (imp[0] if (s["kind"] == "card" and imp) else (next(wcyc) if wcyc else None))
        if not f:
            continue
        inputs += ["-i", os.path.join(SFX_DIR, f)]
        ms = int(max(t - 0.1, 0) * 1000)
        mix.append(f"[{n_in}:a]volume=0.35,adelay={ms}|{ms}[s{n_in}]"); amix_in.append(f"[s{n_in}]")
        n_in += 1; last_sfx = t
    music = plan.get("music")
    if music and os.path.exists(music):
        inputs += ["-stream_loop", "-1", "-i", music]
        mix.append(f"[{n_in}:a]volume=0.07[m]"); amix_in.append("[m]"); n_in += 1
    mix.append("".join(amix_in) + f"amix=inputs={len(amix_in)}:normalize=0:duration=first[aout]")

    fc = ";\n".join(chains + mix)
    with open(os.path.join(root, "filter.txt"), "w", encoding="utf-8") as fh:
        fh.write(fc)
    os.makedirs(os.path.join(root, "out"), exist_ok=True)
    sys.path.insert(0, os.getcwd())
    from config import VIDEO_ENCODER, ENCODER_FLAGS
    enc = ["-c:v", VIDEO_ENCODER, *ENCODER_FLAGS.get(VIDEO_ENCODER, [])]
    enc += ["-b:v", "10M"] if VIDEO_ENCODER == "h264_nvenc" else []
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", *inputs, "-/filter_complex", "filter.txt",
           "-map", "[vout]", "-map", "[aout]", *enc, "-c:a", "aac", "-b:a", "192k",
           "-t", f"{total:.3f}", "-movflags", "+faststart", "out/final.mp4"]
    print("[build]", len(shots), "shots, total", f"{total:.1f}s")
    # -/filter_complex needs ffmpeg>=7; fall back to inline if unsupported
    r = subprocess.run(cmd, cwd=root)
    if r.returncode != 0:
        cmd[cmd.index("-/filter_complex")] = "-filter_complex_script"
        r = subprocess.run(cmd, cwd=root)
    if r.returncode != 0:
        sys.exit("ffmpeg failed")
    print("[build] done:", os.path.join(root, "out", "final.mp4"))


if __name__ == "__main__":
    build(sys.argv[1])
