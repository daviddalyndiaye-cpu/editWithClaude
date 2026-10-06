"""Local web UI: upload a voice-over, watch every stage, review footage, get the video.   http://localhost:8765"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import Flask, jsonify, request, send_from_directory, abort
from app import jobs

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024
jobs.load_all()


def get(jid):
    j = jobs.JOBS.get(jid)
    if not j:
        abort(404)
    return j


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/upload")
def upload():
    f = request.files.get("audio")
    if not f:
        return jsonify(error="No audio file"), 400
    opts = {"accent": request.form.get("accent", "#F5A524"), "captions": request.form.get("captions") == "on",
            "auto_approve": request.form.get("auto") == "on"}
    j = jobs.new_job(request.form.get("title", "").strip(), f.filename, f.read(), opts)
    return jsonify(jobs.view(j, True))


@app.get("/api/jobs")
def list_jobs():
    return jsonify([jobs.view(j) for j in sorted(jobs.JOBS.values(), key=lambda x: -x["created"])])


@app.get("/api/jobs/<jid>")
def job(jid):
    return jsonify(jobs.view(get(jid), True))


@app.get("/api/jobs/<jid>/shots")
def shots(jid):
    return jsonify(jobs.shots_view(get(jid)))


@app.post("/api/jobs/<jid>/approve")
def approve(jid):
    jobs.RT[jid]["action"] = {"type": "approve"}; jobs.RT[jid]["review"].set()
    return jsonify(ok=True)


@app.post("/api/jobs/<jid>/replace")
def replace(jid):
    ids = request.get_json(force=True).get("ids", [])
    if not ids:
        return jsonify(error="Select clips first"), 400
    jobs.RT[jid]["action"] = {"type": "replace", "ids": ids}; jobs.RT[jid]["review"].set()
    return jsonify(ok=True)


@app.post("/api/jobs/<jid>/cancel")
def cancel(jid):
    j = get(jid); j["cancel"] = True
    jobs.RT[jid]["review"].set()
    return jsonify(ok=True)


@app.post("/api/jobs/<jid>/resume")
def resume(jid):
    j = get(jid)
    if j["status"] in ("interrupted", "error", "cancelled"):
        for k, st in j["stages"].items():
            if st["status"] in ("running", "error"):
                st["status"] = "pending"
        jobs.enqueue(jid)
    return jsonify(ok=True)


@app.get("/media/<path:p>")
def media(p):
    return send_from_directory(jobs.PROJ, p, conditional=True)


if __name__ == "__main__":
    print("Open http://localhost:8765")
    app.run(host="127.0.0.1", port=8765, threaded=True)
