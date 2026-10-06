"""Split a long project into N independently renderable parts (HyperFrames chokes when one
composition holds ~75 video clips). Each part is a mini project: projects/<slug>_pK with its own
plan/words/sources, a junction to the shared media folder and a cut of the voice-over.
Cuts are made at shot starts, so no sentence is split."""
import json, os, subprocess, sys


def slice_project(slug, parts):
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    wd = json.load(open(os.path.join(root, "words.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8"))
    shots = plan["shots"]
    total = wd["duration"] + 0.4
    per = len(shots) / parts
    cuts = [shots[int(round(i * per))]["start"] for i in range(parts)] + [total]
    cuts[0] = 0.0
    names = []
    for k in range(parts):
        t0, t1 = cuts[k], cuts[k + 1]
        name = f"{slug}_p{k+1}"; names.append(name)
        pr = os.path.join("projects", name)
        os.makedirs(pr, exist_ok=True)
        sub = []
        for s in shots:
            if t0 - 1e-6 <= s["start"] < t1 - 1e-6:
                c = json.loads(json.dumps(s)); c["start"] = round(s["start"] - t0, 3); sub.append(c)
        ids = {str(s["id"]) for s in sub}
        json.dump({**plan, "shots": sub}, open(os.path.join(pr, "plan.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        json.dump({k2: v for k2, v in reg.items() if k2 in ids}, open(os.path.join(pr, "sources.json"), "w", encoding="utf-8"))
        words = [{"w": w["w"], "s": round(w["s"] - t0, 2), "e": round(w["e"] - t0, 2)}
                 for w in wd["words"] if t0 - 1e-6 <= w["s"] < t1 - 1e-6]
        audio = os.path.abspath(os.path.join(pr, "voice_part.mp3"))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", wd["audio"],
                        "-c:a", "libmp3lame", "-b:a", "160k", audio], check=True)
        json.dump({"audio": audio, "duration": round(t1 - t0 - 0.4, 2), "words": words},
                  open(os.path.join(pr, "words.json"), "w", encoding="utf-8"), ensure_ascii=False)
        media_link = os.path.join(pr, "media")
        if not os.path.exists(media_link):  # directory junction (no admin needed)
            subprocess.run(["cmd", "/c", "mklink", "/J", media_link, os.path.abspath(os.path.join(root, "media"))],
                           check=True, capture_output=True)
        print(f"[slice] {name}: {t0:.1f}s - {t1:.1f}s, {len(sub)} shots, {sum(1 for s in sub if s['kind']=='video')} clips")
    return names


if __name__ == "__main__":
    slice_project(sys.argv[1], int(sys.argv[2]))
