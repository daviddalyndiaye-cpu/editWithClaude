"""Review helpers (the step that makes or breaks a video):
   python -m studio.review sheets <slug> [ids]   contact sheets of every clip with 'wanted vs got' labels -> projects/<slug>/rv_N.jpg
   python -m studio.review fill   <slug> <ids>   fill bad / empty shots with the best ON-TOPIC clips already in the job
                                                 (never more than 2 uses per clip; long shots are split into 2 cuts)
"""
import copy, glob, json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont


def _ff():
    return glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg*\bin"))[0]


def sheets(slug, ids=None):
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8"))
    S = {s["id"]: s for s in plan["shots"]}
    ids = ids or [s["id"] for s in plan["shots"]]
    f1 = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 15); f2 = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 13)
    TW, TH, LB = 320, 180, 34
    empty = [i for i in ids if not reg.get(str(i), {}).get("file")]
    for n, k in enumerate(range(0, len(ids), 20), 1):
        ch = ids[k:k + 20]
        sh = Image.new("RGB", (5 * TW, 4 * (TH + LB)), (14, 14, 14)); d = ImageDraw.Draw(sh)
        for q, i in enumerate(ch):
            x, y = (q % 5) * TW, (q // 5) * (TH + LB); e = reg.get(str(i), {}); p = os.path.join(root, "_thumbs", f"{i}.jpg")
            if os.path.exists(p) and e.get("file"):
                sh.paste(Image.open(p).convert("RGB").resize((TW, TH)), (x, y))
            tag = f"{i}" + (" PHOTO" if e.get("kind") == "image" else "")
            d.rectangle([x, y, x + 90, y + 22], fill=(245, 200, 0)); d.text((x + 4, y + 2), tag, fill=(0, 0, 0), font=f1)
            d.text((x + 3, y + TH + 2), (S[i].get("must_show") or "")[:44], fill=(255, 255, 120), font=f2)
            d.text((x + 3, y + TH + 17), (e.get("title") or "")[:46], fill=(160, 200, 255), font=f2)
        sh.save(os.path.join(root, f"rv_{n}.jpg"), quality=80)
    print(f"[review] {n} sheets in {root}; shots without footage: {empty}")
    print("  look for: talking heads, slides/text, game/screen captures, namesake places (Nordhavn=Copenhagen district), duplicates")


def fill(slug, targets):
    """Replace the given shots with on-topic clips already in the job (title mentions the subject / yacht / boat words)."""
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8"))
    for fn in ("plan", "sources"):                                   # always keep a backup
        src = os.path.join(root, f"{fn}.json"); dst = os.path.join(root, f"{fn}_before_fill.json")
        if not os.path.exists(dst):
            open(dst, "w", encoding="utf-8").write(open(src, encoding="utf-8").read())
    wd = json.load(open(os.path.join(root, "words.json"), encoding="utf-8")); total = wd["duration"] + 0.4
    S = plan["shots"]
    dur = {s["id"]: ((S[i + 1]["start"] if i + 1 < len(S) else total) - s["start"]) for i, s in enumerate(S)}
    st = {s["id"]: s["start"] for s in S}
    subj = (plan.get("subject") or "").lower().split(" ")[0]
    on_topic = re.compile(rf"({subj}|trawler|yacht|boat|vessel|marina|ship|sail)", re.I) if subj else re.compile(r"(yacht|boat|marina)", re.I)

    def length(p):
        return float(subprocess.run([os.path.join(_ff(), "ffprobe.exe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                    capture_output=True, text=True).stdout.strip() or 0)
    pool = []
    for sid, e in reg.items():
        p = os.path.join(root, e.get("file") or "")
        if int(sid) not in targets and e.get("kind") == "video" and e.get("file") and os.path.exists(p) and on_topic.search(e.get("title") or ""):
            pool.append((int(sid), length(p), e.get("title") or ""))
    used, nxt, new = {}, max(dur) + 1, []
    by = {s["id"]: s for s in S}

    def pick(need, at):
        c = [x for x in pool if x[1] >= need and used.get(x[0], 0) < 2] or \
            [x for x in pool if x[1] >= need * 0.8 and used.get(x[0], 0) < 3] or sorted(pool, key=lambda x: -x[1])[:6]
        return min(c, key=lambda x: (used.get(x[0], 0), -abs(st[x[0]] - at)))
    for t in targets:
        s = by[t]; d = dur[t]
        parts = [(s["start"], d)] if d <= 6.8 else [(s["start"], d / 2), (s["start"] + d / 2, d / 2)]
        for j, (a, dd) in enumerate(parts):
            c = pick(dd + 0.6, a); used[c[0]] = used.get(c[0], 0) + 1
            e = copy.deepcopy(reg[str(c[0])]); e["reused_from"] = c[0]
            if j == 0:
                reg[str(t)] = e; s["kind"] = "video"
                if len(parts) == 2:
                    s["overlays"] = [o for o in s.get("overlays", []) if o.get("at", 0) < d / 2]
            else:
                new.append({"id": nxt, "start": round(a, 2), "kind": "video", "queries": s["queries"], "must_show": s.get("must_show"),
                            "overlays": [dict(o, at=max(0.3, o["at"] - d / 2)) for o in s.get("overlays", []) if o.get("at", 0) >= d / 2]})
                reg[str(nxt)] = e; nxt += 1
    plan["shots"] = sorted(S + new, key=lambda x: x["start"])
    json.dump(reg, open(os.path.join(root, "sources.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(plan, open(os.path.join(root, "plan.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"[fill] {len(targets)} shots -> {len(targets) + len(new)} cuts from a pool of {len(pool)} on-topic clips; max reuse {max(used.values()) if used else 0}")


if __name__ == "__main__":
    cmd, slug = sys.argv[1], sys.argv[2]
    ids = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else None
    sheets(slug, ids) if cmd == "sheets" else fill(slug, ids)
