"""AUTO theme - a faithful copy of the user's automobile-report reference (Downloads/videoplayback (5).mp4, 2026-10-09).

Measured from the reference: stage #07080F navy-black with a faint 123 px grid and soft vignette; Montserrat ExtraBold white
uppercase with a soft dark shadow; red #FF1E1E kickers; cards are rounded (radius ~16 px) with a thin light rim and pop in
from a big blurry state; labels blur in under the card; quotes are condensed caps (Oswald) over grey, blurred footage;
article pages are plain white with yellow / lilac highlighter sweeps; step titles assemble word by word from wide,
blurred letter-spacing.

Templates (T(ctx, t0, dur, **params)):
  card_label   one or several cards on the grid stage, each with labels that blur in under it (label can change mid-shot)
  foot_number  big white number / words on footage, bottom-centre, counts up if numeric
  step_title   "STEP #2" red kicker + title assembling word by word (left) ; kicker optional ; align left|center
  quote_blur   footage goes grey + blurred + dark; condensed caps quote in quotes, centred
  article_page white page, body paragraphs, highlighter sweeps (yellow / lilac) over chosen paragraphs, slow push-in
  title_card   footage card on the stage with a big bracketed title + subtitle ON the card ("[CAFE]")
python -m studio.motion_auto -> projects/_motion_demo/auto/hf
"""
import json, os

W, H = 1920, 1080
RED = "#FF1E1E"


def _m():
    from studio import motion as M
    return M


def _vid(p):
    return p.lower().endswith((".mp4", ".mov", ".webm"))


def _stage(ctx, t0, dur):
    return ctx.clip('<div class="astage"><div class="agrid"></div><div class="avig"></div></div>', t0, dur, 10)


def _media(ctx, src, t0, dur, style, track, eid):
    rel = ctx.media(src)
    if _vid(src):
        ctx.els.append(f'<video id="{eid}" class="clip acard" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{track}" '
                       f'data-media-start="0.3" data-volume="0" muted playsinline src="{rel}" style="{style}"></video>')
    else:
        ctx.els.append(f'<div id="{eid}" class="clip acard" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{track}" '
                       f'style="{style}"><img src="{rel}" style="width:100%;height:100%;object-fit:cover;display:block"/></div>')


def _pop_in(eid, t, d=0.55):
    """the reference card entrance: big + blurred + faint -> settled + sharp"""
    return (f'tl.fromTo("#{eid}",{{scale:1.45,opacity:0.35,filter:"blur(22px)"}},'
            f'{{scale:1,opacity:1,filter:"blur(0px)",duration:{d},ease:"power3.out"}},{t:.3f});')


def _pop_out(eid, t, d=0.3, dx=0):
    return f'tl.to("#{eid}",{{opacity:0,x:{dx},filter:"blur(16px)",scale:0.92,duration:{d},ease:"power2.in"}},{t - d:.3f});'


# ------------------------------------------------------------------------------------------------ card + label
def card_label(ctx, t0, dur, cards, stage=True):
    """cards: [{"src": path, "at": s_from_t0, "until": s_from_t0 (optional), "x":, "y":, "w":, "h":, "labels": [(text, at), ...],
    "cutout": bool (no rim/radius - for PNG objects on transparent bg)}]. Defaults: one centred card 860x484 at y 200."""
    M = _m()
    if stage:
        _stage(ctx, t0, dur)
    for c in cards:
        a = t0 + c.get("at", 0.0); e = t0 + c.get("until", dur)
        w, h = c.get("w", 860), c.get("h", 484)
        x = c.get("x", (W - w) // 2); y = c.get("y", 190)
        eid = ctx.uid("ac")
        style = f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;" + ("" if c.get("cutout") else "")
        _media(ctx, c["src"], a, e - a, style + ("background:transparent;border:0;border-radius:0;box-shadow:none;object-fit:contain" if c.get("cutout") else ""), 11, eid)
        ctx.js.append(_pop_in(eid, a) + _pop_out(eid, e))
        labs = c.get("labels", [])
        for k, (text, lat) in enumerate(labs):
            la = a + lat; le = a + labs[k + 1][1] if k + 1 < len(labs) else e
            lid = ctx.clip(f'<div class="alab" style="top:{y + h + 34}px;left:{x + w // 2}px">{M.esc(text)}</div>', la, le - la, 12)
            ctx.js.append(f'tl.fromTo("#{lid} .alab",{{opacity:0,filter:"blur(12px)",scale:1.08}},{{opacity:1,filter:"blur(0px)",scale:1,duration:0.4,ease:"power2.out"}},{la:.3f});'
                          f'tl.to("#{lid} .alab",{{opacity:0,filter:"blur(10px)",duration:0.2,ease:"power2.in"}},{le - 0.2:.3f});')


# ------------------------------------------------------------------------------------------------ number on footage
def foot_number(ctx, t0, dur, bg, text, at=0.4, count=True):
    """Big white Montserrat on the footage, bottom-centre, heavy soft shadow. Counts up if text holds one number ("$70,000")."""
    import re
    M = _m()
    if bg:
        ctx.bg(bg, t0, dur)
    m = re.search(r"\d[\d,]*\.?\d*", text) if count else None
    if m:
        num = m.group(0); val = float(num.replace(",", "")); dec = len(num.split(".")[1]) if "." in num else 0
        pre, suf = M.esc(text[:m.start()]), M.esc(text[m.end():])
        inner = f'{pre}<span class="an">{num}</span>{suf}'
    else:
        inner = M.esc(text)
    eid = ctx.clip(f'<div class="afn">{inner}</div>', t0 + at, dur - at, 13)
    a = t0 + at
    ctx.js.append(f'tl.fromTo("#{eid} .afn",{{opacity:0,y:30,filter:"blur(10px)"}},{{opacity:1,y:0,filter:"blur(0px)",duration:0.45,ease:"power3.out"}},{a:.3f});')
    if m:
        v = int(val) if val.is_integer() else val
        ctx.js.append(f'(function(){{const e=document.querySelector("#{eid} .an");const o={{v:0}};tl.to(o,{{v:{v},duration:1.0,ease:"power2.out",'
                      f'onUpdate:function(){{e.textContent=o.v.toLocaleString("en-US",{{minimumFractionDigits:{dec},maximumFractionDigits:{dec}}});}}}},{a:.3f});}})();')
    ctx.js.append(f'tl.to("#{eid} .afn",{{opacity:0,filter:"blur(8px)",duration:0.25,ease:"power2.in"}},{t0 + dur - 0.25:.3f});')


# ------------------------------------------------------------------------------------------------ step / section title
def step_title(ctx, t0, dur, title, kicker="", align="left", bg=None):
    """The reference's chapter beat: grid stage, red kicker, then each word arrives from wide letter-spacing + blur + offset
    (down-right) and locks into the line, one after another."""
    M = _m()
    if bg:
        b = ctx.bg(bg, t0, dur); ctx.dim(b, t0, 0.3, gray=0.5, d=0.01)
    else:
        _stage(ctx, t0, dur)
    words = "".join(f'<span class="aw">{M.esc(w)}</span> ' for w in title.split())
    cls = "astep center" if align == "center" else "astep"
    eid = ctx.clip(f'<div class="{cls}">' + (f'<div class="akick">{M.esc(kicker)}</div>' if kicker else "") + f'<div class="atitle">{words}</div></div>', t0, dur, 12)
    n = len(title.split()); per = min(0.32, 1.6 / max(n, 1))
    ctx.js.append(f'tl.fromTo("#{eid} .akick",{{opacity:0,filter:"blur(8px)"}},{{opacity:1,filter:"blur(0px)",duration:0.35,ease:"power2.out"}},{t0 + 0.1:.3f});'
                  f'tl.fromTo("#{eid} .aw",{{opacity:0,letterSpacing:"0.55em",x:40,y:26,filter:"blur(6px)"}},'
                  f'{{opacity:1,letterSpacing:"0.01em",x:0,y:0,filter:"blur(0px)",duration:0.55,ease:"power3.out",stagger:{per:.3f}}},{t0 + 0.25:.3f});'
                  f'tl.to("#{eid} .astep",{{opacity:0,filter:"blur(10px)",duration:0.25,ease:"power2.in"}},{t0 + dur - 0.25:.3f});')


# ------------------------------------------------------------------------------------------------ quote on blurred footage
def quote_blur(ctx, t0, dur, bg, quote):
    M = _m()
    b = ctx.bg(bg, t0, dur)
    ctx.js.append(f'tl.fromTo("#{b}",{{filter:"grayscale(1) blur(9px) brightness(.45)"}},{{filter:"grayscale(1) blur(9px) brightness(.45)",duration:0.01}},{t0:.3f});')
    eid = ctx.clip(f'<div class="aq">&#8220;{M.esc(quote.upper())}&#8221;</div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .aq",{{opacity:0,scale:1.06,filter:"blur(8px)"}},{{opacity:1,scale:1,filter:"blur(0px)",duration:0.5,ease:"power3.out"}},{t0 + 0.15:.3f});'
                  # exit like the reference: text smears sideways while the footage whips
                  f'tl.to("#{eid} .aq",{{opacity:0,scaleX:1.6,filter:"blur(14px)",duration:0.3,ease:"power2.in"}},{t0 + dur - 0.3:.3f});')


# ------------------------------------------------------------------------------------------------ article page
def article_page(ctx, t0, dur, paras, hl=None, lead=""):
    """paras: list of paragraphs (strings). hl: {para_index: "yellow"|"lilac"} - each highlight sweeps in order.
    lead: optional dateline prefix ("WASHINGTON –"). White page, centred column, slow push-in."""
    M = _m()
    hl = hl or {}
    ps = "".join(f'<p class="ap"><span class="{"h" + hl[k][0] if k in hl else ""}">'
                 + (M.esc(lead) + " " if k == 0 and lead else "") + f'{M.esc(p)}</span></p>' for k, p in enumerate(paras))
    eid = ctx.clip(f'<div class="apage"><div class="acol">{ps}</div></div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .acol",{{scale:1.0}},{{scale:1.07,duration:{dur:.2f},ease:"none"}},{t0:.3f});'
                  f'tl.fromTo("#{eid} .apage",{{opacity:0}},{{opacity:1,duration:0.25}},{t0:.3f});')
    for n, k in enumerate(sorted(hl)):
        ctx.js.append(f'tl.fromTo("#{eid} .ap:nth-child({k + 1}) span",{{backgroundSize:"0% 100%"}},{{backgroundSize:"100% 100%",duration:0.9,ease:"power1.inOut"}},'
                      f'{t0 + 0.6 + n * 1.1:.3f});')


# ------------------------------------------------------------------------------------------------ title on a card
def title_card(ctx, t0, dur, src, title, sub=""):
    M = _m()
    _stage(ctx, t0, dur)
    w, h = 820, 460; x, y = (W - w) // 2, (H - h) // 2
    cid = ctx.uid("ac")
    _media(ctx, src, t0, dur, f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;", 11, cid)
    ctx.js.append(_pop_in(cid, t0 + 0.05) + _pop_out(cid, t0 + dur))
    eid = ctx.clip(f'<div class="atc" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px"><div class="atct">{M.esc(title)}</div>'
                   f'<div class="atcs">{M.esc(sub)}</div></div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .atc",{{opacity:0,scale:1.3,filter:"blur(16px)"}},{{opacity:1,scale:1,filter:"blur(0px)",duration:0.6,ease:"power3.out"}},{t0 + 0.15:.3f});'
                  + _pop_out(f"{eid} .atc", t0 + dur))


CSS = """
.astage{position:absolute;inset:0;background:#07080F}
.agrid{position:absolute;inset:0;background-image:linear-gradient(rgba(150,160,200,.13) 2px,transparent 2px),linear-gradient(90deg,rgba(150,160,200,.13) 2px,transparent 2px);
  background-size:123px 123px;background-position:-40px -20px}
.avig{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 45%,transparent 30%,rgba(3,3,8,.85) 100%)}
.acard{position:absolute;border-radius:16px;overflow:hidden;object-fit:cover;box-shadow:0 0 0 3px rgba(235,238,250,.85),0 24px 60px rgba(0,0,0,.65)}
.alab{position:absolute;transform:translateX(-50%);white-space:nowrap;font-family:'Mont';font-weight:800;font-size:44px;color:#fff;
  text-transform:uppercase;letter-spacing:.01em;text-shadow:0 0 18px rgba(255,255,255,.35),0 4px 14px rgba(0,0,0,.8)}
.afn{position:absolute;left:0;right:0;bottom:110px;text-align:center;font-family:'Mont';font-weight:800;font-size:92px;color:#fff;
  letter-spacing:.005em;text-transform:uppercase;text-shadow:0 6px 0 rgba(0,0,0,.35),0 8px 30px rgba(0,0,0,.85)}
.astep{position:absolute;left:385px;top:432px}.astep.center{left:0;right:0;text-align:center}
.akick{font-family:'Mont';font-weight:800;font-size:34px;color:__A__;text-transform:uppercase;margin-bottom:2px;letter-spacing:.01em}
.atitle{font-family:'Mont';font-weight:800;font-size:62px;color:#fff;text-transform:uppercase;white-space:nowrap;
  text-shadow:0 0 22px rgba(255,255,255,.28),0 4px 14px rgba(0,0,0,.8)}.aw{display:inline-block}
.aq{position:absolute;left:180px;right:180px;top:50%;transform:translateY(-50%);text-align:center;font-family:'Oswald';font-weight:700;
  font-size:58px;line-height:1.25;color:#fff;text-shadow:0 4px 18px rgba(0,0,0,.8)}
.apage{position:absolute;inset:0;background:#FFFFFF}
.acol{position:absolute;left:320px;top:190px;width:1290px;transform-origin:50% 40%}
.ap{font-family:'InterV';font-weight:400;font-size:29px;line-height:40px;color:#3b3b3b;margin-bottom:30px}
.ap span{background-repeat:no-repeat;background-size:0% 100%;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.ap span.hy{background-image:linear-gradient(#FFF200,#FFF200)}.ap span.hl{background-image:linear-gradient(#E9D7FF,#E9D7FF)}
.atc{position:absolute;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(0,0,0,.18);border-radius:16px}
.atct{font-family:'Mont';font-weight:800;font-size:96px;color:#fff;text-shadow:0 4px 20px rgba(0,0,0,.7)}
.atcs{font-family:'Mont';font-weight:600;font-size:28px;color:#f2f2f2;text-shadow:0 2px 10px rgba(0,0,0,.8)}
/* generic overlays in the AUTO look */
.lk3{background:transparent;color:__A__;font-family:'Mont';font-weight:800;font-size:30px;padding:0;border-radius:0;margin-bottom:0}
.lx3{font-family:'Mont';font-weight:800;font-size:56px;text-transform:uppercase;background:transparent;border:0;padding:0;letter-spacing:.01em;
  text-shadow:0 0 18px rgba(255,255,255,.3),0 4px 14px rgba(0,0,0,.85)}
.ls3{background:rgba(7,8,15,.82);border:0;border-radius:16px;box-shadow:0 0 0 3px rgba(235,238,250,.6)}
.li3{font-family:'Mont';font-weight:800;text-transform:uppercase;font-size:42px}.li3 i{background:__A__;box-shadow:none}
.pill3{background:transparent;color:#fff;font-family:'Mont';font-weight:800;font-size:48px;padding:0;text-shadow:0 6px 0 rgba(0,0,0,.35),0 8px 30px rgba(0,0,0,.85)}
.plate{background:transparent;box-shadow:none;border:0;top:auto;bottom:40px;transform:translateX(-50%)}
.pv{font-family:'Mont';font-weight:800;font-size:100px;text-shadow:0 6px 0 rgba(0,0,0,.35),0 8px 30px rgba(0,0,0,.85)}.pfx{font-size:100px}
.plab{font-family:'Mont';font-weight:800;font-size:30px;color:#fff;letter-spacing:.04em;text-shadow:0 3px 12px rgba(0,0,0,.9)}
.hlbox{background:transparent;box-shadow:none}.hlt{font-family:'Mont';font-weight:800;font-size:60px;color:#fff;text-transform:uppercase;
  text-shadow:0 0 22px rgba(255,255,255,.28),0 4px 14px rgba(0,0,0,.8)}
.digits,.bword{font-family:'Mont';font-weight:800}.bword{color:__A__}
.chbg{background:#07080F;background-image:linear-gradient(rgba(150,160,200,.13) 2px,transparent 2px),linear-gradient(90deg,rgba(150,160,200,.13) 2px,transparent 2px);background-size:123px 123px}
.ghost{display:none}.chtitle{font-family:'Mont';font-weight:800;font-size:72px;text-transform:uppercase}.chsub{font-family:'Mont';color:__A__;font-size:30px}
"""

THEME = {"accent": RED, "hl_h": "100%", "faces": [("InterV", "Inter.ttf", "100 900")], "css": CSS}


def demo():
    import shutil
    M = _m()
    R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hf = os.path.join(R, "projects", "_motion_demo", "auto", "hf")
    shutil.rmtree(hf, ignore_errors=True); os.makedirs(hf)
    ctx = M.Ctx(hf, theme="auto")
    S = lambda f: os.path.join(R, "projects", "_motion_demo", "report_src", f)
    t = 0.0; seq = []

    def add(fn, d, *a, **k):
        nonlocal t
        fn(ctx, t, d, *a, **k); seq.append((fn.__name__, round(t, 2))); t += d
    add(step_title, 3.5, "The invisible killer", align="center")
    add(card_label, 5.0, [{"src": S("grille_still.jpg"), "labels": [("2.7L Ecoboost", 0.6), ("325 HP (120 HP per liter)", 2.6)]}])
    add(card_label, 6.0, [{"src": S("engine_c.mp4"), "x": 140, "y": 120, "w": 620, "h": 349, "at": 0.0, "until": 2.4},
                          {"src": S("mech_c.mp4"), "x": 1100, "y": 420, "w": 620, "h": 349, "at": 2.0, "until": 6.0, "labels": [("Bearing wear", 0.5)]}])
    ctx.bg(S("grille.mp4"), t, 4.0)
    add(foot_number, 4.0, None, "$70,000")
    add(foot_number, 4.0, S("truck_mud.mp4"), "280,000 miles")
    add(quote_blur, 5.0, S("mech_c.mp4"), "Thinner oils, tighter tolerances, and harder bearing materials are all contributing to the failures")
    add(article_page, 6.0, ["WASHINGTON – The Department of Transportation announced new fuel economy standards today, which the agency says will save consumers money at the pump and reduce emissions.",
                            "The new Corporate Average Fuel Economy standards require an industry-wide fleet average of approximately 49 mpg for passenger cars and light trucks in model year 2026.",
                            "Since CAFE was signed into law in 1975, the standards have reduced American oil consumption by roughly a quarter."],
        hl={1: "yellow", 2: "lilac"})
    add(title_card, 4.5, S("truck_mud.mp4"), "[CAFE]", "Corporate Average Fuel Economy")
    add(step_title, 4.0, "Cut your oil intervals in half", kicker="Step #2")
    open(os.path.join(hf, "index.html"), "w", encoding="utf-8").write(M.page(ctx, t))
    json.dump(seq, open(os.path.join(hf, "..", "sequence.json"), "w"), indent=0)
    print(f"[auto] demo {t:.1f}s, {len(seq)} templates -> {hf}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    demo()


def demo_caprae():
    """python -c "from studio.motion_auto import demo_caprae; demo_caprae()" -> projects/_motion_demo/caprae/hf"""
    import shutil
    M = _m()
    R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hf = os.path.join(R, "projects", "_motion_demo", "caprae", "hf")
    shutil.rmtree(hf, ignore_errors=True); os.makedirs(hf)
    ctx = M.Ctx(hf, theme="caprae")
    S = lambda f: os.path.join(R, "projects", "_motion_demo", "report_src", f)
    t = 0.0

    def add(fn, d, *a, **k):
        nonlocal t
        fn(ctx, t, d, *a, **k); t += d
    add(step_title, 3.5, "The invisible killer", align="center")
    add(card_label, 5.0, [{"src": S("grille_still.jpg"), "labels": [("2.7L Ecoboost", 0.6), ("325 HP (120 HP per liter)", 2.6)]}])
    add(M.press_clip, 6.5, "Automotive Ledger", "Maker expands V-6 engine recall to 127,000 more trucks",
        ["Federal regulators said on Tuesday that machining debris left", "inside the engine during manufacturing can damage the",
         "main bearings, which may lead to engine failure while driving.", "Owners will be notified by mail; dealers will inspect",
         "and, if necessary, replace the engine at no cost."], hl=(1, 2), date="Oct 2026", img=S("truck_still.jpg"))
    ctx.bg(S("grille.mp4"), t, 4.0)
    add(foot_number, 4.0, None, "$70,000")
    add(M.quote_wall, 5.5, S("mech_c.mp4"), "Thinner oils, tighter tolerances and harder bearings are all part of the problem.",
        "Independent mechanic, 30 years")
    add(quote_blur, 4.5, S("mech_c.mp4"), "Thinner oils, tighter tolerances, and harder bearing materials are all contributing to the failures")
    add(title_card, 4.0, S("truck_mud.mp4"), "[CAFE]", "Corporate Average Fuel Economy")
    add(step_title, 4.0, "Cut your oil intervals in half", kicker="Step #2")
    open(os.path.join(hf, "index.html"), "w", encoding="utf-8").write(M.page(ctx, t))
    print(f"[caprae] demo {t:.1f}s -> {hf}")
