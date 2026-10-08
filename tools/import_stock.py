"""Import a folder of stock b-roll into library/stock/ (1080p30 clips) + library/stock/stock.json (keywords).

    python tools/import_stock.py <folder> [<folder> ...]

Keeps only landscape videos >= 3 s that are not green-screen elements, intros or icon packs.
Keywords come from the file and folder names (edit stock.json to improve them). The fetcher uses these clips
as a fallback when online search finds nothing for a shot (studio.fetch.local_stock), and review fill can too.
Delete any clip you don't want from library/stock and run `python tools/import_stock.py --reindex`.
"""
import glob, json, os, re, subprocess, sys

FF_DIR = (glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg*\bin")) or [""])[0]
FFMPEG = os.path.join(FF_DIR, "ffmpeg") if FF_DIR else "ffmpeg"
FFPROBE = os.path.join(FF_DIR, "ffprobe") if FF_DIR else "ffprobe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "library", "stock")
SKIP = re.compile(r"green ?screen|chroma|intro|icon|logo|counter|safe ?zone|transition|overlay|#", re.I)
STOP = {"pexels", "mixkit", "medium", "video", "videos", "stock", "footage", "free", "no", "copyright", "royalty", "hd", "4k",
        "1080p", "720p", "540p", "2160p", "by", "the", "a", "of", "on", "in", "with", "and", "to", "for", "copy", "noncopyrightvideos"}
VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".m4v")


def probe(f):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", f], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout); st = j["streams"][0]
        return st["width"], st["height"], float(j["format"]["duration"])
    except Exception:
        return 0, 0, 0


def green_fraction(f, dur):
    """Share of strongly green pixels over 3 sampled frames (green-screen elements score high)."""
    from PIL import Image
    import io
    tot = 0.0
    for k in (0.2, 0.5, 0.8):
        r = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{dur * k:.2f}", "-i", f, "-frames:v", "1", "-vf", "scale=96:54",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        try:
            im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
        except Exception:
            continue
        px = list(im.getdata())
        tot += sum(1 for r_, g, b in px if g > 140 and g > r_ * 1.6 and g > b * 1.6) / len(px)
    return tot / 3


def words_of(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    folder = os.path.basename(os.path.dirname(path))
    toks = re.findall(r"[a-z]+", (stem + " " + folder).lower().replace("realstate", "real estate"))
    return [t for t in dict.fromkeys(toks) if t not in STOP and len(t) > 2]


def reindex():
    old = {}
    p = os.path.join(DST, "stock.json")
    if os.path.exists(p):
        old = {x["file"]: x for x in json.load(open(p))}
    idx = [old.get(f, {"file": f, "words": []}) for f in sorted(os.listdir(DST)) if f.endswith(".mp4")]
    json.dump(idx, open(p, "w"), indent=1)
    print(f"{len(idx)} clips indexed")


def main(folders):
    os.makedirs(DST, exist_ok=True)
    p = os.path.join(DST, "stock.json")
    idx = json.load(open(p)) if os.path.exists(p) else []
    have = {x["file"] for x in idx}
    for folder in folders:
        for f in sorted(glob.glob(os.path.join(folder, "**", "*"), recursive=True)):
            if not f.lower().endswith(VIDEO) or SKIP.search(os.path.basename(f)):
                continue
            w, h, d = probe(f)
            if w <= h or d < 3:
                print("skip (vertical/short)", os.path.basename(f)); continue
            if green_fraction(f, d) > 0.12:
                print("skip (green screen)", os.path.basename(f)); continue
            kw = words_of(f)
            name = "-".join(kw[:4]) or "clip"
            out, n = name + ".mp4", 1
            while out in have:
                n += 1; out = f"{name}-{n}.mp4"
            start = min(1.0, d * 0.1)
            subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", f, "-t", "20", "-an",
                            "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,format=yuv420p",
                            "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-g", "30", os.path.join(DST, out)], check=True)
            have.add(out); idx.append({"file": out, "words": kw, "source": os.path.relpath(f, folder)})
            print("ok", out, kw)
    json.dump(idx, open(p, "w"), indent=1)
    print(f"{len(idx)} clips in {DST}")


if __name__ == "__main__":
    reindex() if sys.argv[1:] == ["--reindex"] else main(sys.argv[1:])
