# README Media

The landing page and what is made from the games: `README.md` (on GitHub
**and** on PyPI, `readme` in `pyproject.toml`), the clips it shows, gameplay
and build-up videos, and the examples download. Hub: [README.md](README.md).
The Guide and the tutorials: [Docs Design.md](Docs%20Design.md).

| Goal | Go to |
| --- | --- |
| Links, the Gallery, code on the page, the pitch, claims | [Editing the README](#editing-the-readme) |
| Clips (`tools/readme/`) and pilots | [Editing the README](#editing-the-readme), "Clips are recorded" |
| Videos with sound, takes, build-ups, debug mode (`tools/video/`) | [Editing the README](#editing-the-readme), "Videos are rendered" |
| `scena-examples.zip` (`tools/release/`) | [Editing the README](#editing-the-readme), "The examples download" |

## Editing the README

Guards: `tests/test_readme.py`.

- **Absolute URLs only.** Links point at
  `github.com/accmota/Scena/(blob|tree)/main/…`, images at
  `github.com/accmota/Scena/raw/main/…`: PyPI renders the same file, where a
  relative path is dead. Each one must map to a file in the checkout. Not
  `raw.githubusercontent.com`: it answered 404 while the repository was private,
  where `github.com/…/raw/…` redirects with a token for a signed-in viewer, and
  one form keeps the guard simple now that it is public.
- **Clips are recorded, never captured by hand.** `python tools/readme/make_readme_media.py`
  plays each program headless on the GPU (`ProgramRun`: the frame body and
  input handlers of a windowed run) while a *pilot* reads the game's globals
  and holds keys / moves the mouse, then writes `docs/assets/readme/<id>.webp`.
  Clips are animated WebP at 30 fps (`FPS` in the tool; the game steps at 60).
  Staleness is by input hash (program text, clip spec, pilot source, render
  settings), never pixels; `--check` lists stale clips. Edit an example or a
  pilot → render again. A pilot that clicks menus sets `game.cursor = True`
  and the tool draws the pointer (the window has none to capture). A
  *montage* (`segments` in `CLIPS`, e.g. "And many more") plays several
  programs, one short take each, fitted into one size (letterboxed when the
  aspect differs) with the file name in a corner; its hash covers every
  take.
- **A Gallery row is one shape.** GitHub sizes a table column by its caption
  and keeps each image's aspect, so mixed shapes make uneven cells. Every
  Gallery cell is `width="50%"`, and the two clips of a row share an aspect
  (within 7%). A clip that has no partner of its shape takes a `frame` in
  `CLIPS` (Connect Four: 500×380 inside 640×360): the game is fitted inside
  and its own edge colour fills the sides (`widen`), so it suits a game whose
  background is flat at the edges, not a scene that runs off them.
- **The code on the page is the code of its picture.** The block right after
  `<!-- clip: <id> -->` is that clip's program (run as a file in `examples/`, so
  its art resolves from `examples/media`). The level editor's clip is no
  exception: `tools/readme/editor_ninja.py` starts the editor the way
  `scena-editor` does, with Ninja IV's level open, and a pilot zooms, box-selects
  and drags in it.
- **The page is English, and so is what it shows.** Every example the README
  links or records is an English file: a tutorial's English twin
  (`names_en.json`, `ships_4_shield.py`, never `naves_4_escudo.py`) or a
  showcase. A Portuguese-only example (`revoada.py`, `constelacao.py`) stays
  off the page until it has a twin, since its clip would show Portuguese text
  and its file name. Levels the same: `ninja_hazards.json`, with its English
  groups (`"floor"`, `"elevator"`). A command names the file where the
  examples zip has it (`media/levels/…`). `tests/test_readme.py` holds both.
- **A dropped clip outlives its README by one release.** PyPI shows the README
  of the released version, and its images load from `main`: a clip renamed or
  removed goes into `RETIRED` in the tool (file kept) and is deleted only after
  a release ships a README without it.
- **A pilot plays like a player.** It reads the game's globals each frame and
  holds keys or moves the mouse; places it acts on are world points of the
  level (`run_jump_and_throw`, `edit_a_level`), put on screen through the
  game's own camera. A clip that shows a death, a stuck hero or an idle
  screen is a pilot bug: look at frames from the clip before keeping it.
- **Videos are rendered the same way, with sound.** `python tools/video/record_game.py`
  plays a program headless with a README pilot (or `pilots.py:function`) and
  encodes MP4 (H.264, BT.709, AAC 48 kHz) or ProRes through ffmpeg, or writes
  PNG frames + WAV. The recorder is the sound card: it takes the mixer off
  `offline` (as `Mixer.start_device` does, so the engine's world-time pump is a
  no-op) and pulls one frame of samples (44100 / 60 = 735) right after each
  step, so a sound starts in the block of the frame that shows its cause.
  Pulling before the step puts every sound one frame late; pumping by world
  time as well plays sounds at double speed (guards: `tests/test_record_game.py`).
- **A video take is a whole run.** The shot list (`tools/video/takes.py`)
  shows each game by its last version (`naves_6_atos`, not `naves_4_escudo`)
  in several takes, a run each (a win, a loss, another track); the edit
  picks the best parts. A video pilot (`tools/video/pilots.py`) plays like a
  player: it re-aims a few times a second, starts a key past a threshold and
  lets go inside a smaller one, and misses on purpose when the take asks. It
  sets `game.done` when the run is over and the take ends after a tail;
  `seconds` is then a cap. Every take writes a review sheet (frames every
  5 s, still and silent seconds); a still stretch the pilot did not mean is
  flagged. `--review` makes only the sheet, small and fast: check a pilot
  there before a full render. A take's variation must show: two takes that
  play alike are one take (the catch pilot's careful and sloppy takes are
  tested apart; a game hard enough that a perfect player misses needs a
  bigger `miss` to look sloppy). The ending must match the take's name:
  in Naves a careless pilot that fires all the time still wins, so the
  game-over take fires in short bursts with slow eyes (tests play each
  take without drawing: `tests/test_record_game_deep.py`, gate). A pilot
  that restarts a game (SPACE after a crash) moves its memory on in the
  same frame: a frame later the game is running again and the pilot's
  crashed branch never runs. Time a pilot's actions in whole frames
  (`pilots.at`): a time measured from a screen's first frame carries float
  error, and a click compared in seconds can miss both candidate frames.
  A screen held still on purpose (a results screen) sets `game.still`, so
  the review does not flag it. A pilot plans with what collides (the
  hitbox), not the picture: the runner's robot is 90 px wide on screen and
  42 px to the ground. Corredor's random level makes spots no jump clears
  at the early speeds (a crate, a short strip, a hole), so its takes are
  several runs, each until the game ends it. A pilot drops or clicks on
  what the game reads, not near it: Ligue 4 takes the column from the
  cell under the drop, so a drop just above the board is a drop off it.
  A level too intricate for a reactive pilot gets a scripted route
  (`NINJA_ROUTE`: world points, each step ending on its own condition, a
  "land" step after running off an edge). Ninja V's platforms hold only a
  landing from above (a jump from below passes through them; the 15°
  ramp, the y 250 and y 420 platforms are reached by jumping down onto
  them), and a crate over the second pit blocks the jump under it until
  the sword breaks it. A route is a chain: trace it whole after each change.
  A demo's take is a tour of its controls (`pilots.tour`: a timetable of
  slider drags, clicks on widgets, objects or world points, pointer paths,
  keys and the wheel). While the button is down, that press owns the
  pointer, and the release happens where it was held: the next event's
  glide starts early and would pull a click off its button, or end the
  editor's band select over nothing.
- **"This code → this game".** A take with `layout="code"` shows the
  program's code (no module docstring; Pygments colours; the largest font
  that fits every line, so meant for one-screen programs) on the left 40 %
  of the frame and the game on the right; the 01, 02 and catch-the-stars
  takes have a `code` twin. The font is the system's monospace (Menlo,
  DejaVu Sans Mono, Consolas): the repository ships none.
- **Build-up videos are read from the tutorial pages.**
  `python tools/video/buildup.py <id>` plays a tutorial's steps in order
  (the steps `tests/test_tutorials.extract_steps` reads, titled by the
  page data's `title:`), each in the code layout with the lines it adds or
  changes marked, each driven by its own pilot (`BUILDUPS` in
  `tools/video/takes.py`: a step that needs input to show its new part
  gets a short timetable). One clip per step, joined by ffmpeg without
  re-encoding into `recordings/buildup/<id>.mp4`. An edited tutorial step
  is in the next build-up with no edit here; a step added or moved shifts
  the numbers in `BUILDUPS`. Build-ups read the English pages
  (`docs/en/tutorial/`, "Step N"; a Portuguese page says "Passo N"). A page
  that ends in two programs (`30-spins`: the bars, then the oscilloscope)
  gives each build-up its own steps (`example=`), numbered from 1.
- **Debug mode on video.** `pilots.with_debug_keys` plays another pilot's
  run and adds Ctrl+Shift chords at set times (`ninja_5_espada/debug`:
  7 hitboxes, then 6 processes; `naves_6_atos/debug`: 7, then 8 debug
  zoom), each overlay kept as the next comes. A chord's modifiers go down
  a moment before its digit (keys of one frame arrive in name order). The
  HUD's FPS counts frames per wall-clock second, which offline is the
  render's speed, so the recorder reports the video's 60. The overlay
  pack, debug zoom and process panel live on the framework, not the world:
  a test that switches them restores them, or the next test clicks
  through a 50 % view.
- **Code on the page runs.** A complete program (`from scena import *` …
  `run()`) plays 2 s headless and must not warn. A fragment must use exported
  names, accepted keywords and existing attributes of scena globals. A block
  inside a list item (indented fences) is read dedented. The fragment check is
  static: before writing a fragment, run it once inside a program. A check
  that only reads names passed `bar["color"] @= …`, and appearance cannot be
  linked (`color`, `visual`, `glow`: [Reactive Design.md](Reactive%20Design.md)).
- **The pitch says what Scena is, not what it does for you.** The author writes
  the game; Scena gives the vocabulary and runs the machinery (loop, drawing,
  timers, cleanup). Avoid lines that read as the framework making the game
  ("Scena does every detail"); performance is "enough for typical games at
  60 fps on an ordinary computer", never "fast".
- **The examples download is a release asset.** The README links
  `releases/latest/download/scena-examples.zip`. The release workflow's
  `examples` job (after PyPI) zips the files in `tools/release/examples_zip.txt`
  with the standard library and attaches the zip to the tag's GitHub Release.
  The list is made here by `python tools/release/make_examples_zip.py --update`
  (the media scanner of `tests/test_media_refs`, level files followed to their
  images, each used folder's license, `CREDITS.md`); `tests/test_examples_zip.py`
  fails while it is stale and plays the level examples from the unzipped folder.
- **Claims match the code.** "Mistakes explain themselves" is true only where
  the near-miss message exists; check a claim before writing it.
- **Docs links:** the API Guide and tutorial links go to `en`, with a line of
  Portuguese links (Guia, tutoriais) beside them.
