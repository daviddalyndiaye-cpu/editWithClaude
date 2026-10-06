"""Editor-brain step for the web app: transcript -> projects/<slug>/plan.json using Gemini.

(In a Claude Code session the plan is written by Claude directly; this is the automated fallback.)
Shots are b-roll only (no full-screen text cards); on-screen text is a small animated overlay timed to speech.
"""
import json, os, re, sys, time
import truststore; truststore.inject_into_ssl()
from google import genai
from google.genai import types

MODELS = ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
CHUNK = 55  # sentences per Gemini call

PROMPT = """You are the editor of a faceless YouTube documentary. You get a timed voice-over transcript
(sentences with start times in seconds). Cut it into B-ROLL SHOTS and add small animated text overlays.

Return ONLY JSON: {{"shots":[{{"start":<number>,"kind":"video|image|screenshot","must_show":"<what the viewer should see>",
"queries":["q1","q2","q3"],"url":"<only for screenshot>","overlays":[<overlay>,...]}}]}}

SUBJECT LOCK: the video's main subject is "{subject}". Everything on screen must visibly relate to it.
- At least 60% of ALL queries must contain the subject name itself (e.g. "{subject} trawler yacht", "{subject} 62").
- Keep one safe generic query per shot as the last fallback (query 3).
- Prefer photos of the exact subject (models, places, people, products) over generic stock.

SHOT KINDS (mix them; about 55% video, 35% image, 10% screenshot; never three non-video shots in a row)
- "video": B-roll footage (default).
- "image": a real PHOTO (Wikimedia Commons / Flickr via Openverse) of a specific named thing the narrator talks about: a model,
  company HQ/factory, landmark, place, historic object, product. queries = the exact proper names, 2-4 words
  ("{subject} 62", "Yanmar headquarters", "Gothenburg harbour"), most specific first, a broader name last.
  Shown full-screen with zoom or as an animated card. Use it whenever a real photo of that exact subject plausibly exists.
- "screenshot": a website shown as an animated card, for data or sources the narrator cites. "url" MUST be a stable English
  Wikipedia article about a company, person, place or technology that was just named: https://en.wikipedia.org/wiki/<Exact_Title>.
  Never invent other URLs. Also give 2 fallback "queries" for a photo.

SHOT RULES
- Every shot "start" MUST be one of the sentence start times given. Shots cover the whole part, in order.
- Aim for 4-8 seconds per shot (the renderer adds jump-cut zooms inside each shot). Never start two shots on the same sentence.
- "queries": 3 YouTube search queries, English, 3-5 words each, for royalty-free / Creative Commons B-ROLL
  (add words like footage, drone, b-roll, stock). Concrete things you can film: places, machines, boats, people
  working, cities, charts on screens. Avoid: logos, talking heads, interviews, tutorials, reviews, news anchors,
  abstract ideas. Go from most specific to most generic; query 3 must be a SAFE generic visual that surely exists.
- "must_show": one short phrase describing the ideal image.

OVERLAY RULES (text drawn over the footage; use sparingly: about 1 of every 2 shots, none if nothing worth saying)
- {{"type":"lower_third","at":<sec from shot start>,"kicker":"<2-3 words>","text":"<=6 words","dur":3.5}}  names/places/short claims
- {{"type":"stat","at":..,"value":<integer>,"unit":"%|yrs|+|K|M|","label":"<=4 words","dur":3.2}}  ONLY when the narrator says that number
- {{"type":"tag","at":..,"text":"<=4 words","x":150,"y":140,"dur":2.8}}  keyword pills
- {{"type":"list","at":..,"kicker":"<2-3 words>","items":[{{"text":"<=4 words"}},..3-4 items],"dur":4.5}}  when the narrator enumerates
- Text must restate what the narrator says. NEVER invent facts, names or numbers. Keep it short. Match language of the transcript.
- "at" is seconds after the shot start (0.5-6). Overlays inside one shot must not overlap in time.

The video's main subject: {subject}
This is part {k} of {n} of the video. Transcript sentences (start | text):
{lines}
"""


def _client():
    from dotenv import load_dotenv
    load_dotenv(".env")
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _parse(txt):
    """Tolerant JSON: strip fences, take the first JSON value even if extra text follows."""
    txt = re.sub(r"^```(?:json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    start = min([i for i in (txt.find("{"), txt.find("[")) if i >= 0] or [0])
    obj, _ = json.JSONDecoder().raw_decode(txt[start:])
    return obj["shots"] if isinstance(obj, dict) else obj


def _ask(client, prompt, log, attempts=14):
    """Gemini is often 503 'busy' for minutes: rotate models and back off up to ~1 min between tries."""
    last = None
    for attempt in range(attempts):
        model = MODELS[attempt % len(MODELS)]
        try:
            r = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.6,
                                                   max_output_tokens=32000))
            return _parse(r.text)
        except Exception as e:
            last = e
            wait = min(60, 5 + attempt * 5)
            log(f"[plan] {model} failed ({str(e)[:70]}) - retry {attempt+1}/{attempts} in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Gemini planning failed: {last}")


def sentences(words):
    out, cur, st = [], [], None
    for w in words:
        if st is None:
            st = w["s"]
        cur.append(w["w"])
        if w["w"].endswith((".", "?", "!")) or len(cur) >= 40:
            out.append({"s": st, "text": " ".join(cur)}); cur, st = [], None
    if cur:
        out.append({"s": st, "text": " ".join(cur)})
    return out


def detect_subject(client, sents, log=print):
    """One short call: the single main subject (brand / product / person / place) of the video, 1-3 words."""
    text = " ".join(s["text"] for s in sents)[:3500]
    q = ("Read this voice-over transcript excerpt. Answer with ONLY the main subject of the video as 1-3 words "
         "(a brand, product, person or place, exactly as it should be searched for). No punctuation.\n\n" + text)
    for attempt in range(6):
        try:
            r = client.models.generate_content(model=MODELS[attempt % len(MODELS)], contents=q)
            s = re.sub(r"[^\w \-]", "", (r.text or "").strip().split("\n")[0]).strip()
            if s:
                generic = {"boats", "boat", "yachts", "yacht", "trawlers", "trawler", "ships", "ship", "cars", "car", "company",
                           "brand", "review", "reviews", "video", "story", "history", "the"}
                words = [w for w in s.split() if w.lower() not in generic] or s.split()
                s = " ".join(words[:2])
                log(f"[plan] subject: {s}")
                return s
        except Exception as e:
            log(f"[plan] subject call failed ({str(e)[:60]})")
            time.sleep(4 + attempt * 4)
    return ""


def make_plan(slug, accent="#F5A524", background="#0B1220", captions=False, log=print):
    root = os.path.join("projects", slug)
    wd = json.load(open(os.path.join(root, "words.json"), encoding="utf-8"))
    sents = sentences(wd["words"])
    starts = [s["s"] for s in sents]
    client = _client()
    subject = detect_subject(client, sents, log) or "the topic"
    n = (len(sents) + CHUNK - 1) // CHUNK
    shots = []
    for k in range(n):
        part = sents[k * CHUNK:(k + 1) * CHUNK]
        lines = "\n".join(f"{s['s']:.1f} | {s['text']}" for s in part)
        log(f"[plan] Gemini part {k+1}/{n} ({len(part)} sentences)")
        shots += _ask(client, PROMPT.format(k=k + 1, n=n, lines=lines, subject=subject), log)
    # ---- validate / repair
    def snap(t):
        return min(starts, key=lambda x: abs(x - float(t)))
    NUMW = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,
            "fifteen":15,"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90,"hundred":100}
    allw = wd["words"]

    def spoken_numbers(t0, t1):
        nums = set()
        for w in allw:
            if t0 - 0.01 <= w["s"] < t1:
                tok = w["w"].lower().strip(".,!?$%'\"")
                for m in re.findall(r"\d+(?:\.\d+)?", tok.replace(",", "")):
                    nums.add(int(float(m)))
                if tok in NUMW:
                    nums.add(NUMW[tok])
        return nums

    shots = sorted(shots, key=lambda x: float(x.get("start", 0)))
    ends = {}
    for i, s in enumerate(shots):
        ends[id(s)] = float(shots[i + 1]["start"]) if i + 1 < len(shots) else wd["duration"] + 1
    fixed = []
    for s in sorted(shots, key=lambda x: float(x.get("start", 0))):
        t = snap(s.get("start", 0))
        if fixed and abs(fixed[-1]["start"] - t) < 2.4:      # too short -> merge into previous
            continue
        qs = [q for q in s.get("queries", []) if isinstance(q, str) and q.strip()][:3]
        if not qs:
            qs = ["marina boats drone footage"]
        ovs = []
        for o in s.get("overlays", []) or []:
            if isinstance(o, dict) and o.get("type") in ("lower_third", "stat", "tag", "list"):
                o["at"] = float(o.get("at", 1.0)); o["dur"] = float(o.get("dur", 3.2))
                if o["type"] == "stat":
                    try:
                        o["value"] = int(o["value"])
                    except Exception:
                        continue
                    if o["value"] not in spoken_numbers(float(s.get("start", 0)), ends[id(s)]):
                        log(f"[plan] dropped stat {o['value']} (not spoken in that shot)")
                        continue
                if o["type"] == "list":
                    o["items"] = [{"text": (i["text"] if isinstance(i, dict) else str(i)), "at": None} for i in o.get("items", [])][:4]
                    if len(o["items"]) < 2:
                        continue
                ovs.append(o)
        kind = s.get("kind") if s.get("kind") in ("video", "image", "screenshot") else "video"
        url = (s.get("url") or "").strip()
        if kind == "screenshot" and not url.startswith("https://en.wikipedia.org/wiki/"):
            kind = "image"
        if fixed and kind != "video" and fixed[-1]["kind"] != "video":
            kind = "video"                                  # never two non-video shots in a row
        shot = {"start": t, "kind": kind, "queries": qs, "must_show": s.get("must_show", qs[0]), "overlays": ovs}
        if kind == "screenshot":
            shot["url"] = url; shot["layout"] = "inset"
        fixed.append(shot)
    # ---- enforce a fast cutting rhythm: any shot over 8 s is split into 2-3 shots, each with its own search term
    def snap_word(t):
        return min(allw, key=lambda w: abs(w["s"] - t))["s"]
    split = []
    for i, s in enumerate(fixed):
        end = fixed[i + 1]["start"] if i + 1 < len(fixed) else wd["duration"] + 0.4
        dur = end - s["start"]
        if dur <= 8.2:
            split.append(s); continue
        n = min(max(2, round(dur / 5.5)), 3)
        cuts = [s["start"]] + [snap_word(s["start"] + dur * j / n) for j in range(1, n)]
        cuts = sorted(set(round(c, 2) for c in cuts))
        qs = s["queries"]
        for j, c in enumerate(cuts):
            c_end = cuts[j + 1] if j + 1 < len(cuts) else end
            sub = {"start": c, "kind": s["kind"] if j == 0 else "video",
                   "queries": (qs[j:] + qs[:j]) if j else qs,
                   "must_show": s.get("must_show"), "overlays": []}
            if j == 0 and s.get("url"):
                sub["url"] = s["url"]; sub["layout"] = s.get("layout", "inset")
            for o in s["overlays"]:
                ta = s["start"] + o["at"]
                if c - 0.01 <= ta < c_end:
                    o2 = dict(o); o2["at"] = max(0.3, ta - c); sub["overlays"].append(o2)
            split.append(sub)
    fixed = split
    if not fixed or fixed[0]["start"] > 1.0:
        fixed.insert(0, {"start": starts[0], "kind": "video", "queries": ["boats marina drone footage"], "must_show": "establishing", "overlays": []})
    fixed[0]["start"] = 0.0
    sw = subject.lower().split(" ")[0] if subject else ""
    for s in fixed:                                    # subject-specific searches first, generic fallbacks last
        s["queries"] = sorted(s["queries"], key=lambda q: sw not in q.lower()) if sw else s["queries"]
    for i, s in enumerate(fixed, 1):
        s["id"] = i
    plan = {"subject": subject, "da": {"accent": accent, "background": background, "text": "#FFFFFF"}, "captions": captions, "shots": fixed}
    json.dump(plan, open(os.path.join(root, "plan.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    log(f"[plan] {len(fixed)} shots, {sum(len(s['overlays']) for s in fixed)} overlays")
    return plan


if __name__ == "__main__":
    make_plan(sys.argv[1])
