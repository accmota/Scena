# Sound Design

`play_sound` returns the same `Handle` as `after` / tween. **`Sound`** is a
material (like `Sheet` / `Gradient`) — it never places itself. **Happy path** —
pick one row. Hub: [Scena Design.md](Scena%20Design.md). Ownership:
[Actors Design.md](Actors%20Design.md). Effect-stack idiom:
[Effect Handles.md](Effect%20Handles.md). Author catalog:
[API Guide](../docs/en/guide/index.html#som).

Today’s baseline — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Verb / material / Handle | [Surface](#surface) |
| Mode / entity / game / scene; what stops when the owner ends | [Ownership](#ownership) |
| Mixer / threads / limiter | [Mixer](#mixer) |
| Master bus | [Master](#master) |
| Missing files / banner | [Assets](#assets) |
| No miniaudio (Python 3.15, ARM) / silent install | [No miniaudio](#no-miniaudio) |
| Analysis / mic / record / effects | [Analysis](#analysis), [Microphone](#microphone), [Effects](#effects) |
| `@=` / `@when` on a level | [Levels as formula sources](#levels-as-formula-sources) |
| Locating code | [Router](#router) |

## Use

1. Pick one jump-box row.
2. Read that section only. Treat fences there as current constraints.
3. Open **Start** in the router if the section is not enough.
4. Stop.

## Router

| Need | Start | Also | Design (if needed) |
| --- | --- | --- | --- |
| `play_sound` / `Sound` / `audio` | `audio.py` | `process.py` (`Handle`) | this file |
| Mix / limiter / pitch resample / tails | `audio_mixer.py` | `audio_effects.py` (`_tail_seconds`) | this file |
| Capture | `audio_capture.py` | `audio.py` (`play_sound(mic)`) | this file |
| Level as a formula source | `level_source.py` | `state.py` (`_formula_source_of`), `orchestration.py` (`_simulate_frame`) | this file |
| `LowPass` / `Wavefold` / bake | `audio_effects.py` | `audio.py` (`Sound.bake`) | this file |
| Banner warning severity | `process.py` (`report_author_warning`) | `orchestration.py` | [Actors Design.md](Actors%20Design.md#protections) |

**Do not slurp:** `audio.py`, `audio_mixer.py`, `process.py`.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `Sound("x.wav")` | a material | a play |
| `Sound.effects` | does not exist | use `h.effects` live, or `Sound.bake(...)` |
| `fade_out` | ramp to 0 and **stop** (`on_done` fires) | `.cancel()` (no `on_done`); no Echo/Reverb tail |
| `fade_to(0)` | silent, still ticking | `fade_out` |
| `audio.volume = 0` | master mute; Handles keep running | cancelling voices |
| `Microphone()` | capture + analysis + `record` | a monitor (`play_sound(mic)`); a device picker |
| `clip` right after `record()` | a `Sound` still being made | playable — `mic.stop()` or `await` first |
| `mic.stop()` | ends the take; the mic stays open | `mic.close()` (releases the device) |
| monitor output | wet (`mic.effects`) | the recording (always dry) |
| `pitch=` on a mic monitor | ignored (file voices only) | live transpose (not in v1) |
| `name=` replace | cut (5 ms de-click); with `crossfade=` a ramp, still a cut (no `on_done`) | `crossfade=` (opt-in; requires `name=`) |
| `crossfade=0` | named-slot cut (same as omitting it) | a fade that starts at silence |
| `loops="forever"` | never `on_done`; stop with `.cancel()` | a `loop=True` boolean (doesn’t exist) |
| owner ends (destroy / mode leave / act change) | a sound that ends by itself **finishes**; a forever loop, named slot or paused sound is cut | "everything the owner started stops" |
| a cut | ~5 ms ramp to silence, no tail, no `on_done` | a fade (`fade_out`) |

## Surface

```python
play_sound("laser.wav")
h = play_sound("laser.wav", volume=0.6, pan=0.0, pitch=1.0, loops=1)
play_sound("theme.mp3", name="music", loops="forever", crossfade=1.0)
laser = Sound("laser.wav", volume=0.7)   # does not play
crunch = laser.bake(Distortion(), transpose=3)
play_sound(crunch)
```

Same `Handle` class as `after` / tween — `.done` / `.cancelled` / `.paused` /
`.elapsed` / `.remaining` / `.cancel()` / `.pause()` / `.resume()` / `await h` /
`on_done=` / `then=` / `name=` are free. `.remaining` is seconds left in the clip
(plus Echo/Reverb tail while effects are on), or seconds to the next loop while
looping. Sound-only attributes (`.volume` / `.pan` / `.pitch` / `.fade_to` /
`.fade_out` / `.level` / `.spectrum` / `.effects`) raise `AttributeError` with a
hint on a non-sound handle — same precedent as `.velocity` on `after`.

- `h.pause()` / `h.resume()` hold the voice on the mixer (cursor / effects /
  Echo-Reverb drain frozen; silence in the mix) **and** freeze an in-flight
  `fade_to` / `fade_out` on that Handle. Not the same as `audio.muted`
  (master mute — Handles keep running). `on_done` does not run on pause,
  including a fade that would otherwise have finished. `.cancel()` also
  cancels that fade tween.
- `loops=`: `1` (default), integer `N`, or `"forever"` — same spelling as
  `move_along` / `sprite.play`. `"forever"` never fires `on_done`.
- `name=`: named slot **replaces** (a cut, same as `after(..., name=)`).
  `crossfade=` is the opt-in smooth swap and **only works with `name=`**.
  It must be finite and `>= 0` (`ValueError` otherwise). **`crossfade=0`**
  does not ramp: the outgoing voice is cut (no `on_done`) and the new voice
  starts at its volume. Only `crossfade > 0` fades the old voice out and
  the new voice in from silence. Either way the old voice's end is a cut by
  the slot: no `on_done`, no `then=` (`Handle._ramp_out(natural=False)`; the
  public `fade_out` is the natural end). Before 2026-10-21 a crossfade used
  `fade_out`, so a replaced `forever` loop ran its `on_done` (persona probes
  R5-1). An explicit `fade_in=` still wins for the
  incoming ramp.
- Fades are author-requested only. A cut (`.cancel()`, `name=` replace, an
  owner ending under a sound that would not end by itself) is not a fade: the
  mixer only de-clicks it (~5 ms ramp, [Mixer](#mixer)). For a longer ramp the
  author writes `fade_in=` / `.fade_out()` / `crossfade=`.
- `.fade_out(time=)` ramps to silence and **stops** (natural end → `on_done`);
  no effect tail after an author fade-to-stop. `.fade_to(0)` only ramps.
  A new fade on a voice with a fade in flight retargets it (last wins, no
  warning; it warned from the scheduler's fallback until 2026-10-23).
  `time=` must be finite and `>= 0` (`ValueError` otherwise), same rule as
  any other tween.
- `.volume` is unbounded above 1.0 but is a **magnitude**: negative raises
  `ValueError` (it used to flip phase silently — a sign typo, never a mix
  choice; [Scena Design — Numbers and signs](Scena%20Design.md#numbers-and-signs)).
  It must be **finite** — `nan` / `inf` raise `ValueError`, a non-number
  raises `TypeError` — on `play_sound`, `Sound`, `h.volume`, `fade_to`,
  and `audio.volume`. The *master* mix is
  soft-limited, not each voice. A non-finite sample that still reaches the
  mixer is treated as silence so one bad value cannot poison the bus.
- `pan=` must be finite (`ValueError` otherwise). Finite values outside
  ±1 still clamp. Non-finite pan that reaches the mixer is center.
- `pitch=`: live **rate** knob (duration changes with it). Cheap; not cached.
  Random SFX variety: `pitch=1 + chance(-0.05, 0.05)`. Must be finite and
  `> 0` (`ValueError` otherwise) on `play_sound`, `h.pitch`, and
  `Sound.bake`. A positive rate smaller than `1e-12` is raised to that floor
  so the resampler stays finite. Bake refuses a rate that would run longer
  than 30 minutes. On a mic monitor the rate is ignored, but it still has
  to be a legal number.
- `on_done` fires only on natural completion (including `.fade_out` and after
  Echo/Reverb drain), never on `.cancel()` / `.pause()` / named-slot cut, and
  never once the owner has ended — a sound that rings out past its owner has
  its `on_done` / `then=` dropped ([When the owner ends](#when-the-owner-ends)).
- `Sound.bake(*effects, transpose=0, pitch=1)`: freeze a chain (+ optional
  duration-preserving `transpose=` in semitones and/or rate `pitch=`) into an
  interned material. Knobs snapshotted at bake time. Echo/Reverb tails are
  padded into the PCM. No `.effects` on `Sound`. Microphone cannot bake.
  `transpose=` must be finite. The intern key is **source identity + volume +
  knobs**: a resolved file path, or a hash of the PCM when there is no file.
  Two different buffers that share a duration do not share a bake, and
  `volume=0.3` does not return the `volume=0.9` material.
  Clips of at least ~0.19 s (eight 1024-point hops) use the phase vocoder.
  Shorter clips shift rfft bins so `transpose=` still moves the pitch and
  keeps the length. Under 8 samples, transpose is a no-op.
- `amp_db(x, floor=-60)`: linear amp `0…1` → display `0…1` via dB (for meters /
  spectrum bars). `<= 0` **or non-finite** → `0`; `> 1` clamps to full scale.
  `floor` must be finite and `< 0` (`ValueError` otherwise).

## Ownership

The process table is reused with **zero new rows**. Bare `play_sound` in a mode
body is mode-scoped (ends on leave). `e.play_sound` is entity-scoped (survives
mode change, ends on `destroy()`). A bare call anywhere else is ownerless:
`"game"` when made before the top level ends, `"scene"` after it (ends on the
next act change; [Act Design](Act%20Design.md#lifetime-the-game-and-the-act),
decision 11). Wiring is the existing `owning()` resolver — no new mechanism.

### When the owner ends

**A sound that ends by itself finishes; one that would play forever stops.
Callbacks never outlive the owner.**

An owner ends *implicitly* on `destroy()` (a part's work ends with its host's
destroy — the part itself stays readable), on
`e.mode = …` (mode-scoped sounds only), and on an act change (the act, its
objects, and its ownerless work). Each sound it owned is decided in this order
(`_rings_out` in `process.py`):

| Sound at the owner’s end | Fate | Why |
| --- | --- | --- |
| paused (`h.pause()`) | cut | a held voice never ends — releasing it would leak |
| `h.fade_out()` in flight | **rings out** | the author asked it to end, and it will |
| named slot (`name=`) | cut | `name=` marks a channel (music, ambience) |
| `loops="forever"` | cut | it would never end |
| live source (`play_sound(mic)`) | cut | it would never end |
| anything else — one-shot, `loops=N` (all N laps), `fade_to(0)`, Echo/Reverb tail | **rings out** | it ends by itself |

A sound that rings out is **released to the game**: `h.owner is None`,
`h.scope == "game"`, its name slot is unbound, and its `on_done` / `then=` are
dropped (it ends with `done` true, `cancelled` false, and no callback). Its
in-flight fade moves with it. A later act change does not touch it;
`h.cancel()` still cuts it. It holds no reference to the dead owner.

*Explicit* endings cut everything: `h.cancel()`, `e.cancel_process()`.

Why this split: `play_sound("boom.wav"); change_act(Vitoria)` and
`self.play_sound("death.wav"); self.destroy()` are the commonest beginner
lines, and an instant cut made them silent with nothing pointing at the cause.
The cut exists for what leaks — a loop that would stack on every re-entry, a
callback that would run against dead objects or in the next scene — and a
one-shot has neither problem. A released sound is bounded (it ends by itself),
so this is not the `keep=` escape hatch the Scene fence rejects.

Decided, not open:

- **A forever loop is cut, not finished at the end of its lap.** A music loop
  can be a minute long; "one more lap" would bleed an unpredictable amount into
  the next scene, and the graceful stop already exists (`fade_out`).
- **`loops=N` plays all N laps.** The laps are the sound (an alarm's "beep beep
  beep"); stopping after the current lap would truncate it like the old cut.
- **A long finite sound is not capped and does not warn.** A 3-minute song
  started without `loops=` / `name=` plays on into the next scene; the fix is
  audible and the author writes `name=`, `loops=`, or a cancel / `fade_out` in
  `on_destroy`.
- **`on_done=` does not change the fate.** Whether a sound is heard must not
  depend on whether the author wrote a callback; only the callback is dropped.

To fade a loop when its owner ends, keep the Handle and start the fade in the
hook that runs *before* the owner's work is ended — `on_destroy` for an actor
or a scene (the fading loop then rings out across the change), `@exit_mode`
for an entity-scoped loop. A **mode-scoped** loop is already cut when
`@exit_mode` runs (mode work ends first), so start the loop with
`e.play_sound` when it needs a fade on leave:

```python
@on_mode
def flying(self):
    self.thrust = self.play_sound("thrust_loop.wav", loops="forever")

@exit_mode(flying)
def flying_exit(self):
    self.thrust.fade_out(0.3)
```

## Mixer

Two objects, two threads. The author holds a `Handle` (main thread only). The
mixer holds a `Voice` (audio callback thread). `h.volume = 0.6` enqueues a
command; it does not mutate anything the audio thread reads directly.

The miniaudio callback only **renders** — numpy mix, per-voice volume / pan /
pitch, held (pause), effects, tanh-style soft limiter, finished flags,
double-buffered EMA snapshot. It never calls author code. Completion (`on_done` /
`then=`) fires from the process tick (frame-order step 3) by polling finished
flags. `CMD_SET_HELD` freezes a voice without pulling the source or draining
tails; the voice stays in the mix table (idle short-circuit does not drop it).

After dry EOF, Echo/Reverb voices **drain silence** through the chain for
`max(effect._tail_seconds())` (parametric, capped at 4 s). A cut (`CMD_CANCEL`:
`.cancel()`, `name=` replace, an owner's end cutting a loop) and a `fade_out`
end (`CMD_FINISH`) have no tail.

**De-click.** A cut of an audible voice does not drop the waveform mid-cycle
(an audible click): the voice keeps playing under a linear ramp to silence over
`DECLICK_FRAMES` (220 frames, ~5 ms), then leaves the table. It is reported
finished at the cut frame, is excluded from analysis, and is **not a live
voice** during the ramp — `Mixer.live_voice_ids()` is the set that matches live
Handles (a ramp may span a small device block). A held voice, a muted voice,
`CMD_FINISH` (already at 0), and a 0-frame render pop at once. A second cut
during the ramp is a no-op.

A command `at_frame` past the end of the current block is **not dropped**.
The mixer keeps it and applies it on a later block (`at_frame` minus the
frames already rendered). A 0-frame `render` does not move level / spectrum
EMAs. The settled idle path still returns silence shaped `(n_frames, 2)`.

`render(...)` is a pure function: tests call it / `pump_dt` with no device
(`Backend.NULL` for the spike). The limiter never drops or silently steals a
voice.

Pitch is linear-interpolation resample (playback speed changes with it). Short
clips (< 8 s) decode to an interned buffer; longer files stream.
`Sound(path, stream=True/False)` overrides the heuristic **for that call**.
A decoded buffer is reused later; a `stream=True` entry does not force a
later `Sound(path)` (heuristic) to stream. Bake forces a full
decode when transpose/effects need PCM.

`Handle.remaining` on a stream uses the file's duration and how far the
decoder has read (same lap math as a buffer). Forever loops stay `inf`.

`reset_audio()` (tests) drops the decode cache, bake cache, asset warnings,
the mixer, **and** the `audio` bus (`volume` 1, unmuted, `level_tau` 0.08).

## Master

One module singleton `audio` (same shape as `canvas` / `clock`). v1 has no
forced SFX / music bus split.

```python
audio.volume = 0.8
audio.muted = True
audio.level_tau = 0.08
audio.level                 # 0..1, EMA-smoothed mix
audio.spectrum(bins=8)
```

`audio.volume = 0` / `audio.muted = True` silences the mix without cancelling
any Handle.

## Assets

WAV / FLAC / Ogg / MP3 (what miniaudio decodes). Missing or corrupt: warn
**once per asset**, play silence of nominal duration, keep the Handle ticking
(so `on_done` / `loops` still behave). The warning is a **SCENA WARNING**
banner (amber), same Ctrl+Shift+E dismiss. Terminal
`warnings.warn` still fires.

### No miniaudio

miniaudio (decoder and device) has wheels only for some Pythons and
platforms (1.71: CPython 3.10–3.14 on macOS, Windows x86 / x64, Linux
x86_64). Elsewhere pip builds it from the sdist and, without a C compiler,
the whole `pip install scena` fails. So `pyproject.toml` lists it with a
marker for exactly that wheel set, and the engine runs without it:

- `audio_mixer.miniaudio_module()` probes the import once (a failed import
  searches the whole path); `reset_mixer` probes again (tests block it with
  `sys.modules["miniaudio"] = None`).
- `start_device` returns and the mixer stays **offline**: `tick_audio`
  pumps it, so Handles tick, `on_done` / `await` / `loops` behave, analysis
  reads 0.
- Every file is the missing-file silence (nominal 1 s). One SCENA WARNING
  for the whole game (`NO_MINIAUDIO_MESSAGE`: use Python 3.14, or `python -m
  pip install miniaudio`), on the first decode or `play_sound` (`where`
  `play_sound`) or `Microphone()` (silent mic, `backends=` unchecked). A
  game that never plays a sound sees nothing.

Fence: do not cap `requires-python` for a missing wheel (pip would pick an
older Scena with no cap and fail the same way), and do not move miniaudio to
an extra (3.12–3.14 users would lose sound by default). When miniaudio
ships wheels for more, widen the marker (`tests/test_audio.py`
`TestMiniaudioMarker` lists the cases) and the README / Guia note.

## Analysis

`.level` / `.spectrum(bins=)` on `audio` (master mix), a sound `Handle` (one
voice, metered after its own volume and pan, before the master: `h.volume = 0`
reads 0; it read the source until showcase A11, 2026-10-23), and `Microphone` are read-only and EMA-smoothed (`audio.level_tau`,
default `0.08`). One τ for level and spectrum, everywhere. `level_tau` must
be **finite and > 0** (`ValueError` otherwise, including `nan`). Spectrum
bands are **log-spaced** (~40 Hz … 16 kHz); DC is
excluded by the first edge. Internally 32 bands; `bins=` (default 8) resamples
that snapshot. A full-scale sine peaks near 1 in its band; half-scale peaks
near 0.5 (the reference is `n/4`, the Hann-scaled rfft bin — not `n/8`).
Not an FFT toolkit; no `.level_raw`, no separate spectrum τ. Non-finite
blocks read as silence on the meter, not as full scale.

### Levels as formula sources

`bar["width"] @= lambda: 300 * amp_db(mic.level)` links, like `clock` /
`mouse` (and `@when` / `@on_change` on a level fire). A level is written by
an audio thread (the capture callback, the mixer), which must never touch the
reactive graph, so the reader is not a Container. It names a stand-in node
instead (`level_source.py`): `state._formula_source_of` asks
`type(obj)._formula_source` at link time, for the base of a chain and for
every object along it, so `self.mic.level` inside an Entity depends on the
mic, not on the Entity (before, that chain was accepted with the Entity as its
only source and froze: AL1 in Testing Design). A formula with no readable
source (REPL, `exec`) links from its code object; there the fallback also
looks one attribute away from a Container candidate, for each name the code
reads (`self` → `.mic`). One `LevelSource` per `Microphone`; the `audio` bus
and every sound `Handle` share one (all voices read one mixer snapshot; a
timer Handle answers `None` and `.level` raises its hint).

The frame body samples linked sources in step 1, after the pointer sample
(`if LEVEL_SOURCES: sample_level_sources()`): a source whose reader published
since the last frame (`Microphone._ingest_seq`, bumped per capture block and
on `close()`; `audio_mixer._publish_count`, bumped per snapshot publish and on
a mixer reset) gets `update()`. `.level` stays a live read; the node only says
"it moved". Consequences:

- Updated once per frame. Outside `run()` (a script with no frames) a linked
  level does not move, like a `clock` formula.
- A formula on one `h.level` re-runs every frame while **anything** plays
  (shared node); a settled mixer publishes nothing, so it stops.
- Sources are learned at link time: the mic must exist when the formula is
  linked. `lambda: amp_db(g.mic.level) if g.mic else 0`, linked while
  `g.mic` is `None`, raises (the source walk reads the whole chain, whatever
  the condition) with a message naming the read and the fix
  (`state._extract_sources`, RA2). A mic in a State cell (`st.mic.level`)
  follows the cell and the level, and one linked while `st.mic` is `None`
  follows the mic the cell gets later. A later `g.mic = other` /
  `st.mic = other` moves the formula to the new mic's level (2026-10-17;
  before, it stayed on the first mic's: [Reactive Design — A formula that
  reads an ink field follows the field](Reactive%20Design.md#a-formula-that-reads-an-ink-field-follows-the-field)).
  A mic opened on demand links where it
  opens: tutorial 23 writes `st["voz"] @= lambda: amp_db(self.mic.level)`
  right after `Microphone()` in the R handler, and the meter, the light and
  the `@when` read `st.voz` (0 until then). Opening the mic at the top of the
  file would warn on a machine with no input (and the tutorial runner has
  none).
- Cost: nothing is created until a formula links a level; the frame pays one
  empty-list check (`perf_audio_levels.py`, 2026-10-10: frame body 12.03 vs
  11.93 µs with no mic, 15.97 vs 15.98 µs with an unlinked mic; a mic driving
  three formulas and a `@when` costs 37 µs/frame read directly vs 53 µs for
  the `on_update` copy into `st`). A graph reset makes a new node on the next
  link; dead readers (weakref) and old-graph nodes leave the list on the next
  sample. Tests: `tests/test_audio_level_source.py`.

## Microphone

`Microphone()` opens the OS default capture device. Nothing captures before
that line. `mic.available` (read-only) is `True` while a device is open, `False`
when none opened or after `close()` (2026-10-23: a game had only the warning
to tell). No device: one SCENA WARNING and a silent mic (`.level` stays 0;
a timed `record` still finishes, filled with zeros). No miniaudio: the same silent mic, with
[its own warning](#no-miniaudio). There is no input or
output picker — Scena follows the system default.
`play_sound(mic)` monitors via the same pluggable `FrameSource` seam as a
decoded buffer — construction does not imply monitor. `.level` / `.spectrum`
share `audio.level_tau`. `.effects` is the same live stack as a sound Handle.
`.close()` is idempotent and **zeros `.level` and `.spectrum`**.
Quitting the app closes every open microphone the same way (`run()` cleanup,
and an `atexit` backstop for scripts that never call `run()`).
A native audio device must be released before Python shuts down, never left
for garbage collection: on macOS, stopping CoreAudio from a finalizer during
interpreter shutdown kills the audio thread.
**`.pitch` on a mic monitor is a no-op** (rate-change
does not apply to live capture). The 1 s ring is a jitter buffer for
monitors, not the clip store.

Several `play_sound(mic)` monitors each keep a cursor on that ring, so they
hear the **same** capture (including samples already buffered). Mic effects
run **once** over each captured sample; readers share that result. A reader
that falls more than 1 s behind skips ahead. Closing the mic makes further
reads silence. Closing during a take keeps the samples captured so far and
does **not** fire `on_done`.

### Recording

```python
clip = mic.record()                 # Sound, still recording — not playable yet
mic.stop()                          # clip is final; the mic stays open
play_sound(clip)
clip = await mic.record(seconds=2)  # same object, finished
play_sound(clip.bake(Echo()))
```

`record(seconds=None, *, on_done=, then=)` returns the clip. It is **dry**:
raw ingest, before `mic.effects`. The monitor is wet; the clip is not.
Length is counted in captured samples, not game-clock seconds (`clock.scale`
does not stretch a take). `clip.duration` grows until the take ends, then
it is fixed. `mic.recording` is true only while a take is open.
`mic.stop()` returns nothing — the author already holds `clip`.

`seconds=` ends the take after that many seconds of samples. It must be
finite, `> 0`, and `<= 30` (`ValueError` otherwise). Omit it to record
until `stop()` or the hard 30 s cap (`MAX_RECORD_SECONDS`, not a setting).
An open-ended take that hits the cap ends normally and shows one SCENA
WARNING per microphone.

The clip changes **once**, on the main thread, when the take ends. Until
then `play_sound(clip)`, `clip.bake(...)`, and decoding raise
`RuntimeError`. `await clip` waits for that end and returns the same clip.
`await` on a `Sound` that is not a recording raises `TypeError`.

`on_done=` / `then=` fire on the next process tick after a natural end.
After `stop()`, the clip is playable on the next line; the callback still
waits for that tick. Ownership is the usual resolver: a call from a mode
body is mode-scoped, a bare call is ownerless: the game before the top level ends, the current act after it (Act Design, decision 11).

| End | Keeps the audio | `on_done` / `then=` |
| --- | --- | --- |
| `mic.stop()` | yes, playable on the next line | next tick |
| `seconds=` reached | yes | next tick |
| 30 s cap | yes | next tick, plus one warning |
| mode leave / owner `destroy()` / `mic.close()` | yes | no |

`mic.record()` while already recording, or on a closed mic, raises
`RuntimeError`. `mic.stop()` with nothing recording raises `RuntimeError`.
Samples already in the ring when `record()` is called are not part of the
clip.

### Recording fences

| Don't | Revisit |
| --- | --- |
| `record(wet=True)` | `bake` or `h.effects` cannot express a taught case |
| A setting for the 30 s cap | A taught script needs a longer take and the warning is not enough |
| `clip = mic.stop()` as a second spelling | `clip = mic.record()` cannot be held across the handlers that start and stop |

### Deferred

- **Input or output device selection.** Revisit when a taught script or a classroom setup needs an input or output the OS default cannot provide.
- **`clip.save(...)`.** Revisit when several taught scripts need a file, not just playback.
- **Pause while recording.** Revisit when a taught script must hold a take without ending it.
- **`race(clip, ...)`.** The record Handle is hidden. Revisit when a script must race a take against another awaitable.

## Effects

Curated catalog on a sound `Handle` and on a `Microphone`: `LowPass`
(cutoff=300), `HighPass` (cutoff=2000), `Echo` (delay=0.25, decay=0.6),
`Reverb` (size=1.0, mix=0.6; algorithmic comb + allpass), `Distortion`
(drive=8; makeup-normalized asymmetric tanh + pre/de-emphasis), `Wavefold`
(drive=3; triangle fold). Stack idiom: `.add` / `.enabled` / `.remove` /
`.clear`. Knobs are instance attributes read every mix block.
**`h.effects.enabled = False` syncs immediately** — the mixer drops the
chain, same as `live()` returning `()`.

Non-finite knobs do not crash the callback. Cutoff, size, mix, and drive
fall back to their defaults, then clamp. `Echo` delay that is non-finite or
`<= 0` is dry (tail 0). Decay is clamped to `0…0.95` in **both** the tail
estimate and `_process` (so a decay above 0.95 cannot grow forever while the
drain assumes 0.95). `Reverb` allpass is the unity Schroeder form
(`y = buf - g·x`, `buf = x + g·y`). The parallel combs are scaled by
`(1 - g) / N` so a full wet mix stays near the dry level, not several times
hotter. `Distortion` keeps **separate** pre-emphasis and de-emphasis state,
and makeup is a ~30 ms peak envelope carried in that state — not a max over
the current block — so a mix block and a bake of the same samples agree.
Empty input is a no-op (no `max` on a zero-length buffer).

**No effect steps through a numpy array a row at a time.** The chain runs on
the mixer thread for a live voice, so its cost per second of audio is what
a slower machine can spare in real time. A per-sample loop over rows paid
numpy's call cost per sample: Reverb ~1.4 s per second of stereo on a slower
Windows machine (more than real time), Distortion about the same (WP32). Now:

- **Delay lines** (Echo, Reverb's combs and allpasses) go through
  `_delay_line`: a sample reads what was written `n` samples before, so a run
  of `n` samples reads only the run before it, and numpy takes a run per step.
- **One-pole filters and the envelope** (LowPass, HighPass, Distortion) are
  sequential sample to sample: a loop over Python floats per channel, the same
  double arithmetic as numpy on a row without its overhead.

Both give the 0.9.0 bytes exactly, for any block sizes
(`test_audio_effects.TestEffectsMatchTheSampleLoop`, which keeps the
per-sample loops as the reference); `TestNoSampleLoopOverRows` refuses a
`for i in range(x.shape[0])` in `audio_effects.py`. **Fence:** a Reverb comb
outputs the value it writes (`y = x + g·y[n ago]`, so the dry signal is in
each comb's output), not the value it reads. That is what the per-sample code
computed (its read was a numpy view of the slot it then overwrote), and the
sound authors have; changing it changes every Reverb, and is a design change,
not a fix.

`Sound.bake` runs inside `stall.busy("baking <file> (<effects>)")`: a cold bake
long enough to pass the stall limit is a SCENA NOTE naming the work, not the
loop error, and its time does not count toward the stall (Actors Design, the
stall watch).

Live always. Freeze with `Sound.bake(...)` when the author wants one-shot
compute. Sample keyboards: `pitch=2**(n/12)` or several baked `Sound`s — not a
live vocoder per key.

## Not in this pass

Positional / ambient sound (`Ambience`, camera-distance falloff, SpatialFx
twin) is **v2**. Live `Transpose` on the mix thread is deferred.
`bake(..., pitch=)` frozen rate and mic recording are supported.
Author catalogs: [API Guide](../docs/en/guide/index.html#som).

**Implemented.** Tests: `tests/test_audio.py`, `test_audio_capture.py`,
`test_audio_effects.py`. Smoke: `scripts/smoke/audio.py`, `audio_mic.py`,
`audio_record.py`.
