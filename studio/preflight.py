"""Fail early, with a clear message, instead of hours into a job. Returns (errors, warnings)."""
import glob, os, shutil, time


def run():
    err, warn = [], []
    free = shutil.disk_usage("C:\\").free / 1e9
    if free < 6:
        err.append(f"Only {free:.1f} GB free on C: - renders need >6 GB. Delete old projects/*_p* folders and the hyperframes-extract-cache-u folder in %TEMP%.")
    elif free < 12:
        warn.append(f"Low disk space ({free:.1f} GB free).")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ck = os.path.join(root, "cookies.txt")
    if not os.path.exists(ck):
        err.append("cookies.txt missing in the repo root - YouTube will refuse downloads. Export it with the 'Get cookies.txt LOCALLY' Chrome extension.")
    elif time.time() - os.path.getmtime(ck) > 14 * 86400:
        warn.append("cookies.txt is older than 14 days - re-export it if YouTube starts blocking.")
    if not glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg*\bin\ffmpeg.exe")) and not shutil.which("ffmpeg"):
        err.append("FFmpeg not found.")
    if not os.path.isdir(os.path.join(root, "node_modules", "hyperframes")):
        err.append("HyperFrames is not installed - run 'npm install' in the repo folder (setup.ps1 does it).")
    if not glob.glob(os.path.expanduser(r"~\.cache\hyperframes\chrome\chrome-headless-shell\*\*\chrome-headless-shell.exe")):
        err.append("Chrome Headless Shell for rendering is missing (npx hyperframes browser ensure).")
    for need in ("fx", "sfx", "bg", "icons", "stock"):
        if not glob.glob(os.path.join(root, "library", need, "*")):
            warn.append(f"library/{need} is empty - some effects will be skipped.")
    try:
        import cv2  # noqa
        import cv2 as _c
        if not os.path.exists(_c.data.haarcascades + "haarcascade_frontalface_default.xml"):
            warn.append("OpenCV has no face model (need opencv-python-headless==4.10.0.84) - talking-head check disabled.")
    except Exception:
        warn.append("OpenCV missing - talking-head check disabled.")
    return err, warn


if __name__ == "__main__":
    e, w = run()
    print("ERRORS:", *e, sep="\n  ") if e else print("no blocking problems")
    print("WARNINGS:", *w, sep="\n  ") if w else None
