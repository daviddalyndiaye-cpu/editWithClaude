"""Motion-design template library (HyperFrames: HTML + CSS + GSAP on one paused timeline).

Every template is a function  T(ctx, t0, dur, **params)  that appends DOM elements and timeline code to `ctx`.
Rules every template follows (see CLAUDE.md "Motion templates"):
  - eased motion only (power3/expo out on entrances, power2 in on exits), related elements staggered 2-4 frames
  - one focal point; the key number/word holds still for at least ~1 s
  - all text >= 5 % inside the frame; text on footage always gets a plate or a dimmed background
  - deterministic: no Math.random at render time (any "random" order is seeded in Python)

python -m studio.motion demo   -> projects/_motion_demo/hf/index.html (a reel of every template)
"""
import html, json, os, random, shutil, sys

W, H = 1920, 1080
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "library", "fonts")
YEL = "#F5C518"


def esc(s):
    return html.escape(str(s), quote=True)


class Ctx:
    """Collects elements + timeline code for one composition and copies media next to it."""

    def __init__(self, hf_dir, accent=None, theme=None):
        theme = theme if theme in THEMES else DEFAULT_THEME
        self.theme = THEMES[theme]; self.tname = theme
        self.hf = hf_dir; self.els = []; self.js = []; self.n = 0; self.accent = accent or self.theme["accent"]
        os.makedirs(os.path.join(hf_dir, "media"), exist_ok=True)

    def uid(self, p="m"):
        self.n += 1
        return f"{p}{self.n}"

    def media(self, src):
        name = f"mm{len(os.listdir(os.path.join(self.hf, 'media')))}_{os.path.basename(src)}".replace(" ", "_")
        dst = os.path.join(self.hf, "media", name)
        if src.lower().endswith((".mp4", ".mov", ".webm")):
            from studio.hf_build import norm_video          # closed GOP + SDR, or the renderer seeks badly
            dst = dst.rsplit(".", 1)[0] + ".mp4"; norm_video(src, dst); return "media/" + os.path.basename(dst)
        shutil.copy(src, dst)
        return "media/" + name

    def clip(self, inner, t0, dur, track=10, cls="", style="", eid=None):
        eid = eid or self.uid()
        self.els.append(f'<div id="{eid}" class="clip tpl {cls}" data-start="{t0:.3f}" data-duration="{dur:.3f}" '
                        f'data-track-index="{track}" style="{style}">{inner}</div>')
        return eid

    def bg(self, src, t0, dur, track=4, move="zoom", start=0.0):
        """Full-frame background: video or still, with a slow camera move."""
        eid = self.uid("bg"); rel = self.media(src)
        if src.lower().endswith((".mp4", ".mov", ".webm")):
            self.els.append(f'<video id="{eid}" class="clip full" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{track}" '
                            f'data-media-start="{start}" data-volume="0" muted playsinline src="{rel}"></video>')
        else:
            # wrapped in a div: a bare <img> clip is composited below video clips by the renderer
            self.els.append(f'<div id="{eid}w" class="clip" style="position:absolute;inset:0;overflow:hidden;background:#000" data-start="{t0:.3f}" '
                            f'data-duration="{dur:.3f}" data-track-index="{track}"><img id="{eid}" class="full" src="{rel}" /></div>')
        if move == "zoom":
            self.js.append(f'tl.fromTo("#{eid}",{{scale:1.0}},{{scale:1.08,duration:{dur:.3f},ease:"none"}},{t0:.3f});')
        return eid

    def dim(self, target, t, to_brightness=0.5, gray=0, d=0.6, span=None):
        """Darken (and optionally desaturate) the picture. target=None -> an overlay layer over whatever footage is below."""
        if target:
            self.js.append(f'tl.to("#{target}",{{filter:"brightness({to_brightness}) grayscale({gray})",duration:{d},ease:"power2.out"}},{t:.3f});')
            return
        t0, dur = span
        eid = self.clip("", t0, dur, 11, cls="shade", style=f"background:rgba(0,0,0,{1 - to_brightness:.2f});"
                        + (f"backdrop-filter:grayscale({gray});" if gray else ""))
        self.js.append(f'tl.fromTo("#{eid}",{{opacity:0}},{{opacity:1,duration:{d},ease:"power2.out"}},{t:.3f});'
                       f'tl.to("#{eid}",{{opacity:0,duration:0.4,ease:"power2.in"}},{t0 + dur - 0.4:.3f});')

    def vignette(self, t0, dur, strength=0.75, track=11):
        eid = self.clip("", t0, dur, track, cls="vig2")
        self.js.append(f'tl.fromTo("#{eid}",{{opacity:0}},{{opacity:{strength},duration:0.6,ease:"power2.out"}},{t0:.3f});'
                       f'tl.to("#{eid}",{{opacity:0,duration:0.4,ease:"power2.in"}},{t0 + dur - 0.4:.3f});')


def chars(text, cls="ch"):
    return "".join(f'<span class="{cls}">{"&nbsp;" if c == " " else esc(c)}</span>' for c in text)


def exit_fade(ctx, sel, t_end, d=0.35, y=0, scale=1.0):
    ctx.js.append(f'tl.to("{sel}",{{opacity:0,y:{y},scale:{scale},duration:{d},ease:"power2.in"}},{t_end - d:.3f});')


# ============================================================================== TEXT ON FOOTAGE
def highlight_box(ctx, t0, dur, bg, text, y=430):
    """Footage dims + vignette; a yellow label wipes open and the words land inside it."""
    b = ctx.bg(bg, t0, dur) if bg else None; ctx.dim(b, t0 + 0.6, 0.62, span=(t0, dur)); ctx.vignette(t0, dur, 0.8)
    eid = ctx.clip(f'<div class="hlbox" style="top:{y}px"><span class="hlt">{esc(text)}</span></div>', t0, dur, 12)
    a = t0 + 1.0
    ctx.js.append(f'tl.fromTo("#{eid} .hlbox",{{clipPath:"inset(0 100% 0 0)"}},{{clipPath:"inset(0 0% 0 0)",duration:0.45,ease:"expo.out"}},{a:.3f});'
                  f'tl.fromTo("#{eid} .hlt",{{opacity:0,x:-18}},{{opacity:1,x:0,duration:0.4,ease:"power3.out"}},{a + 0.12:.3f});'
                  f'tl.fromTo("#{eid} .hlbox",{{scale:0.96}},{{scale:1,duration:0.6,ease:"back.out(2)"}},{a:.3f});')
    exit_fade(ctx, f"#{eid} .hlbox", t0 + dur, y=-10)


def price_plate(ctx, t0, dur, bg, value, label, prefix="$", suffix=""):
    """Dimmed footage; dark plate with a counting figure (thousands separators, decimals kept) and a small tracked label."""
    dec = len(str(value).split(".")[1].rstrip("0")) if "." in str(value) else 0
    b = ctx.bg(bg, t0, dur) if bg else None; ctx.dim(b, t0 + 0.3, 0.55, span=(t0, dur)); ctx.vignette(t0, dur, 0.6)
    eid = ctx.clip(f'<div class="plate"><div class="pv"><span class="pfx">{esc(prefix)}</span><span class="num">0</span>'
                   f'<span class="sfx">{esc(suffix)}</span></div><div class="plab">{esc(label)}</div></div>', t0, dur, 12)
    a = t0 + 0.5
    ctx.js.append(f'tl.fromTo("#{eid} .plate",{{opacity:0,y:30,filter:"blur(10px)"}},{{opacity:1,y:0,filter:"blur(0px)",duration:0.55,ease:"power3.out"}},{a:.3f});'
                  f'(function(){{const o={{v:0}};tl.to(o,{{v:{value},duration:1.1,ease:"power3.out",onUpdate:function(){{'
                  f'document.querySelector("#{eid} .num").textContent=o.v.toLocaleString("en-US",{{minimumFractionDigits:{dec},maximumFractionDigits:{dec}}});}}}},{a + 0.1:.3f});}})();'
                  f'tl.fromTo("#{eid} .plab",{{opacity:0,letterSpacing:"0.5em"}},{{opacity:1,letterSpacing:"0.18em",duration:0.6,ease:"power2.out"}},{a + 0.9:.3f});')
    exit_fade(ctx, f"#{eid} .plate", t0 + dur, y=-12)


def big_stat_roll(ctx, t0, dur, bg, value, word):
    """Footage turns grey and dark; each digit rolls like a slot machine, then the word slides in beside it."""
    b = ctx.bg(bg, t0, dur) if bg else None; ctx.dim(b, t0 + 0.4, 0.38, gray=1, d=1.0, span=(t0, dur)); ctx.vignette(t0, dur, 0.85)
    digits = str(value)
    cols = "".join(f'<span class="dcol"><span class="dstrip">{"".join(f"<i>{(k) % 10}</i>" for k in range(20 + int(d) + 1))}</span></span>'
                   if d.isdigit() else f'<span class="dsym">{esc(d)}</span>' for d in digits)
    eid = ctx.clip(f'<div class="bigstat"><span class="digits">{cols}</span><span class="bword">{chars(word, "bw")}</span></div>', t0, dur, 12)
    a = t0 + 1.0
    ctx.js.append(f'tl.fromTo("#{eid} .bigstat",{{opacity:0}},{{opacity:1,duration:0.2}},{a:.3f});')
    for k, d in enumerate([d for d in digits if d.isdigit()]):
        steps = 20 + int(d)
        ctx.js.append(f'tl.fromTo("#{eid} .dcol:nth-of-type({k + 1}) .dstrip",{{y:0}},{{y:-{steps}*1.0*parseFloat(getComputedStyle(document.querySelector("#{eid} .digits")).fontSize),'
                      f'duration:{1.3 + 0.15 * k:.2f},ease:"expo.out"}},{a:.3f});')
    ctx.js.append(f'tl.fromTo("#{eid} .bw",{{opacity:0,x:60,filter:"blur(8px)"}},{{opacity:1,x:0,filter:"blur(0px)",duration:0.5,ease:"power3.out",stagger:0.035}},{a + 1.1:.3f});')
    exit_fade(ctx, f"#{eid} .bigstat", t0 + dur)


def typewriter_highlight(ctx, t0, dur, bg, words, x=760, y=520, width=760):
    """Caption types in word by word; words wrapped in *stars* get an italic script face on a yellow box."""
    b = ctx.bg(bg, t0, dur) if bg else None; ctx.dim(b, t0 + 0.2, 0.6, span=(t0, dur)); ctx.vignette(t0, dur, 0.7)
    parts = []
    for w in words.split(" "):
        if w.startswith("*") and w.rstrip(".,!?").endswith("*"):
            tail = w[len(w.rstrip(".,!?")):]
            parts.append(f'<span class="tw hlw"><b>{esc(w.strip("*.,!?"))}</b></span>{esc(tail)} ')
        else:
            parts.append(f'<span class="tw">{esc(w)}</span> ')
    eid = ctx.clip(f'<div class="twbox" style="left:{x}px;top:{y}px;width:{width}px"><span class="caret"></span>{"".join(parts)}</div>', t0, dur, 12)
    a = t0 + 0.5; n = len(words.split(" ")); step = min(0.32, (dur - 2.2) / max(n, 1))
    ctx.js.append(f'tl.set("#{eid} .tw",{{opacity:0}},{t0:.3f});'
                  f'tl.fromTo("#{eid} .caret",{{opacity:0}},{{opacity:1,duration:0.05,repeat:5,yoyo:true}},{t0 + 0.1:.3f});'
                  f'tl.set("#{eid} .caret",{{opacity:0}},{a:.3f});'
                  f'tl.to("#{eid} .tw",{{opacity:1,duration:0.01,stagger:{step:.3f}}},{a:.3f});'
                  f'tl.fromTo("#{eid} .hlw b",{{backgroundSize:"0% {ctx.theme["hl_h"]}"}},{{backgroundSize:"100% {ctx.theme["hl_h"]}",duration:0.3,ease:"power2.out",stagger:{step:.3f}}},{a:.3f});')
    exit_fade(ctx, f"#{eid} .twbox", t0 + dur)


def spaced_title(ctx, t0, dur, bg, title, y=260):
    """Wide-tracked title tightens in over footage, holds, then fades."""
    b = ctx.bg(bg, t0, dur) if bg else None; ctx.dim(b, t0, 0.7, d=0.4, span=(t0, dur)); ctx.vignette(t0, dur, 0.6)
    eid = ctx.clip(f'<div class="sptitle" style="top:{y}px">{esc(title)}</div>', t0, dur, 12)
    a = t0 + 0.3
    ctx.js.append(f'tl.fromTo("#{eid} .sptitle",{{opacity:0,letterSpacing:"0.6em",filter:"blur(12px)"}},'
                  f'{{opacity:1,letterSpacing:"0.08em",filter:"blur(0px)",duration:1.4,ease:"expo.out"}},{a:.3f});')
    exit_fade(ctx, f"#{eid} .sptitle", t0 + dur, d=0.5)


def lower_third(ctx, t0, dur, kicker, text):
    """Bottom-left: mono kicker pill, then the line itself on a glass plate."""
    eid = ctx.clip(f'<div class="lt3"><div class="lk3">{esc(kicker)}</div><div class="lx3">{esc(text)}</div></div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .lk3",{{opacity:0,x:-30}},{{opacity:1,x:0,duration:0.35,ease:"power3.out"}},{t0:.3f});'
                  f'tl.fromTo("#{eid} .lx3",{{clipPath:"inset(0 100% 0 0)"}},{{clipPath:"inset(0 0% 0 0)",duration:0.5,ease:"expo.out"}},{t0 + 0.1:.3f});')
    exit_fade(ctx, f"#{eid} .lt3", t0 + dur, y=10)


def list_panel(ctx, t0, dur, kicker, items, times=None):
    """Glass panel top-left: mono kicker, items land one by one (on their spoken words when `times` given)."""
    rows = "".join(f'<div class="li3 r{q}"><i></i>{esc(t)}</div>' for q, t in enumerate(items))
    eid = ctx.clip(f'<div class="ls3"><div class="lk3">{esc(kicker)}</div>{rows}</div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .ls3",{{opacity:0,y:20}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{t0:.3f});')
    for q in range(len(items)):
        ti = times[q] if times else t0 + 0.3 + q * min(0.7, (dur - 1.2) / max(len(items), 1))
        ctx.js.append(f'tl.fromTo("#{eid} .r{q}",{{opacity:0,x:-24}},{{opacity:1,x:0,duration:0.35,ease:"power3.out"}},{ti:.3f});')
    exit_fade(ctx, f"#{eid} .ls3", t0 + dur, y=-10)


def pill(ctx, t0, dur, text, y=140):
    """Small keyword pill, top centre."""
    eid = ctx.clip(f'<div class="pill3" style="top:{y}px">{esc(text)}</div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .pill3",{{opacity:0,scale:0.6}},{{opacity:1,scale:1,duration:0.4,ease:"back.out(2.2)"}},{t0:.3f});')
    exit_fade(ctx, f"#{eid} .pill3", t0 + dur, scale=0.9)


# ============================================================================== CHAPTER CARD
def chapter(ctx, t0, dur, num, title, sub="", seed=7):
    """Dark card: huge ghost number, title letters land out of order (seeded), two-line subtitle rises."""
    order = list(range(len(title))); random.Random(seed).shuffle(order)
    sub_html = "".join(f"<div>{esc(l)}</div>" for l in sub.split("|")) if sub else ""
    eid = ctx.clip(f'<div class="chbg"></div><div class="ghost">{esc(num)}</div>'
                   f'<div class="chwrap"><div class="chtitle">{chars(title, "ct")}</div><div class="chsub">{sub_html}</div></div>', t0, dur, 12)
    a = t0 + 0.02
    ctx.js.append(f'tl.fromTo("#{eid} .ghost",{{opacity:0.7,scale:1.12}},{{opacity:1,scale:1,duration:1.0,ease:"expo.out"}},{t0:.3f});')
    for rank, i in enumerate(order):
        ctx.js.append(f'tl.fromTo("#{eid} .ct:nth-child({i + 1})",{{opacity:0,y:28,filter:"blur(6px)"}},'
                      f'{{opacity:1,y:0,filter:"blur(0px)",duration:0.3,ease:"power3.out"}},{a + rank * 0.035:.3f});')
    ctx.js.append(f'tl.fromTo("#{eid} .chsub div",{{opacity:0,y:16}},{{opacity:1,y:0,duration:0.45,ease:"power3.out",stagger:0.1}},{a + len(title) * 0.05 + 0.15:.3f});'
                  f'tl.to("#{eid} .chwrap",{{scale:1.04,duration:{dur:.3f},ease:"none"}},{t0:.3f});')
    exit_fade(ctx, f"#{eid} .chwrap, #{eid} .ghost", t0 + dur, d=0.4)


# ============================================================================== PHOTO TEMPLATES
def photo_caption(ctx, t0, dur, img, caption):
    """Framed photo on black, slow push; caption types in letter by letter beneath it."""
    rel = ctx.media(img)
    eid = ctx.clip(f'<div class="blackbg"></div><div class="pcard"><img src="{rel}"/></div><div class="pcap">{chars(caption, "pc")}</div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .pcard",{{opacity:0,scale:0.86}},{{opacity:1,scale:1,duration:0.7,ease:"expo.out"}},{t0:.3f});'
                  f'tl.to("#{eid} .pcard",{{scale:1.05,duration:{dur - 0.7:.3f},ease:"none"}},{t0 + 0.7:.3f});'
                  f'tl.set("#{eid} .pc",{{opacity:0}},{t0:.3f});'
                  f'tl.to("#{eid} .pc",{{opacity:1,duration:0.01,stagger:0.045}},{t0 + 0.55:.3f});')
    exit_fade(ctx, f"#{eid} .pcard, #{eid} .pcap", t0 + dur)


def card_carousel(ctx, t0, dur, imgs, style="paper"):
    """Rounded photo cards on a grid background slide through one by one (paper = light grid, dark = filmstrip with
    yellow frames + number badges). The last card pushes in."""
    rels = [ctx.media(i) for i in imgs]
    gap = 1180 if style == "paper" else 620
    cw, chh = (1080, 640) if style == "paper" else (560, 330)
    cards = "".join(f'<div class="ccard {style}" style="left:{k * gap}px;width:{cw}px;height:{chh}px"><img src="{r}"/>'
                    + (f'<i class="badge">{k + 1:02d}</i>' if style == "dark" else "") + "</div>" for k, r in enumerate(rels))
    eid = ctx.clip(f'<div class="gridbg {style}"></div><div class="ctrack" style="top:{(H - chh) // 2}px;left:{(W - cw) // 2}px">{cards}</div>', t0, dur, 12)
    n = len(rels); seg = (dur - 0.6) / n
    ctx.js.append(f'tl.fromTo("#{eid} .ctrack",{{x:{W}}},{{x:0,duration:0.8,ease:"expo.out"}},{t0:.3f});')
    for k in range(1, n):
        ctx.js.append(f'tl.to("#{eid} .ctrack",{{x:{-k * gap},duration:0.75,ease:"power3.inOut"}},{t0 + k * seg:.3f});')
    for k in range(n):
        on = t0 + (k * seg if k else 0.2)
        ctx.js.append(f'tl.fromTo("#{eid} .ccard:nth-child({k + 1})",{{scale:0.86,opacity:0.55}},{{scale:1,opacity:1,duration:0.6,ease:"power3.out"}},{on:.3f});')
        if k < n - 1:
            ctx.js.append(f'tl.to("#{eid} .ccard:nth-child({k + 1})",{{scale:0.86,opacity:0.55,duration:0.6,ease:"power3.inOut"}},{t0 + (k + 1) * seg:.3f});')
    if style == "dark":   # last card zooms to fill the frame
        ctx.js.append(f'tl.to("#{eid} .ccard:nth-child({n})",{{scale:{W / cw * 1.02:.3f},borderWidth:0,duration:0.9,ease:"power3.inOut"}},{t0 + dur - 1.4:.3f});')
    exit_fade(ctx, f"#{eid}", t0 + dur, d=0.3)


def bubbles(ctx, t0, dur, img_a, img_b, label_a="", label_b=""):
    """Split cream/orange background; two circular photos pop in one after the other."""
    ra, rb = ctx.media(img_a), ctx.media(img_b)
    lab = lambda s: f'<div class="blab">{esc(s)}</div>' if s else ""
    eid = ctx.clip(f'<div class="halfA"></div><div class="halfB"></div>'
                   f'<div class="bub b1" style="left:{W // 4 - 190}px"><img src="{ra}"/></div>{lab(label_a).replace("blab", "blab la")}'
                   f'<div class="bub b2" style="left:{3 * W // 4 - 190}px"><img src="{rb}"/></div>{lab(label_b).replace("blab", "blab lb")}', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .b1",{{scale:0,rotation:-12}},{{scale:1,rotation:0,duration:0.6,ease:"back.out(1.8)"}},{t0 + 0.2:.3f});'
                  f'tl.fromTo("#{eid} .b2",{{scale:0,rotation:12}},{{scale:1,rotation:0,duration:0.6,ease:"back.out(1.8)"}},{t0 + 1.1:.3f});'
                  f'tl.fromTo("#{eid} .la",{{opacity:0,y:20}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{t0 + 0.55:.3f});'
                  f'tl.fromTo("#{eid} .lb",{{opacity:0,y:20}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{t0 + 1.45:.3f});'
                  f'tl.fromTo("#{eid} .bub img",{{scale:1.15}},{{scale:1,duration:{dur:.3f},ease:"none"}},{t0:.3f});')
    exit_fade(ctx, f"#{eid} .bub, #{eid} .blab", t0 + dur, scale=0.9)


def split_tag(ctx, t0, dur, left, right, tag):
    """Two footage panels slide open from the centre seam; a yellow tag pins to the right panel."""
    for k, src in enumerate((left, right)):
        rel = ctx.media(src); pid = ctx.uid("pn")
        st = f"left:{k * (W // 2)}px;top:0;width:{W // 2}px;height:{H}px;object-fit:cover"
        if src.lower().endswith((".mp4", ".mov")):
            ctx.els.append(f'<video id="{pid}" class="clip" style="{st}" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{2 + k}" data-volume="0" muted playsinline src="{rel}"></video>')
        else:
            ctx.els.append(f'<img id="{pid}" class="clip" style="{st}" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{2 + k}" src="{rel}" />')
        ctx.js.append(f'tl.fromTo("#{pid}",{{clipPath:"inset(0 {100 if k == 0 else 0}% 0 {0 if k == 0 else 100}%)"}},'
                      f'{{clipPath:"inset(0 0% 0 0%)",duration:0.7,ease:"expo.out"}},{t0 + 0.12 * k:.3f});')
    eid = ctx.clip(f'<div class="divider"></div><div class="ytag">{esc(tag)}</div>', t0, dur, 12)
    ctx.js.append(f'tl.fromTo("#{eid} .divider",{{scaleY:0}},{{scaleY:1,duration:0.6,ease:"expo.out"}},{t0:.3f});'
                  f'tl.fromTo("#{eid} .ytag",{{clipPath:"inset(0 100% 0 0)"}},{{clipPath:"inset(0 0% 0 0)",duration:0.45,ease:"expo.out"}},{t0 + 0.9:.3f});')
    exit_fade(ctx, f"#{eid} .ytag", t0 + dur)


# ============================================================================== CALLOUTS
def callouts(ctx, t0, dur, img, labels, mode="card", color="#7FD6A5", bgcolor="#0c1712"):
    """Leader-line callouts. labels = [(anchor_x, anchor_y, label_x, label_y, text)] in frame pixels.
    mode="card": photo floats on a dark tinted stage; mode="full": photo/footage fills the frame (labels over it)."""
    rel = ctx.media(img)
    isv = img.lower().endswith((".mp4", ".mov"))
    if mode == "full":
        b = ctx.bg(img, t0, dur); ctx.dim(b, t0 + 0.2, 0.75); stage = ""
    else:
        stage = (f'<div class="stage" style="background:radial-gradient(ellipse at center,{bgcolor} 0%,#020403 80%)"></div>'
                 f'<div class="cimg"><img src="{rel}"/></div>')
    svg = "".join(f'<path class="ld" d="M{ax},{ay} L{lx},{ay if abs(ly - ay) < 4 else ly} L{lx},{ly}" />' for ax, ay, lx, ly, _ in labels)
    dots = "".join(f'<i class="dot d{k}" style="left:{ax - 7}px;top:{ay - 7}px"></i>' for k, (ax, ay, *_) in enumerate(labels))
    tags = "".join(f'<div class="ltag t{k}" style="left:{lx}px;top:{ly}px">{esc(t)}</div>' for k, (_, _, lx, ly, t) in enumerate(labels))
    eid = ctx.clip(f'{stage}<svg class="lines" viewBox="0 0 {W} {H}">{svg}</svg>{dots}{tags}', t0, dur, 12,
                   style=f"--lc:{color}")
    if mode != "full":
        ctx.js.append(f'tl.fromTo("#{eid} .cimg",{{opacity:0,scale:0.9}},{{opacity:1,scale:1,duration:0.7,ease:"expo.out"}},{t0:.3f});'
                      f'tl.to("#{eid} .cimg",{{scale:1.04,duration:{dur - 0.7:.3f},ease:"none"}},{t0 + 0.7:.3f});')
    for k in range(len(labels)):
        a = t0 + 0.8 + k * 0.55
        ctx.js.append(f'tl.fromTo("#{eid} .d{k}",{{scale:0}},{{scale:1,duration:0.3,ease:"back.out(3)"}},{a:.3f});'
                      f'(function(){{const p=document.querySelectorAll("#{eid} .ld")[{k}];const L=p.getTotalLength();'
                      f'tl.fromTo(p,{{strokeDasharray:L,strokeDashoffset:L}},{{strokeDashoffset:0,duration:0.5,ease:"power2.inOut"}},{a + 0.1:.3f});}})();'
                      f'tl.fromTo("#{eid} .t{k}",{{opacity:0,y:8}},{{opacity:1,y:0,duration:0.35,ease:"power3.out"}},{a + 0.5:.3f});')
    exit_fade(ctx, f"#{eid}", t0 + dur, d=0.3)


# ============================================================================== DATA
def fill_bar(ctx, t0, dur, title, value, source="", glitch_in=True):
    """Dark grid stage; a capsule fills from the bottom while the % counts up beside it."""
    eid = ctx.clip(f'<div class="gridbg data"></div><div class="fbtitle">{esc(title)}</div>'
                   f'<div class="fcap"><div class="capfill"></div></div><div class="fbnum"><span class="n">0</span>%</div>'
                   f'<div class="fbsrc">{esc(source)}</div>', t0, dur, 12)
    a = t0 + 0.4
    if glitch_in:
        ctx.js.append(f'tl.fromTo("#{eid}",{{x:-24,filter:"hue-rotate(90deg) contrast(1.6)"}},{{x:0,filter:"hue-rotate(0deg) contrast(1)",duration:0.25,ease:"steps(5)"}},{t0:.3f});')
    ctx.js.append(f'tl.fromTo("#{eid} .fbtitle",{{opacity:0.4,y:-20}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{t0:.3f});'
                  f'tl.fromTo("#{eid} .fcap",{{opacity:0.5,scaleY:0.7}},{{opacity:1,scaleY:1,duration:0.4,ease:"expo.out"}},{t0:.3f});'
                  f'tl.fromTo("#{eid} .capfill",{{height:"0%"}},{{height:"{value}%",duration:1.6,ease:"power3.out"}},{a:.3f});'
                  f'(function(){{const o={{v:0}};tl.to(o,{{v:{value},duration:1.6,ease:"power3.out",onUpdate:function(){{'
                  f'document.querySelector("#{eid} .n").textContent=Math.round(o.v);}}}},{a:.3f});}})();'
                  f'tl.fromTo("#{eid} .fbnum",{{opacity:0,x:30}},{{opacity:1,x:0,duration:0.4,ease:"power3.out"}},{a:.3f});'
                  f'tl.fromTo("#{eid} .fbsrc",{{opacity:0}},{{opacity:1,duration:0.5}},{a + 1.2:.3f});')
    exit_fade(ctx, f"#{eid}", t0 + dur, d=0.3)



# ============================================================================== THEMES (our own visual identities)
# Same animations, different look: fonts, palette, backgrounds and shape language. "classic" = the reference style.
THEMES = {

}

# ============================================================================== CSS + PAGE
def font_css():
    faces = [("Bebas", "BebasNeue-Regular.ttf", 400), ("Mont", "Montserrat-Medium.ttf", 500), ("Mont", "Montserrat-SemiBold.ttf", 600),
             ("Mont", "Montserrat-Bold.ttf", 700), ("Mont", "Montserrat-ExtraBold.ttf", 800), ("Mont", "Montserrat-Black.ttf", 900),
             ("Oswald", "Oswald-Bold.ttf", 700), ("Script", "Lobster-Regular.ttf", 400)]
    return "".join(f"@font-face{{font-family:'{f}';src:url('fonts/{p}');font-weight:{w}}}" for f, p, w in faces)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;background:#000;font-family:'Mont',sans-serif}
.clip{position:absolute}.full{position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:cover;transform-origin:50% 50%}
.tpl{position:absolute;inset:0}
.vig2{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 50%,transparent 35%,rgba(0,0,0,.85) 100%)}
.shade{position:absolute;inset:0}
.sfx{font-size:.5em;margin-left:14px;color:__Y__;letter-spacing:0}
.lt3{position:absolute;left:110px;bottom:120px}
.lk3{display:inline-block;font-family:'Mono';font-weight:700;font-size:22px;letter-spacing:.08em;color:#0A0A0A;background:__Y__;border-radius:999px;padding:5px 16px;margin-bottom:12px;text-transform:uppercase}
.lx3{font-family:'Mont';font-weight:700;font-size:58px;letter-spacing:-.02em;color:#fff;background:rgba(10,10,10,.72);border:1px solid rgba(255,255,255,.22);border-radius:18px;padding:12px 28px 16px}
.ls3{position:absolute;left:110px;top:110px;min-width:560px;background:rgba(10,10,10,.78);border:1px solid rgba(255,255,255,.22);border-radius:24px;padding:22px 34px 26px}
.li3{display:flex;align-items:center;gap:18px;font-family:'Mont';font-weight:700;font-size:44px;color:#fff;margin-top:10px;letter-spacing:-.01em}
.li3 i{width:14px;height:14px;border-radius:50%;background:__Y__;box-shadow:0 0 16px __Y__;flex:none}
.pill3{position:absolute;left:50%;transform:translateX(-50%);font-family:'Mono';font-weight:700;font-size:30px;letter-spacing:.06em;color:#0A0A0A;background:__Y__;border-radius:999px;padding:10px 26px;text-transform:uppercase;white-space:nowrap}
/* highlight box */
.hlbox{position:absolute;left:50%;transform:translateX(-50%);background:__Y__;padding:14px 30px 16px;border-radius:4px;
  box-shadow:0 10px 40px rgba(0,0,0,.45);white-space:nowrap}
.hlt{font-weight:800;font-size:44px;color:#111;letter-spacing:-.01em}
/* price plate */
.plate{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);background:rgba(8,8,8,.88);padding:18px 46px 22px;border-radius:6px;
  text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.pv{font-family:'Bebas';font-size:150px;line-height:1;color:#fff;letter-spacing:.01em}.pfx{font-size:110px}
.plab{font-weight:700;font-size:22px;letter-spacing:.18em;color:#d8d8d8;text-transform:uppercase;margin-top:6px}
/* big stat roll */
.bigstat{position:absolute;left:150px;top:50%;transform:translateY(-50%);display:flex;align-items:baseline;gap:34px;color:#fff;
  text-shadow:0 8px 40px rgba(0,0,0,.6)}
.digits{font-family:'Bebas';font-size:300px;line-height:1;display:flex}
.dcol{display:inline-block;height:1em;overflow:hidden;line-height:1}.dstrip{display:flex;flex-direction:column}.dstrip i{font-style:normal;height:1em;display:block}
.bword{font-family:'Bebas';font-size:190px;letter-spacing:.02em}.bw{display:inline-block}
/* typewriter */
.twbox{position:absolute;font-weight:800;font-size:62px;line-height:1.55;color:#fff;text-shadow:0 3px 14px rgba(0,0,0,.7)}
.tw{display:inline}.hlw b{font-family:'Script';font-weight:400;font-size:68px;color:#151515;padding:0 12px 4px;border-radius:4px;
  background:linear-gradient(__Y__,__Y__) no-repeat left/0% 100%;text-shadow:none}
.caret{display:inline-block;width:6px;height:70px;background:__Y__;vertical-align:-10px;margin-right:10px}
/* spaced title */
.sptitle{position:absolute;left:0;right:0;text-align:center;font-family:'Oswald';font-weight:700;font-size:128px;color:#fff;
  text-transform:uppercase;text-shadow:0 6px 30px rgba(0,0,0,.6)}
/* chapter */
.chbg{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 45%,#2a2a2a 0%,#0e0e0e 55%,#050505 100%)}
.ghost{position:absolute;left:0;right:0;top:50%;transform:translateY(-58%);text-align:center;font-family:'Bebas';font-size:720px;
  line-height:1;color:rgba(255,255,255,.06)}
.chwrap{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);text-align:center}
.chtitle{font-family:'Bebas';font-size:170px;color:#fff;line-height:1;letter-spacing:.02em}.ct{display:inline-block}
.chsub{font-weight:800;font-size:34px;letter-spacing:.06em;color:#cfcfcf;text-transform:uppercase;margin-top:16px;line-height:1.35}
/* photo caption */
.blackbg{position:absolute;inset:0;background:#000}
.pcard{position:absolute;left:50%;top:44%;width:1120px;height:660px;margin:-330px 0 0 -560px;border:5px solid #e9e9e9;
  box-shadow:0 30px 80px rgba(0,0,0,.8);overflow:hidden}.pcard img{width:100%;height:100%;object-fit:cover}
.pcap{position:absolute;left:0;right:0;top:860px;text-align:center;font-family:'Bebas';font-size:58px;letter-spacing:.06em;color:#fff}
.pc{display:inline-block}
/* grids + carousel */
.gridbg{position:absolute;inset:0}
.gridbg.paper{background-color:#f3f3f1;background-image:linear-gradient(#d9d9d6 1.5px,transparent 1.5px),linear-gradient(90deg,#d9d9d6 1.5px,transparent 1.5px);background-size:46px 46px}
.gridbg.dark,.gridbg.data{background-color:#0a0a0a;background-image:linear-gradient(#1f1f1f 1.5px,transparent 1.5px),linear-gradient(90deg,#1f1f1f 1.5px,transparent 1.5px);background-size:64px 64px}
.gridbg.data{background-color:#14171d;background-image:linear-gradient(#20252e 1.5px,transparent 1.5px),linear-gradient(90deg,#20252e 1.5px,transparent 1.5px)}
.ctrack{position:absolute}
.ccard{position:absolute;top:0;overflow:visible}.ccard img{width:100%;height:100%;object-fit:cover;display:block}
.ccard.paper{border-radius:26px;overflow:hidden;box-shadow:0 22px 50px rgba(0,0,0,.28)}
.ccard.dark{border:8px solid __Y__;box-shadow:0 16px 40px rgba(0,0,0,.7)}
.badge{position:absolute;left:50%;bottom:-22px;transform:translateX(-50%);background:__Y__;color:#111;font-style:normal;font-family:'Bebas';
  font-size:26px;padding:2px 10px;border-radius:3px}
/* bubbles */
.halfA{position:absolute;left:0;top:0;width:960px;height:1080px;background:#FDF1C7}.halfB{position:absolute;left:960px;top:0;width:960px;height:1080px;background:#FBC879}
.bub{position:absolute;top:350px;width:380px;height:380px;border-radius:50%;overflow:hidden;border:10px solid #fff;box-shadow:0 24px 50px rgba(0,0,0,.25)}
.bub img{width:100%;height:100%;object-fit:cover}
.blab{position:absolute;top:780px;width:960px;text-align:center;font-weight:900;font-size:46px;color:#1b1b1b;letter-spacing:.02em}.la{left:0}.lb{left:960px}
/* split */
.panel{top:0;height:1080px;overflow:hidden}.pfill{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.divider{position:absolute;left:957px;top:0;width:6px;height:1080px;background:#111;transform-origin:50% 0}
.ytag{position:absolute;right:70px;top:70px;background:__Y__;color:#111;font-weight:900;font-size:34px;padding:8px 18px;letter-spacing:.03em}
/* callouts */
.stage{position:absolute;inset:0}
.cimg{position:absolute;left:50%;top:50%;width:1100px;height:680px;margin:-340px 0 0 -550px;filter:drop-shadow(0 30px 60px rgba(0,0,0,.7))}
.cimg img{width:100%;height:100%;object-fit:contain}
.lines{position:absolute;inset:0;width:1920px;height:1080px;overflow:visible}
.ld{fill:none;stroke:var(--lc);stroke-width:3}
.dot{position:absolute;width:14px;height:14px;border-radius:50%;border:3px solid var(--lc);background:rgba(0,0,0,.4)}
.ltag{position:absolute;transform:translate(-50%,-50%);background:rgba(10,14,12,.92);border:2px solid var(--lc);color:#eafff3;
  font-weight:800;font-size:24px;letter-spacing:.08em;padding:6px 14px;white-space:nowrap;text-transform:uppercase}
/* fill bar */
.fbtitle{position:absolute;left:0;right:0;top:150px;text-align:center;font-weight:900;font-size:62px;color:#fff;letter-spacing:.01em;text-transform:uppercase}
.fcap{position:absolute;left:740px;top:330px;width:130px;height:440px;border:6px solid #cfd6e2;border-radius:18px;padding:8px;transform-origin:50% 100%}
.capfill{position:absolute;left:8px;right:8px;bottom:8px;background:#cfd6e2;border-radius:8px}
.fbnum{position:absolute;left:930px;top:430px;font-weight:900;font-size:170px;color:#fff;line-height:1}
.fbsrc{position:absolute;left:0;right:0;top:900px;text-align:center;font-weight:600;font-size:20px;letter-spacing:.2em;color:#6e7685;text-transform:uppercase}
"""


def page(ctx, total):
    th = ctx.theme
    faces = "".join(f"@font-face{{font-family:'{f}';src:url('fonts/{p}');font-weight:{w}}}" for f, p, w in th.get("faces", []))
    css = font_css() + faces + CSS.replace("__Y__", ctx.accent) + th["css"].replace("__A__", ctx.accent)
    fdir = os.path.join(ctx.hf, "fonts"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(FONTS):
        shutil.copy(os.path.join(FONTS, f), fdir)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width={W}, height={H}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>{css}</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{W}" data-height="{H}">
{chr(10).join(ctx.els)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(ctx.js)}
window.__timelines["main"] = tl;
</script></body></html>"""


# ============================================================================== DEMO REEL
def demo(theme=None):
    P = lambda *a: os.path.join(ROOT, "projects", *a)
    hf = P("_motion_demo", theme, "hf")
    if os.path.isdir(hf):
        shutil.rmtree(hf)
    os.makedirs(hf)
    ctx = Ctx(hf, theme=theme)
    nt, db = P("next-time", "pool"), P("dutch-boatbuilder", "pool")
    nm = P("next-time", "media")
    pool = {r[0]: r[1] for r in json.load(open(P("dutch-boatbuilder", "pool", "index.json"), encoding="utf-8"))}
    E = lambda n: os.path.join(db, pool[n])
    seq = []
    t = 0.0

    def add(fn, d, *a, **k):
        nonlocal t
        fn(ctx, t, d, *a, **k); seq.append((fn.__name__, round(t, 2))); t += d

    add(chapter, 4.5, "1", "THE SINKING SHIP", "when a cargo ship|sinks on purpose")
    add(highlight_box, 4.0, os.path.join(nm, "shot_170.mp4"), "Why would a ship sink itself?")
    add(price_plate, 4.0, os.path.join(nm, "shot_202.mp4"), 100000, "One-way, 100-ft yacht")
    add(big_stat_roll, 4.5, os.path.join(nm, "shot_190.mp4"), 19, "YACHTS")
    add(typewriter_highlight, 5.0, os.path.join(nm, "shot_116.mp4"), "*Speed* is exactly what kills its *range.*", x=640, y=470, width=1100)
    add(spaced_title, 4.0, os.path.join(nm, "shot_157.mp4"), "The Atlantic Gap")
    add(photo_caption, 4.0, E(104), "A $2.6M ELLING E6")
    add(card_carousel, 6.5, [os.path.join(nt, "pl_gib_2.jpg"), os.path.join(nt, "pl_capeverde_1.jpg"), os.path.join(nt, "pl_barbados_0.jpg")], "paper")
    add(card_carousel, 6.0, [E(104), E(58), E(122), E(69)], "dark")
    add(bubbles, 4.0, os.path.join(nt, "nar_5.jpg"), E(126), "NORDHAVN 40", "PERSHING 9X")
    add(split_tag, 4.0, os.path.join(nm, "shot_119.mp4"), os.path.join(nm, "shot_128.jpg"), "380 NM vs 2,500 NM")
    add(callouts, 5.5, os.path.join(db, "pool", "tech_115_0.jpg") if os.path.exists(os.path.join(db, "pool", "tech_115_0.jpg")) else os.path.join(db, "tech_115_0.jpg"),
        [(1060, 450, 1300, 250, "Propeller"), (700, 500, 540, 300, "Rudder"), (1180, 520, 1420, 760, "Prop shaft")])
    add(fill_bar, 5.0, "Superyachts that can't cross alone", 90, "Illustrative figure")
    open(os.path.join(hf, "index.html"), "w", encoding="utf-8").write(page(ctx, t))
    json.dump(seq, open(os.path.join(hf, "..", "sequence.json"), "w"), indent=0)
    print(f"[motion] demo {t:.1f}s, {len(seq)} templates -> {hf}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["demo"]:
        demo(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)




# ---- REPORT theme (broad documentary / automobile report): studio/motion_report.py
from studio.motion_report import spec_card, stat_slam, section_title, press_clip, quote_wall, id_tag, spec_bars  # noqa: E402
from studio import motion_report as _rp  # noqa: E402
THEMES["report"] = _rp.THEME

# ---- AUTO theme (faithful copy of the user's car-report reference): studio/motion_auto.py
from studio.motion_auto import card_label, foot_number, step_title, quote_blur, article_page, title_card  # noqa: E402
from studio import motion_auto as _au  # noqa: E402
THEMES["auto"] = _au.THEME

# ---- CAPRAE theme (user's pick 2026-10-09): the AUTO close copy + press_clip and quote_wall exactly as in REPORT (orange)
def _caprae():
    rc = _rp.CSS
    keep = rc[rc.index(".rstage"):rc.index(".rfill")] + rc[rc.index(".pcam"):rc.index(".rid{")]
    faces = _au.THEME["faces"] + [f for f in _rp.THEME["faces"] if f[0] in ("Mono", "ISerif", "DMS")]
    return {"accent": _au.RED, "hl_h": "100%", "faces": faces, "css": _au.THEME["css"] + keep.replace("__A__", _rp.OR)}


THEMES["caprae"] = _caprae()

# ---- private house styles (kept off GitHub): loaded only if present on this computer
DEFAULT_THEME = "caprae"
try:
    from studio.motion_signal import *  # noqa: E402,F401,F403  (registers THEMES["signal"] + Signal v2 templates)
    DEFAULT_THEME = "signal"
except ImportError:
    pass
