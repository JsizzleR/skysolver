# SkySolver

A one-button math-copter game for macOS (and anywhere else Python runs).

Hold **SPACE** (or the mouse button) to climb; release to descend. A math
problem sits in the banner at the bottom of the screen, and balloons drift
in from the right carrying candidate answers. Fly into the balloon with the
**correct** answer, dodge the wrong ones and the storm clouds, keep off the
sea (ditching in the water costs a life), and grab
stars for bonus points. The whole game plays out over an open ocean —
rolling swells, sun glitter on the water, drifting islands, and a little
sailboat on the horizon. Clear five skies — each with its own palette, from
midday blue to starry night over a moonlit sea — and the speed, problem
range, and storm density rise as you go.

## Play

```sh
cd skysolver
.venv/bin/python skysolver.py
```

Or just double-click `SkySolver.command` in Finder.

If you're setting it up fresh on another machine:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python skysolver.py
```

(`pygame` is required; `numpy` is optional but powers the rich sound
effects — without it the game falls back to simple tones.)

## How it works

| Thing | Detail |
|---|---|
| Modes | Addition, Subtraction, Multiplication, Division, or Mixed |
| Difficulty | Breezy / Steady / Stormy — scales number ranges and speed |
| Levels | 5 skies × 5 correct answers each |
| Lives | 3 hearts; wrong balloons and storm clouds each cost one |
| Scoring | 100 × streak per correct answer (streak caps at ×5), +50 per star |

Division problems always have whole-number answers, and subtraction never
goes negative. Wrong-answer balloons carry plausible near-misses, not random
junk, so you actually have to do the math.

## Controls

- **SPACE / ↑ / left mouse** — hold to climb, release to sink
- **↑ ↓** — choose operation on the menu, **← →** — difficulty
- **ENTER** or **1–5** — start
- **M** — mute / unmute all sound (works anywhere)
- **ESC** — back to menu / quit

## Sound

Every sound effect is synthesized procedurally with numpy at startup — there
are no audio files:

- a looping **helicopter rotor** with a slow ~10 Hz "whop-whop" blade chop
  whose volume lifts as you climb (a tiled, seamless loop)
- a **thunderclap** when you hit a storm cloud (a bright crack rolling into a
  low rumble)
- a satisfying **whoosh + sparkle** when you catch the right answer (a rising
  sweep resolving to a major chord)
- a **splash** when the copter ditches in the sea
- a comedic **deflate/raspberry** for a wrong balloon

Press **M** to toggle all of it off.

## Testing

```sh
.venv/bin/python skysolver.py --smoke
```

Runs headless (no window or audio needed): verifies every generated problem
is arithmetically true across all operations, levels, and difficulties, then
drives the game through flight, water crashes, correct/wrong catches, cloud
hits, star pickups, level clears, the win screen, and game over — and exercises
the sound board (every effect, the rotor, and the mute toggle).

## Provenance

SkySolver is an original game *inspired by* the Flash-era "fly into the
right answer" genre of educational copter games (e.g. Mathcopter). It shares
the genre's core idea — one-button helicopter flight plus answer-catching —
but the name, code, artwork, sounds, level/scoring design, and twists
(streak multiplier, storm clouds, per-level ocean palettes) are all original.
All art is drawn with pygame primitives and all sound is synthesized from
scratch with numpy at runtime; the project contains no third-party assets.
