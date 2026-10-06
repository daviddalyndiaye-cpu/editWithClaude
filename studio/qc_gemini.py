"""Automatic footage QC with Gemini vision: look at contact sheets and flag clips that are talking heads,
slates/title cards/disclaimers, big burned-in text, watermarks, black frames or unrelated to the wanted shot."""
import json, os, re, sys, time
import truststore; truststore.inject_into_ssl()
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

MODELS = ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
PER = 12

PROMPT = """You are quality-checking B-roll clips for a documentary video. The image is a contact sheet; each tile is
one clip's frame with its shot number in a yellow box. For each tile I give what the shot SHOULD show.

Flag a tile as BAD if ANY of these is true:
- a person talking to the camera / vlog / interview / presenter (people simply working or walking are fine)
- a title card, intro slate, disclaimer, big readable text, subtitles burned into the picture, or a logo animation
- a visible watermark or channel banner covering the picture
- a black / blank / nearly empty frame, a screen recording, a slide or diagram
- clearly unrelated to the wanted subject (e.g. a car when a boat is wanted, soldiers, concerts)
Loose but plausible matches (generic marina, ocean, machinery, city, business stock footage) are FINE.

Shots (id: wanted):
{wanted}

Return ONLY JSON: {{"bad":[{{"id":<int>,"why":"<5 words>"}}]}}  (empty list if all fine)."""


def _font(size):
    for p in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def check(slug, only=None, log=print):
    from dotenv import load_dotenv
    load_dotenv(".env")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    root = os.path.join("projects", slug)
    plan = json.load(open(os.path.join(root, "plan.json"), encoding="utf-8"))
    reg = json.load(open(os.path.join(root, "sources.json"), encoding="utf-8"))
    want = {s["id"]: s.get("must_show") or (s.get("queries") or [""])[0] for s in plan["shots"]}
    ids = [i for i in want if reg.get(str(i), {}).get("file") and os.path.exists(os.path.join(root, "_thumbs", f"{i}.jpg"))
           and (only is None or i in only)]
    bad = {}
    f = _font(30)
    for n in range(0, len(ids), PER):
        chunk = ids[n:n + PER]
        sheet = Image.new("RGB", (4 * 400, 3 * 225), (10, 10, 10))
        d = ImageDraw.Draw(sheet)
        for k, i in enumerate(chunk):
            im = Image.open(os.path.join(root, "_thumbs", f"{i}.jpg")).convert("RGB").resize((400, 225))
            x, y = (k % 4) * 400, (k // 4) * 225
            sheet.paste(im, (x, y))
            d.rectangle([x, y, x + 78, y + 38], fill=(245, 200, 0))
            d.text((x + 6, y + 3), str(i), fill=(0, 0, 0), font=f)
        sp = os.path.join(root, f"_qc_{n // PER}.jpg"); sheet.save(sp, quality=85)
        prompt = PROMPT.format(wanted="\n".join(f"{i}: {want[i]}" for i in chunk))
        data = open(sp, "rb").read()
        for attempt in range(10):
            model = MODELS[attempt % len(MODELS)]
            try:
                r = client.models.generate_content(model=model, contents=[types.Part.from_bytes(data=data, mime_type="image/jpeg"), prompt],
                                                   config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2))
                res = json.loads(re.sub(r"^```(?:json)?|```$", "", (r.text or "").strip()).strip())
                for b in res.get("bad", []):
                    if int(b["id"]) in chunk:
                        bad[int(b["id"])] = b.get("why", "")
                break
            except Exception as e:
                log(f"[qc] {model} failed ({str(e)[:80]})")
                time.sleep(min(45, 4 + attempt * 5))
        os.remove(sp)
    log(f"[qc] checked {len(ids)} clips, flagged {len(bad)}: {sorted(bad)}")
    return bad


if __name__ == "__main__":
    print(check(sys.argv[1]))
