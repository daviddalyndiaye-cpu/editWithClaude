"""Turn film-burn / light-leak transition clips into library/fx/burn-XX.mp4 flashes.

    python tools/import_burns.py [--prefix film] <folder-or-files...>   (burn- = light leaks, film- = film burns)

Each source is scanned for its brightest moment; a 0.33 s window around that peak is cut, scaled to 1080p,
and its floor crushed to pure black (the renderer screen-blends it, so any grey base would wash out the footage).
New flashes are numbered after the existing ones; very dim or near-white results are skipped.
"""
import glob, os, re, subprocess, sys

FF_DIR = (glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg*\bin")) or [""])[0]
FFMPEG = os.path.join(FF_DIR, "ffmpeg") if FF_DIR else "ffmpeg"
FX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library", "fx")
WIN = 0.333


def luma_curve(src):
    """[(t, mean luma 0-255)] at 15 fps."""
    r = subprocess.run([FFMPEG, "-v", "info", "-i", src, "-vf", "fps=15,scale=160:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-an", "-f", "null", "-"], capture_output=True, text=True, errors="replace")
    ts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    ys = [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stderr)]
    return list(zip(ts, ys))


def main(srcs):
    prefix = "burn"
    if srcs[:1] == ["--prefix"]:
        prefix, srcs = srcs[1], srcs[2:]
    files = []
    for s in srcs:
        files += sorted(glob.glob(os.path.join(s, "*.mp4"))) if os.path.isdir(s) else [s]
    os.makedirs(FX, exist_ok=True)
    n = max([int(m.group(1)) for f in os.listdir(FX) for m in [re.match(prefix + r"-(\d+)", f)] if m] or [0])
    for f in files:
        if re.search(r"overlay|8mm", os.path.basename(f), re.I):
            continue                                     # long film-grain overlays, not flashes
        cur = luma_curve(f)
        if not cur:
            print("skip (unreadable)", f); continue
        tpk, ypk = max(cur, key=lambda x: x[1])
        if ypk < 40:
            print(f"skip (too dim, peak {ypk:.0f})", os.path.basename(f)); continue
        floor = min(y for _, y in cur)
        start = max(tpk - WIN / 2, 0)
        n += 1
        out = os.path.join(FX, f"{prefix}-{n:02d}.mp4")
        # crush the floor: anything at/below the clip's darkest level becomes black, then gain back
        lo = min(int(floor) + 12, 60)
        vf = (f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,"
              f"lutyuv=y='clip((val-{lo})*255/(255-{lo}),0,255)':u='128+(val-128)*0.9':v='128+(val-128)*0.9',format=yuv420p")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", f, "-t", f"{WIN}", "-vf", vf, "-an",
                        "-c:v", "libx264", "-crf", "18", "-preset", "fast", out], check=True)
        print(f"{os.path.basename(f)} -> {os.path.basename(out)} (peak {ypk:.0f} at {tpk:.2f}s, floor {floor:.0f})")


if __name__ == "__main__":
    main(sys.argv[1:])
