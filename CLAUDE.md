# CLAUDE.md

Guidance for working on SkySolver with Claude Code. This covers the
conventions and invariants that aren't obvious from the code; see `README.md`
for gameplay and install.

## Run & test

- Run the game: `.venv/bin/python skysolver.py`
- **Self-test (run before declaring any change done):**
  `.venv/bin/python skysolver.py --smoke`
  Headless (dummy SDL video/audio). It checks every generated math problem is
  arithmetically true across all ops/levels/difficulties, then drives the game
  through flight, water crashes, correct/wrong catches, cloud hits, star
  pickups, level clears, win, and game over, and exercises the sound board.
  When you add a feature, extend the smoke test to cover it.

## Hard invariant: no third-party assets

All art is drawn with pygame primitives; all sound is synthesized at runtime
with numpy in `sfx.py`. **Do not add image, audio, or font files** — generate
them in code instead. This keeps the project licensing-clean and dependency-light.

When adding a sound, write a generator in `sfx.py` and register it in
`GENERATORS`. Each generator must:

- be `def name(sr=SAMPLE_RATE): ...` returning a 1-D `numpy.int16` mono array
- synthesize from numpy only; seed any RNG with a fixed constant (builds stay
  deterministic)
- normalize to ~0.7 of full scale (no clipping, no NaN/Inf), and be vectorized
- for a looping sound (e.g. `rotor_loop`), loop seamlessly — build an integer
  number of periods and `np.tile`, so `sample[0]` flows out of `sample[-1]`

`skysolver.py` turns each array into a pygame Sound and falls back to simple
tones if numpy/`sfx.py` is unavailable, so audio must degrade gracefully.

## Provenance

SkySolver is an *original homage* to the Flash-era "fly into the right answer"
copter genre (e.g. Mathcopter), not a clone. Don't import that game's name,
art, audio, or assets — keep new work original.

## Environment

- macOS; the venv uses Homebrew `python3.12`. Deps: `pygame`, `numpy`
  (`requirements.txt`).
- `SkySolver.command` and the venv paths are relative to the project dir —
  run from the project root.

## Style

Match the surrounding code: standard-library + pygame/numpy, terse helpers,
comments only for non-obvious constraints (e.g. why a buffer must be periodic).
