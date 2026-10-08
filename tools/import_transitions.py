"""Import transition clips into library/fx/ with their own sound effect.

    python tools/import_transitions.py <kind> <file-or-folder> [...]

kind:
  leak | film | glitch   flashes on a black background (screen blend). Kept whole (ramp in -> peak -> out),
                         scaled to 1080p, floor crushed to black. -> fx/burn-NN / film-NN / glitch-NN.mp4
  wipe                   green-screen shape wipes that cover the whole frame for a moment. Keyed to VP9 alpha
                         -> fx/wipe-NN.webm; the fully-covered window is measured and stored in fx/fx.json
  tv                     opaque "no signal" style transition, only used when a shot asks for it -> fx/tv-NN.mp4

If the source has audio, it is saved next to the clip as <name>.wav and the renderer plays it in sync instead of
the generic whoosh. fx/fx.json records duration (and cover window for wipes) so the renderer can centre each
transition on the cut.
"""
import glob, io, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "library", "fx")
PREFIX = {"leak": "burn", "film": "film", "glitch": "glitch", "wipe": "wipe", "tv": "tv"}
KEY = "0x01D700"          # the pack's green; adjust for other packs


def dur_of(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                                capture_output=True, text=True).stdout or 0)


def has_audio(f):
    return "audio" in subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", f],
                                     capture_output=True, text=True).stdout


def cover_window(webm, d):
    """Times where the keyed wipe covers >= 97 % of the frame (alpha), sampled at 30 fps."""
    from PIL import Image
    r = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", webm, "-vf", "fps=30,alphaextract,scale=96:54,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    fr = 96 * 54
    cov = [sum(1 for b in r.stdout[i * fr:(i + 1) * fr] if b > 200) / fr for i in range(len(r.stdout) // fr)]
    if not cov:
        return None
    thr = min(0.97, max(cov) - 0.02)                    # some shapes never reach 100 %: use their fullest moment
    full = [i / 30 for i, c in enumerate(cov) if c >= thr]
    print(f"  max cover {max(cov):.0%}")
    return (min(full), max(full))


def main(kind, srcs):
    pre = PREFIX[kind]
    files = []
    for s in srcs:
        files += sorted(glob.glob(os.path.join(glob.escape(s), "*.mp4")) + glob.glob(os.path.join(glob.escape(s), "*.mov"))) if os.path.isdir(s) else [s]
    os.makedirs(FX, exist_ok=True)
    meta_p = os.path.join(FX, "fx.json")
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    n = max([int(m.group(1)) for f in os.listdir(FX) for m in [re.match(pre + r"-(\d+)\.", f)] if m] or [0])
    for f in files:
        n += 1
        name = f"{pre}-{n:02d}"
        d = dur_of(f)
        if kind == "wipe":
            out = os.path.join(FX, name + ".webm")
            vf = f"scale=1920:1080,fps=30,chromakey={KEY}:0.22:0.06,despill=type=green,format=yuva420p"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vf", vf, "-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                            "-b:v", "0", "-crf", "30", "-auto-alt-ref", "0", "-row-mt", "1", out], check=True)
            cw = cover_window(out, d)
            if not cw:
                print("  WARNING: never fully covers the frame; renderer will centre on the clip's middle")
            meta[os.path.basename(out)] = {"dur": round(d, 3), "cover": [round(cw[0], 3), round(cw[1], 3)] if cw else None}
        else:
            out = os.path.join(FX, name + ".mp4")
            vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,format=yuv420p"
            if kind != "tv":
                vf = vf.replace("format=yuv420p", "lutyuv=y='clip((val-20)*255/235,0,255)',format=yuv420p")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vf", vf, "-an", "-c:v", "libx264", "-crf", "18",
                            "-preset", "fast", "-g", "15", out], check=True)
            meta[os.path.basename(out)] = {"dur": round(d, 3)}
        if has_audio(f):
            wav = os.path.join(FX, name + ".wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vn", "-af", "loudnorm=I=-20:TP=-3", "-ar", "48000", "-ac", "2", wav], check=True)
            meta[os.path.basename(out)]["sfx"] = name + ".wav"
        print(f"{os.path.basename(f)} -> {os.path.basename(out)}  {meta[os.path.basename(out)]}")
    json.dump(meta, open(meta_p, "w"), indent=1)


def remeasure():
    meta_p = os.path.join(FX, "fx.json"); meta = json.load(open(meta_p))
    for k, v in meta.items():
        if k.startswith("wipe-"):
            cw = cover_window(os.path.join(FX, k), v["dur"])
            v["cover"] = [round(cw[0], 3), round(cw[1], 3)] if cw else None
            print(k, v)
    json.dump(meta, open(meta_p, "w"), indent=1)


if __name__ == "__main__":
    remeasure() if sys.argv[1:] == ["--remeasure"] else main(sys.argv[1], sys.argv[2:])
