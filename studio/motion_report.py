"""REPORT theme - broad documentary / automobile-report style (inspired by the user's car-report reference, rebuilt in our own look).

Look: graphite "technical drawing" stage (fine grid, ruler ticks, crop marks), safety-orange accent, amber highlighter,
Anton for heavy labels and numbers, Instrument Serif italic for quotes, DM Serif for press clippings, JetBrains Mono tags.

Templates (all  T(ctx, t0, dur, **params), same rules as studio/motion.py):
  spec_card     footage/photo on a floating card over the stage, heavy label (+ count-up) under it
  stat_slam     full-frame footage, big number bottom-left counting up, orange bar, mono label
  section_title kicker ("STEP 03") + heavy title, outlined ghost number, visible from frame 0
  press_clip    self-built news clipping on paper, highlighter sweeps over the lines that matter, camera pushes in
  quote_wall    footage turns grey + soft, serif quote reveals word by word, mono source
  id_tag        lower-left name tag over footage (orange slab, name, role)
  spec_bars     horizontal comparison bars, one highlighted, values count up

python -m studio.motion_report   -> projects/_motion_demo/report/hf  (demo reel)
"""
import json, os

W, H = 1920, 1080
OR = "#FF5B1F"


def _m():
    from studio import motion as M
    return M


def _is_vid(p):
    return p.lower().endswith((".mp4", ".mov", ".webm"))


STAGE = ('<div class="rstage"><div class="rgrid"></div><div class="rrule rt"></div><div class="rrule rl"></div>'
         '<div class="rvig"></div></div>')


def _media_box(ctx, src, t0, dur, x, y, w, h, track=11, radius=18, move=1.06):
    """A video or image clipped into a rounded rect at (x,y,w,h). Returns the element id (the box)."""
    rel = ctx.media(src); eid = ctx.uid("rb")
    box = f"position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;overflow:hidden;border-radius:{radius}px"
    if _is_vid(src):
        # a top-level video clip (the renderer only times top-level media); the box itself is the rounded frame
        ctx.els.append(f'<video id="{eid}" class="clip" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{track}" '
                       f'data-media-start="0.3" data-volume="0" muted playsinline src="{rel}" style="{box};object-fit:cover"></video>')
    else:
        ctx.els.append(f'<div id="{eid}" class="clip" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-track-index="{track}" style="{box}">'
                       f'<img id="{eid}v" class="rfill" src="{rel}"/></div>')
        ctx.js.append(f'tl.fromTo("#{eid}v",{{scale:1}},{{scale:{move},duration:{dur:.3f},ease:"none"}},{t0:.3f});')
    return eid


def _count(eid, sel, value, t, d=1.1, dec=None, prefix="", suffix=""):
    value = float(value)                      # a non-number here would be a JS syntax error that kills the whole timeline
    value = int(value) if value.is_integer() else value
    dec = (len(str(value).split(".")[1].rstrip("0")) if "." in str(value) else 0) if dec is None else dec
    return (f'(function(){{const e=document.querySelector("#{eid} {sel}");const o={{v:0}};'
            f'tl.to(o,{{v:{value},duration:{d},ease:"power3.out",onUpdate:function(){{e.textContent="{prefix}"+'
            f'o.v.toLocaleString("en-US",{{minimumFractionDigits:{dec},maximumFractionDigits:{dec}}})+"{suffix}";}}}},{t:.3f});'
            f'e.textContent="{prefix}"+(0).toFixed({dec})+"{suffix}";}})();')


# ------------------------------------------------------------------------------------------------ spec card
def spec_card(ctx, t0, dur, media, label, value=None, prefix="", suffix="", fig=""):
    """Graphite stage; the footage/photo rises on a card; crop marks snap to its corners; the heavy label lands under it.
    value: if set, the label is  prefix + counting number + suffix  (label text then goes small above as the caption)."""
    M = _m()
    st = ctx.clip(STAGE, t0, dur, 10)
    x, y, w, h = 400, 120, 1120, 630
    box = _media_box(ctx, media, t0, dur, x, y, w, h, track=11)
    big = f'<span class="rnum">{M.esc(prefix)}0{M.esc(suffix)}</span>' if value is not None else M.esc(label)
    cap = f'<div class="rcap">{M.esc(label)}</div>' if value is not None else ""
    marks = "".join(f'<i class="cm c{k}"></i>' for k in range(4))
    ov = ctx.clip(f'<div class="cmarks" style="left:{x - 22}px;top:{y - 22}px;width:{w + 44}px;height:{h + 44}px">{marks}</div>'
                  + (f'<div class="rfig" style="left:{x}px;top:{y - 58}px">{M.esc(fig)}</div>' if fig else "")
                  + f'<div class="rlab">{cap}<div class="rbig">{big}</div></div>', t0, dur, 12)
    a = t0 + 0.15
    ctx.js.append(f'tl.fromTo("#{box}",{{y:70,scale:0.94,opacity:0,clipPath:"inset(30% 0 30% 0 round 18px)"}},'
                  f'{{y:0,scale:1,opacity:1,clipPath:"inset(0% 0 0% 0 round 18px)",duration:0.7,ease:"expo.out"}},{a:.3f});'
                  f'tl.fromTo("#{ov} .cmarks",{{scale:1.12,opacity:0}},{{scale:1,opacity:1,duration:0.5,ease:"power3.out"}},{a + 0.3:.3f});'
                  f'tl.fromTo("#{ov} .rfig",{{opacity:0,x:-20}},{{opacity:1,x:0,duration:0.4,ease:"power3.out"}},{a + 0.45:.3f});'
                  f'tl.fromTo("#{ov} .rbig",{{yPercent:110}},{{yPercent:0,duration:0.55,ease:"expo.out"}},{a + 0.5:.3f});'
                  f'tl.fromTo("#{ov} .rcap",{{opacity:0,y:10}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{a + 0.6:.3f});')
    if value is not None:
        ctx.js.append(_count(ov, ".rnum", value, a + 0.6, prefix=prefix, suffix=suffix))
    for sel in (f"#{box}", f"#{ov}"):
        M.exit_fade(ctx, sel, t0 + dur, d=0.3)


# ------------------------------------------------------------------------------------------------ stat slam
def stat_slam(ctx, t0, dur, bg, value, label, prefix="", suffix=""):
    """Full-frame footage; a dark ramp rises from the bottom; the number counts up bottom-left with an orange bar under it."""
    M = _m()
    b = ctx.bg(bg, t0, dur)
    ov = ctx.clip(f'<div class="rramp"></div><div class="rslam"><div class="rsl">{M.esc(label)}</div>'
                  f'<div class="rsn"><span class="rnum">{M.esc(prefix)}0{M.esc(suffix)}</span></div><i class="rbar"></i></div>', t0, dur, 12)
    a = t0 + 0.35
    ctx.js.append(f'tl.fromTo("#{ov} .rramp",{{opacity:0}},{{opacity:1,duration:0.5,ease:"power2.out"}},{t0 + 0.1:.3f});'
                  f'tl.fromTo("#{ov} .rsn",{{yPercent:105}},{{yPercent:0,duration:0.6,ease:"expo.out"}},{a:.3f});'
                  f'tl.fromTo("#{ov} .rbar",{{scaleX:0}},{{scaleX:1,duration:0.7,ease:"expo.out"}},{a + 0.25:.3f});'
                  f'tl.fromTo("#{ov} .rsl",{{opacity:0,x:-24}},{{opacity:1,x:0,duration:0.45,ease:"power3.out"}},{a + 0.1:.3f});')
    ctx.js.append(_count(ov, ".rnum", value, a + 0.1, d=1.2, prefix=prefix, suffix=suffix))
    M.exit_fade(ctx, f"#{ov}", t0 + dur, d=0.3)


# ------------------------------------------------------------------------------------------------ section title
def section_title(ctx, t0, dur, kicker, title, num="", bg=None):
    """Stage (or heavily darkened footage) visible from frame 0; orange kicker; heavy title reveals line by line through masks;
    an outlined ghost number sits on the right; an orange rule draws under the title."""
    M = _m()
    if bg:
        b = ctx.bg(bg, t0, dur); ctx.dim(b, t0, 0.28, gray=0.6, d=0.01)
        ctx.clip('<div class="rgrid" style="opacity:.55"></div><div class="rvig"></div>', t0, dur, 10)
    else:
        ctx.clip(STAGE, t0, dur, 10)
    lines = "".join(f'<div class="rtm"><div class="rtl">{M.esc(l)}</div></div>' for l in title.split("|"))
    ov = ctx.clip((f'<div class="rghost">{M.esc(num)}</div>' if num else "")
                  + f'<div class="rsec"><div class="rkick"><i></i>{M.esc(kicker)}</div>{lines}<i class="rrule2"></i></div>', t0, dur, 12)
    a = t0 + 0.12
    ctx.js.append(f'tl.fromTo("#{ov} .rghost",{{opacity:0,x:80}},{{opacity:1,x:0,duration:1.2,ease:"expo.out"}},{a:.3f});'
                  f'tl.fromTo("#{ov} .rkick",{{opacity:0,x:-30}},{{opacity:1,x:0,duration:0.45,ease:"power3.out"}},{a + 0.1:.3f});'
                  f'tl.fromTo("#{ov} .rtl",{{yPercent:110}},{{yPercent:0,duration:0.65,ease:"expo.out",stagger:0.1}},{a + 0.25:.3f});'
                  f'tl.fromTo("#{ov} .rrule2",{{scaleX:0}},{{scaleX:1,duration:0.8,ease:"expo.out"}},{a + 0.55:.3f});')
    M.exit_fade(ctx, f"#{ov} .rsec", t0 + dur, d=0.3, y=-12)


# ------------------------------------------------------------------------------------------------ press clipping
def press_clip(ctx, t0, dur, outlet, headline, lines, hl=(), date="", img=None):
    """A news clipping we typeset ourselves (no screenshot needed): paper card, masthead, headline, optional photo, body lines.
    The highlighter sweeps over the lines in `hl` one after another while the camera pushes toward the first one."""
    M = _m()
    ctx.clip(STAGE, t0, dur, 10)
    body = "".join(f'<div class="pl{" phl" if k in hl else ""}"><span>{M.esc(l)}</span></div>' for k, l in enumerate(lines))
    photo = f'<div class="pimg"><img src="{ctx.media(img)}"/></div>' if img else ""
    ov = ctx.clip(f'<div class="pcam"><div class="paper"><div class="pmast"><b>{M.esc(outlet)}</b><span>{M.esc(date)}</span></div>'
                  f'<div class="phead">{M.esc(headline)}</div>{photo}<div class="pbody">{body}</div></div></div>', t0, dur, 12)
    first = min(hl) if hl else 0
    oy = 330 + (250 if img else 0) + first * 50
    ctx.js.append(f'tl.fromTo("#{ov} .paper",{{y:700,rotation:4}},{{y:0,rotation:-1.5,duration:0.8,ease:"expo.out"}},{t0 + 0.1:.3f});'
                  f'tl.fromTo("#{ov} .pcam",{{scale:1}},{{scale:1.16,transformOrigin:"960px {oy}px",duration:{dur - 1.0:.2f},ease:"power1.inOut"}},{t0 + 0.9:.3f});')
    for n, k in enumerate(sorted(hl)):
        ctx.js.append(f'tl.fromTo("#{ov} .pl:nth-child({k + 1}) span",{{backgroundSize:"0% 100%"}},{{backgroundSize:"100% 100%",duration:0.6,ease:"power2.inOut"}},'
                      f'{t0 + 1.1 + n * 0.55:.3f});')
    M.exit_fade(ctx, f"#{ov}", t0 + dur, d=0.3)


# ------------------------------------------------------------------------------------------------ quote wall
def quote_wall(ctx, t0, dur, bg, quote, source=""):
    """Footage turns grey, soft and dark; a big orange quote mark; the serif quote reveals word by word; mono source."""
    M = _m()
    b = ctx.bg(bg, t0, dur)
    ctx.js.append(f'tl.fromTo("#{b}",{{filter:"grayscale(0) blur(0px) brightness(1)"}},{{filter:"grayscale(1) blur(7px) brightness(.32)",duration:0.7,ease:"power2.out"}},{t0:.3f});')
    words = "".join(f'<span class="qw">{M.esc(w)}</span> ' for w in quote.split())
    ov = ctx.clip(f'<div class="rq"><div class="rqm">&#8220;</div><div class="rqt">{words}</div>'
                  f'<div class="rqs"><i></i>{M.esc(source)}</div></div>', t0, dur, 12)
    n = len(quote.split()); per = min(0.09, 1.6 / max(n, 1))
    ctx.js.append(f'tl.fromTo("#{ov} .rqm",{{opacity:0,scale:0.6}},{{opacity:1,scale:1,duration:0.5,ease:"back.out(2)"}},{t0 + 0.4:.3f});'
                  f'tl.fromTo("#{ov} .qw",{{opacity:0,y:18}},{{opacity:1,y:0,duration:0.45,ease:"power3.out",stagger:{per:.3f}}},{t0 + 0.6:.3f});'
                  f'tl.fromTo("#{ov} .rqs",{{opacity:0,y:10}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{t0 + 0.8 + n * per:.3f});')
    M.exit_fade(ctx, f"#{ov}", t0 + dur, d=0.3)


# ------------------------------------------------------------------------------------------------ id tag
def id_tag(ctx, t0, dur, name, role=""):
    """Lower-left tag over footage: an orange slab wipes in, the name slides out of it, the role types under it."""
    M = _m()
    ov = ctx.clip(f'<div class="rid"><i class="ridb"></i><div class="ridn">{M.esc(name)}</div><div class="ridr">{M.esc(role)}</div></div>', t0, dur, 13)
    ctx.js.append(f'tl.fromTo("#{ov} .ridb",{{scaleY:0}},{{scaleY:1,duration:0.35,ease:"expo.out"}},{t0 + 0.1:.3f});'
                  f'tl.fromTo("#{ov} .ridn",{{clipPath:"inset(0 100% 0 0)"}},{{clipPath:"inset(0 0% 0 0)",duration:0.55,ease:"expo.out"}},{t0 + 0.25:.3f});'
                  f'tl.fromTo("#{ov} .ridr",{{opacity:0,x:-14}},{{opacity:1,x:0,duration:0.4,ease:"power3.out"}},{t0 + 0.5:.3f});')
    M.exit_fade(ctx, f"#{ov}", t0 + dur, d=0.3, y=10)


# ------------------------------------------------------------------------------------------------ spec bars
def spec_bars(ctx, t0, dur, title, rows, highlight=0, unit=""):
    """rows: [(label, value), ...]. Bars grow in order (scaled to the max), the highlighted one is orange, values count up."""
    M = _m()
    ctx.clip(STAGE, t0, dur, 10)
    mx = max(v for _, v in rows) or 1
    rws = "".join(f'<div class="rbr{" rbh" if k == highlight else ""}"><div class="rbl">{M.esc(l)}</div>'
                  f'<div class="rbt"><i class="rbf" style="width:{1000 * v / mx:.0f}px"></i></div><div class="rbv"><span class="rv{k}">0</span>{M.esc(unit)}</div></div>'
                  for k, (l, v) in enumerate(rows))
    ov = ctx.clip(f'<div class="rbars"><div class="rbtitle">{M.esc(title)}</div>{rws}</div>', t0, dur, 12)
    a = t0 + 0.2
    ctx.js.append(f'tl.fromTo("#{ov} .rbtitle",{{yPercent:60,opacity:0}},{{yPercent:0,opacity:1,duration:0.5,ease:"expo.out"}},{a:.3f});'
                  f'tl.fromTo("#{ov} .rbr",{{opacity:0,x:-30}},{{opacity:1,x:0,duration:0.45,ease:"power3.out",stagger:0.12}},{a + 0.3:.3f});')
    for k, (_, v) in enumerate(rows):
        b = a + 0.5 + k * 0.18
        ctx.js.append(f'tl.fromTo("#{ov} .rbr:nth-of-type({k + 2}) .rbf",{{scaleX:0}},{{scaleX:1,duration:0.9,ease:"expo.out"}},{b:.3f});')
        ctx.js.append(_count(ov, f".rv{k}", v, b, d=0.9))
    M.exit_fade(ctx, f"#{ov}", t0 + dur, d=0.3)


CSS = """
.rstage{position:absolute;inset:0;background:#15171A}
.rgrid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px),
  linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px);
  background-size:24px 24px,24px 24px,120px 120px,120px 120px}
.rrule{position:absolute;opacity:.55}
.rrule.rt{left:0;right:0;top:0;height:22px;background:repeating-linear-gradient(90deg,#6b6f76 0 2px,transparent 2px 24px),repeating-linear-gradient(90deg,#9aa0a8 0 2px,transparent 2px 120px);background-size:auto 10px,auto 22px;background-repeat:repeat-x}
.rrule.rl{top:0;bottom:0;left:0;width:22px;background:repeating-linear-gradient(0deg,#6b6f76 0 2px,transparent 2px 24px),repeating-linear-gradient(0deg,#9aa0a8 0 2px,transparent 2px 120px);background-size:10px auto,22px auto;background-repeat:repeat-y}
.rvig{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 42%,transparent 40%,rgba(0,0,0,.6) 100%)}
.rfill{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover}
.cmarks{position:absolute}.cm{position:absolute;width:34px;height:34px;border-color:__A__;border-style:solid;border-width:0}
.cm.c0{left:0;top:0;border-left-width:4px;border-top-width:4px}.cm.c1{right:0;top:0;border-right-width:4px;border-top-width:4px}
.cm.c2{left:0;bottom:0;border-left-width:4px;border-bottom-width:4px}.cm.c3{right:0;bottom:0;border-right-width:4px;border-bottom-width:4px}
.rfig{position:absolute;font-family:'Mono';font-weight:700;font-size:22px;letter-spacing:.14em;color:__A__;text-transform:uppercase}
.rlab{position:absolute;left:0;right:0;top:800px;text-align:center}
.rcap{font-family:'Mono';font-weight:600;font-size:24px;letter-spacing:.16em;color:#A9AEB6;text-transform:uppercase;margin-bottom:6px}
.rbig{font-family:'Anton';font-size:108px;line-height:1.08;color:#F3EFE6;letter-spacing:.01em;text-transform:uppercase;display:inline-block;overflow:hidden}
.rbig{clip-path:inset(0 0 0 0)}
.rramp{position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(10,11,13,.92) 100%)}
.rslam{position:absolute;left:120px;bottom:120px}
.rsl{font-family:'Mono';font-weight:700;font-size:28px;letter-spacing:.14em;color:#F3EFE6;text-transform:uppercase;margin-bottom:4px}
.rsl::before{content:"";display:inline-block;width:14px;height:14px;background:__A__;margin-right:14px;vertical-align:1px}
.rsn{font-family:'Anton';font-size:230px;line-height:1.02;color:#F3EFE6;overflow:hidden}.rslam{clip-path:inset(-20px -600px 0 -20px)}
.rbar{display:block;height:12px;width:100%;background:__A__;transform-origin:0 50%;margin-top:8px}
.rghost{position:absolute;right:90px;top:50%;transform:translateY(-52%);font-family:'Anton';font-size:820px;line-height:1;color:transparent;
  -webkit-text-stroke:4px rgba(255,91,31,.45)}
.rsec{position:absolute;left:150px;top:50%;transform:translateY(-50%)}
.rkick{font-family:'Mono';font-weight:700;font-size:32px;letter-spacing:.2em;color:__A__;text-transform:uppercase;margin-bottom:18px}
.rkick i{display:inline-block;width:18px;height:18px;background:__A__;margin-right:18px;vertical-align:1px}
.rtm{overflow:hidden}.rtl{font-family:'Anton';font-size:150px;line-height:1.06;color:#F3EFE6;text-transform:uppercase;letter-spacing:.005em}
.rrule2{display:block;width:420px;height:10px;background:__A__;margin-top:26px;transform-origin:0 50%}
.pcam{position:absolute;inset:0}
.paper{position:absolute;left:410px;top:110px;width:1100px;background:#F4F1EA;padding:46px 60px 56px;box-shadow:0 50px 100px rgba(0,0,0,.6);border-radius:3px}
.pmast{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid #1d1d1d;padding-bottom:12px;margin-bottom:22px}
.pmast b{font-family:'DMS';font-weight:400;font-size:40px;color:#141414}.pmast span{font-family:'Mono';font-size:20px;color:#6d6a63;letter-spacing:.08em;text-transform:uppercase}
.phead{font-family:'DMS';font-size:58px;line-height:1.1;color:#111;margin-bottom:22px}
.pimg{height:250px;overflow:hidden;margin-bottom:22px}.pimg img{width:100%;height:100%;object-fit:cover;filter:saturate(.85)}
.pl{font-family:'InterV';font-weight:400;font-size:30px;line-height:50px;color:#2b2a27}
.pl span{background-image:linear-gradient(transparent 12%,rgba(255,197,61,.9) 12%,rgba(255,197,61,.9) 88%,transparent 88%);background-repeat:no-repeat;background-size:0% 100%;padding:0 2px}
.rq{position:absolute;left:220px;right:220px;top:50%;transform:translateY(-50%);text-align:center}
.rqm{font-family:'DMS';font-size:260px;line-height:.6;color:__A__;height:120px}
.rqt{font-family:'ISerif';font-style:italic;font-size:80px;line-height:1.18;color:#F3EFE6}.qw{display:inline-block}
.rqs{margin-top:34px;font-family:'Mono';font-weight:700;font-size:26px;letter-spacing:.16em;color:__A__;text-transform:uppercase}
.rqs i{display:inline-block;width:60px;height:3px;background:__A__;vertical-align:8px;margin-right:18px}
.rid{position:absolute;left:110px;bottom:110px;padding-left:28px}
.ridb{position:absolute;left:0;top:0;bottom:0;width:10px;background:__A__;transform-origin:50% 100%}
.ridn{font-family:'Anton';font-size:64px;line-height:1.1;color:#F3EFE6;background:rgba(14,15,17,.86);padding:6px 24px 10px;text-transform:uppercase;letter-spacing:.01em}
.ridr{display:inline-block;margin-top:8px;font-family:'Mono';font-weight:600;font-size:24px;letter-spacing:.12em;color:#0E0F11;background:#F3EFE6;padding:6px 16px;text-transform:uppercase}
.rbars{position:absolute;left:170px;top:150px;width:1580px}
.rbtitle{font-family:'Anton';font-size:96px;color:#F3EFE6;text-transform:uppercase;margin-bottom:46px}
.rbr{display:flex;align-items:center;height:118px;border-top:1px solid rgba(255,255,255,.08)}
.rbl{width:330px;font-family:'Mono';font-weight:700;font-size:30px;letter-spacing:.08em;color:#A9AEB6;text-transform:uppercase}
.rbt{width:1020px}.rbf{display:block;height:46px;background:#4A4F57;transform-origin:0 50%}
.rbv{font-family:'Anton';font-size:64px;color:#A9AEB6;margin-left:10px;white-space:nowrap}
.rbh .rbl{color:#F3EFE6}.rbh .rbf{background:__A__}.rbh .rbv{color:#F3EFE6}
/* the generic overlays (lower third, stat plate, pill, list, highlight, chapter) in the REPORT look */
.lk3{background:__A__;color:#0E0F11;border-radius:0;font-family:'Mono'}
.lx3{font-family:'Anton';font-weight:400;font-size:62px;letter-spacing:.01em;text-transform:uppercase;background:rgba(14,15,17,.86);border:0;border-left:10px solid __A__;border-radius:0}
.ls3{background:rgba(14,15,17,.86);border:0;border-left:10px solid __A__;border-radius:0}
.li3{font-family:'Anton';font-weight:400;text-transform:uppercase;font-size:48px;letter-spacing:.01em}.li3 i{border-radius:0;background:__A__;box-shadow:none}
.pill3{background:__A__;color:#0E0F11;border-radius:0;font-family:'Mono'}
.plate{background:rgba(14,15,17,.86);border:0;border-bottom:10px solid __A__;border-radius:0}
.pv{font-family:'Anton';font-size:150px;letter-spacing:.01em}.pfx{font-size:110px;color:__A__}.plab{font-family:'Mono';color:#F3EFE6}
.hlbox{background:__A__;border-radius:0}.hlt{font-family:'Anton';font-weight:400;font-size:56px;color:#0E0F11;text-transform:uppercase;letter-spacing:.01em}
.digits{font-family:'Anton'}.bword{font-family:'Anton';color:__A__}
.twbox{font-family:'InterV';font-weight:800}.hlw b{font-family:'ISerif';font-style:italic;font-weight:400;font-size:74px;color:#0E0F11}
.sptitle{font-family:'Anton';letter-spacing:.06em}
.chbg{background:#15171A;background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);background-size:24px 24px}
.ghost{font-family:'Anton';color:transparent;-webkit-text-stroke:3px rgba(255,91,31,.25)}
.chtitle{font-family:'Anton';font-size:160px;text-transform:uppercase}.chsub{font-family:'Mono';color:__A__;font-size:28px;letter-spacing:.14em}
"""

THEME = {"accent": OR, "hl_h": "100%",
         "faces": [("Anton", "Anton-Regular.ttf", 400), ("Mono", "JetBrainsMono.ttf", "100 800"), ("InterV", "Inter.ttf", "100 900"),
                   ("ISerif", "InstrumentSerif-Italic.ttf", 400), ("DMS", "DMSerifDisplay-Regular.ttf", 400)],
         "css": "html,body{font-family:'InterV',sans-serif}" + CSS}


def demo():
    """python -m studio.motion_report  -> projects/_motion_demo/report/hf/index.html"""
    import shutil
    M = _m()
    R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hf = os.path.join(R, "projects", "_motion_demo", "report", "hf")
    shutil.rmtree(hf, ignore_errors=True); os.makedirs(hf)
    ctx = M.Ctx(hf, theme="report")
    S = lambda f: os.path.join(R, "projects", "_motion_demo", "report_src", f)
    t = 0.0; seq = []

    def add(fn, d, *a, **k):
        nonlocal t
        fn(ctx, t, d, *a, **k); seq.append((fn.__name__, round(t, 2))); t += d
    add(section_title, 4.5, "Part 01", "The invisible|killer", num="01")
    add(spec_card, 4.5, S("truck_front.mp4"), "Real-world mileage", value=15, suffix=" MPG", fig="Fig. 02  —  Pickup, towing")
    add(spec_card, 4.0, S("grille_still.jpg"), "2.7L Twin-turbo V6", fig="Fig. 03  —  Engine bay")
    add(stat_slam, 4.5, S("lot_air.mp4"), 127000, "Vehicles recalled")
    add(stat_slam, 4.0, S("grille.mp4"), 70000, "Sticker price", prefix="$")
    add(press_clip, 6.5, "Automotive Ledger", "Maker expands V-6 engine recall to 127,000 more trucks",
        ["Federal regulators said on Tuesday that machining debris left", "inside the engine during manufacturing can damage the",
         "main bearings, which may lead to engine failure while driving.", "Owners will be notified by mail; dealers will inspect",
         "and, if necessary, replace the engine at no cost."], hl=(1, 2), date="Oct 2026", img=S("truck_still.jpg"))
    add(quote_wall, 5.5, S("mech_c.mp4"), "Thinner oils, tighter tolerances and harder bearings are all part of the problem.",
        "Independent mechanic, 30 years")
    ctx.bg(S("mech_c.mp4"), t, 3.5, track=4)               # footage first: later DOM elements draw on top
    add(id_tag, 3.5, "Dave Morales", "Independent mechanic")
    add(spec_bars, 5.5, "Horsepower per litre", [("3.5L V6", 126), ("2.7L V6", 120), ("5.0L V8", 96), ("6.2L V8", 68)], highlight=1, unit=" HP")
    add(section_title, 4.0, "Step 03", "Cut your oil|interval in half", num="03", bg=S("engine_c.mp4"))
    open(os.path.join(hf, "index.html"), "w", encoding="utf-8").write(M.page(ctx, t))
    json.dump(seq, open(os.path.join(hf, "..", "sequence.json"), "w"), indent=0)
    print(f"[report] demo {t:.1f}s, {len(seq)} templates -> {hf}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    demo()
