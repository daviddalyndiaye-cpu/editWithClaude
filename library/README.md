# library/ — your effect assets (not in git)

The renderer picks these up automatically by file name. They are not committed because they come from licensed asset packs. Add your own.

| Folder | Files | Used for |
|---|---|---|
| `library/sfx/` | `whoosh-*.wav`, `impact-*.wav`, `pop-*.wav`, `money-*.wav` | cut whooshes, stat impacts, pop-ins, cha-ching on money numbers |
| `library/fx/` | `burn-01.mp4` … (0.3 s light-leak / film-burn flashes, 1920x1080, **black background**) | flash on every 3rd cut (screen blend) |
| `library/bg/` | `bg1-*.mp4`, `bg2-*.mp4` … (16:9 looping grids / topographic lines, dark) | animated backdrop behind website-screenshot cards |

Without them the tool still works — just without sound effects, flashes or grid backdrops (`python -m studio.preflight` warns).
To make a flash from a light-leak clip with a grey base: `ffmpeg -i in.mp4 -an -vf "fps=30,scale=1920:1080,lutyuv=y='clip((val-126)*2.0,0,255)'" -c:v libx264 -crf 12 -g 1 -pix_fmt yuv420p library/fx/burn-01.mp4`
