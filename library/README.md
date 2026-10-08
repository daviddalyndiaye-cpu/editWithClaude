# library/ — your effect assets (not in git)

The renderer picks these up automatically by file name. They are not committed because they come from licensed asset packs. Add your own; the `tools/` scripts convert raw packs into the right format.

| Folder | Files | Used for | Import with |
|---|---|---|---|
| `library/sfx/` | `whoosh-*`, `impact-*`, `pop-*`, `money-*`, `riser-*`, `type-*` (.wav) | cut whooshes, stat impacts, sticker/card pop-ins, cha-ching on money numbers, a build-up riser into big stats (max 1 per 75 s), keyboard clicks on website cards | ffmpeg → wav |
| `library/fx/` | `burn-*.mp4` (blue/white light leaks), `film-*.mp4` (orange film burns): 0.33 s, 1920x1080, **black background** | flash on every 3rd cut (screen blend). `plan.burn_style`: `mix` (default) / `leak` / `film` | `python tools/import_burns.py [--prefix film] <folder>` |
| `library/fx/` | `rain-*.mp4` (falling money on black) | money rain behind money stats (max 1 per 60 s, `plan.money_rain: false` disables) | ffmpeg, 1080p, black bg |
| `library/bg/` | `bgN-*.mp4` dark loops, `bgN-color-*.mp4` bright grids (16:9, ~30 s) | animated backdrop behind website-screenshot cards. `plan.backdrops`: `all` (alternate) / `dark` / `color` | ffmpeg crop to 1920x1080 |
| `library/icons/` | transparent PNG stickers + `icons.json` (trigger words) | a sticker pops in (top-right) when the narrator says a trigger word; max 1 per 12 s (`plan.icon_gap`), `plan.icons: false` disables | `python tools/import_icons.py <folder>` (edit its MAP) |
| `library/stock/` | 1080p clips + `stock.json` (keywords) | fallback b-roll when online search finds nothing for a shot (each clip ≤ 2× per video) | `python tools/import_stock.py <folder>` (skips vertical + green-screen clips; review the result, fix keywords in `stock.json`) |

Without them the tool still works, just without those effects (`python -m studio.preflight` warns).
Vertical (9:16) pack assets are not usable for 16:9 videos; the import tools skip them.
