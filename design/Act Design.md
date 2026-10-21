# Act Design

**Status: implemented (2026-09-28); renamed to `Act` 2026-10-06 (0.6.0).**
`Act`, `change_act` and `run(Titulo)` are Scena API (`scena/act.py`, exported
from `stage`). Author surface: [Guia — Atos](../docs/pt/guide/index.html#atos).
Tests: `tests/test_act.py`. A runnable sample game (the design's paper
sketch, made runnable) is in development and not yet in `examples/`.
Design history: first pass 2026-09-25 as "Room Design"; reshaped 2026-09-26;
open questions decided the same day, see [Decisions](#decisions-2026-09-26);
promoted from draft 2026-09-28 once the registry rename freed the word
(see [History](#history)); built the same day — what the build decided or
corrected is in [Implementation notes](#implementation-notes); renamed
Scene → Act 2026-10-06, see [Naming](#naming).

| Goal | Go to |
| --- | --- |
| What it looks like | [At a glance](#at-a-glance) |
| What an act class may contain | [An act is a flat class](#an-act-is-a-flat-class) |
| Pair rules for one act only | [Pair rules](#pair-rules-scoped-by-when-not-where) |
| What gets removed / restored / kept on an act change | [Lifetime](#lifetime-the-game-and-the-act) |
| Something from an act that must outlive it | [Game-wide things](#game-wide-things-from-inside-an-act) |
| Where game data lives | [Game data](#game-data-st-is-the-one-channel) |
| How entities find each other | [Finding each other](#finding-each-other-groups-not-the-act) |
| Act vs mode | [Acts and modes](#acts-and-modes) |
| What `change_act` does, step by step | [change_act](#change_act) |
| Rules and error messages | [Restrictions](#restrictions-and-error-messages) |
| Why "Act" (and not Scene), and the names considered | [Naming](#naming) |
| Why not the other shapes | [Alternatives](#alternatives-considered) |
| What was decided | [Decisions](#decisions-2026-09-26) |
| What the sketches and the reviews taught us | [Findings](#findings) |
| Still undecided | [Open questions](#open-questions) |


## Problem

Scena has no act management. Games that need a restart write a hand-made
reset list, and each game forgets something different:

- a shooter sample — an 11-line `restart()` including `ready.reset("fire")`
  and `canvas.reset_view()`.
- a Galaga sample — resets `hp`, `center`, `active`, `visible`,
  `untag("hurt")`, three groups, and the Director by hand.

Neither sample has a title screen; "game over" is the HUD text changing to
"press R". The pieces exist (modes, `destroy`, `cancel_process`, cover fades,
`clock.paused`, `st`), but **cleanup** between screens does not.

## Goals and non-goals

Goals:

- Title → play → game over → title, levels, and restart, **without a reset list**.
- Simple concept, readable without a tutorial: the code does what it looks like.
- Author code stays in the style the examples teach:
  **flat classes** (no hierarchy, no `super()`), game state in **`st`**, no `global`,
  Scena vocabulary (groups, `@when`, modes) instead of new plumbing.
- Reuse what authors already know (Entity classes, `setup`, `on_update`,
  `on_destroy`, modes, method decorators).
- Optional: games without acts are unchanged. Acts are a tool for
  authors who already write classes such as `Heroi` or `Director` (the last step of
  the owners grow path: [Grow path](#grow-path)).

Non-goals (deliberately out):

- Act stacks, overlay acts (pause menus), acts alive in the background.
- Preloading / async loading, act files, editors.
- Transition-effect catalog (fades compose; see [Transitions](#transitions)).
- Persisting an act's state across visits — entering always builds fresh.
- Pause: stays `clock.paused` (nothing should be torn down).


## At a glance

```python
# ---- o palco: topo do arquivo, vale o jogo todo ----
SkyGradient("night")
Bloom()

def jogo_novo():                             # os dados de um jogo que começa
    st.pontos = 0
    st.vidas = 3
    st.fase = 1

st.recorde = 0                               # vale entre jogos
jogo_novo()                                  # run(Fase) direto também tem st pronto

class Heroi(Sprite, group="heroi"): ...      # classes são só definições
class Inimigo(Sprite, group="inimigo"): ...

@leave_playfield("tiro", "tiro_inimigo")
def saiu(tiro):
    tiro.destroy()

# ---- atos ----
class Titulo(Act):
    def setup(self):
        Text("GALAGA", center=(500, 500), font_size=72)

    def on_update(self, dt):
        if keyp.once("SPACE"):
            jogo_novo()
            change_act(Fase)

class Fase(Act):
    def setup(self):
        Heroi(center=(500, 70))
        placar = Text("", x1=20, y1=760)
        placar["text"] @= lambda: f"Pontos {st.pontos}   Vidas {st.vidas}"
        self.mode = self.frota               # um modo *deste ato*

    def on_update(self, dt):
        if keyp.once("R") and st.vidas > 0:
            change_act(Fase)               # recomeça: sempre uma Fase nova

    @when(lambda self: st.vidas == 0)
    def perdeu(self):
        self.after(1.5, lambda: change_act(FimDeJogo))

    @on_mode
    async def frota(self):
        montar_frota()
        await until_empty("inimigo")
        st.fase += 1
        change_act(Fase)

class FimDeJogo(Act):
    def setup(self):
        Text("FIM DE JOGO", center=(500, 400))
        self.after(8, lambda: change_act(Titulo))

run(Titulo)
```

No cleanup code anywhere: everything an act created leaves with it. No
`global`, no base class, no reference from an entity to an act.


## Concepts

### An act is a flat class

`class Titulo(Act)`. `Act` is a bare `Entity` subclass (`layer=None`, never
drawn, never in a group). Following the Actors rule "do not invent a parallel
Entity type", it inherits the process surface authors already know:

| In an act class | Means |
| --- | --- |
| `setup(self)` | Build the act. Same signature as `Entity.setup()` — no parameters |
| `on_update(self, dt)` | Per-frame logic **for this act only** |
| `@every` / `@after` / `@when` / `@on_change` methods | Act-scoped rules; armed on enter, gone on leave |
| `self.mode = self.frota` | A mode of the act (chapters inside one act) |
| `self.aviso = Text(...)` | Act memory on `self`, only for objects a **later** method uses |
| `self.after(...)`, `self.play_sound(...)` | Owned by the act; stop on leave (a sound that ends by itself finishes — [decision 12](#decisions-2026-09-26)) |
| `on_destroy(self)` | Leave hook. Runs **first** on an act change, while the act's objects are still alive (it can read them). Rarely needed: owned things stop and settings are restored without it |

**One rule for decorators:** an act class accepts exactly the method
decorators and hooks an Entity class accepts, **except the ones that need a
body** — an act has no position, shape, or collider. `@collide_with`,
`@collide_with_stay`, `@collide_with_exit`, class-level `@leave_playfield`,
`on_click` / pointer hooks and `on_collide` raise at class definition (see
[Restrictions](#restrictions-and-error-messages)). Script-level `@collide(a, b)`
in a class body already raises for every class today (`collision.py`); an act
is no exception.

The leave hook is `on_destroy`, not a new name: an act starts with the Entity
word `setup`, so it ends with the Entity word that pairs with it, and the act
entity really is destroyed. `on_leave` already means something else
(`History(on_leave=)`), and a second name would be a second spelling.

Acts are **taught flat**: `class Fase(Act)` (the examples and tutorials
never use class hierarchy: a beginner reads one class, not two). An act that
subclasses an act works and is not refused: a base's `on_update`, class
`@every` and `@when` run once in the subclass act, and the base `setup` runs
only through `super().setup()`. The Guia said "never" while nothing enforced
it and the form behaves correctly (persona probes round 2, R2-10); decided
2026-10-20: the Guia recommends flat acts and documents inheritance.
Shared parts are either one act that reads `st` (`Fase` with `st.fase`) or a
top-level helper function called from each `setup` (`montar_frota()`; what it
creates belongs to the act that called it; `jogo_novo()` resets data).

A decorator (`@act def titulo():`) was considered and rejected: it would mark a
function but give it nowhere to keep per-act logic, rules, or state. Subclassing
is already how Scena marks kinds (`class Heroi(Sprite)`, `class Director(Entity)`).

### Starting: `run(Titulo)`

The first act starts at `run(Titulo)`. `run()` with no argument is unchanged —
that is the gradual path: games without acts never see any of this.
`run(Fase)` while developing starts straight at the act being worked on
(which is why the starting game data is set at the top too, via `jogo_novo()`).

Starting at `run()` (and not with a `change_act` on some line of the file)
keeps the lifetime rule exact: **every** top-level line runs before any act
exists.

### Switching: `change_act(Fase)`

An explicit verb. `change_act` reads as "the old act ends, this one begins"
without a tutorial. It takes the act **class** (the framework builds the
instance) and nothing else.

Restart is `change_act(Fase)` while in `Fase`: it **always** builds a new
instance, even for the same class (unlike `e.mode = same`, which is a no-op).
Flat acts name their own class literally, so there is no `type(self)` and no
restart verb (a `restart()` with no parameters would be a second spelling of
`change_act(Fase)`; see [Alternatives](#alternatives-considered)).

Constructing an act directly (`Fase()`) is rejected with a message that names
`change_act` (see [Restrictions](#restrictions-and-error-messages)). One spelling.

### Game data: `st` is the one channel

Everything the next act needs to know — score, lives, which level, whether the
player won — lives in `st`, the taught home of game state. There is no second
channel (`setup` keywords were dropped; see [Findings](#findings)).

- **Set before the change, read in `setup`:** `st.venceu = True` then
  `change_act(FimDeJogo)`; `FimDeJogo.setup` reads `st.venceu`.
- **New game = one top-level helper** (`jogo_novo()`), called at the top of the
  file (so `run(Fase)` works while developing) and by the act that starts a
  game (`Titulo`). The starting values are written once. That is game rules,
  not cleanup. Values that span games (`st.recorde`) stay outside it.
- **`st` is never cleared by an act change.** A restart keeps `st` as it is
  now: `R` in `Fase` keeps the current lives and the points earned so far. A
  game where restart must undo points saves them on entry
  (`st.pontos_na_entrada = st.pontos` in `setup`) — author's choice, visible in
  the code.

### Finding each other: groups, not the act

Entities never mention acts. They find each other the way Scena entities
already do, by group:

```python
@on_mode
async def mergulho(self):
    heroi = group["heroi"].nearest(self)     # None if there is no hero
    if not heroi:
        return
    await self.move_to(heroi.center.x, heroi.center.y + 230, time=1.1)
```

The act does not need to keep the hero either: with lives in `st.vidas`, the
HUD reads `st`, the lose rule reads `st`, and nothing after `setup` touches the
hero. `Heroi(center=...)` with no name is enough.

Why not a top-level `heroi = Heroi(...)`: that object belongs to the game (see
[Lifetime](#lifetime-the-game-and-the-act)). It survives every act with its
state: after a death it keeps its lost lives, stays parked (`active = False`),
dissolved and tagged `"ferido"`, and it shows up on the title screen — the reset
list comes back. A hero born in the act *and* bound to a module name needs
`global`, which author code avoids.

There is no `Act.current` in v1 (see [Alternatives](#alternatives-considered)).

### Pair rules: scoped by when, not where

Pair rules follow the same lifetime rule as everything else: what decides their
lifetime is **when** they are registered, not where the code is written.

| Written | Lives |
| --- | --- |
| `@collide("tiro", "inimigo")` at the top of the file | The whole game. Inert in acts where those groups are empty (the title has no bullets) |
| `@collide_with("tiro_inimigo")` on `class Heroi` | As long as that hero; a hero born in an act takes its rules with it |
| `@collide(...)` written inside `setup()` | This act only (a classless registration made after the top level ended) |

So most games need nothing: top-level rules are inert where their groups are
absent, and class rules die with their objects. An act-only pair rule is needed
only when the **same groups** must behave differently in different acts (a
tutorial where bullets do not hurt). Then it goes inside `setup`:

```python
class Treino(Act):
    def setup(self):
        @collide("tiro_inimigo", "heroi")
        def de_mentira(tiro, heroi):
            tiro.destroy()
```

This is the advanced form; the Guia shows it only next to act-scoped rules.
`@collide(a, b)` as an act **method** is not added (see
[Alternatives](#alternatives-considered)).

### Act memory on `self` (ink rule)

`self.aviso = Text(...)` stores an object in the act's ink. Ink is not only
bare scalars: this becomes a documented rule for every Entity.

> **Ink holds any value except a function.** Numbers, text, points, other
> objects. Only numbers, bools and points can be linked (`@=`). A stored object
> that was destroyed reads falsy (`if self.aviso:`).

Consequence: `self.inimigos = group["inimigo"]` raises `CallableAssignError`
(a group view is callable, so ink rejects it as a function). A group is looked
up where it is used, never stored, and the error says so: "A group is looked
up, not stored. Write group['inimigo'] where you need it"
(`entity._ink_callable_message`; see
[Restrictions](#restrictions-and-error-messages)).

Store an object only when a later method needs it (`Titulo.piscar_aviso`). A
banner shown and removed inside one async mode stays a local:
`faixa = Text(...)`, `await wait(1.5)`, `faixa.destroy()`.

### What an act is not

An act is an Entity for its process surface only. The Entity verbs that make
no sense on an act raise and name the right tool: `self.destroy()`,
`self.active = …`, `self.visible = …`, `self.tag(...)`, `group=`,
`layer=`, `self.cancel_process()`, and the body-only decorators above. The exact
messages are in [Restrictions](#restrictions-and-error-messages).


## Lifetime: the game and the act

One rule:

> **Objects an act makes leave with it; settings it changes go back to how the
> top of your file left them. What the top of your file created stays.**

In Portuguese, for authors: *"O que o topo do arquivo cria fica no palco o jogo
todo. O que um ato cria sai com ele, e o que ele muda volta ao que era."*

Wording: in English design docs and in code the persistent part is **"the
game"** — not "the stage", which read as the framework while it was named Stage, before 0.6.0 (see
[Naming](#naming)). The Guia keeps **"o palco"** as its teaching metaphor. The
moment the top-level part is sealed is "the top level ends".

- **The game (o palco, in the Guia)** — everything created by top-level code
  before the top level ends (see [Where the top level ends](#where-the-top-level-ends)):
  backgrounds, post effects, top-level rules (`@collide`, `@leave_playfield`,
  classless `@when`), top-level objects, and the top-level `update` /
  `on_key_down`. Lives until the window closes and keeps working in every act.
- **The act** — everything created after the top level ended, no matter which
  code created it. A bullet spawned by `Heroi.on_update` belongs to the act.
  So does an object made by a top-level helper called from `setup`, and a
  sound started from a top-level `on_key_down`.

Because there is always exactly one act after `run()`, "created since the game
started" and "belongs to the current act" are the same set. No ownership
vocabulary is needed to teach it.

### Removed

| Created after the top level ended | On act change |
| --- | --- |
| Entities (Shape, Sprite, Text, SpatialFx, bare Entity), widgets | destroyed (`on_destroy` runs) |
| Timers, tweens, sounds with no longer-lived owner (includes camera tweens) | cancelled — except a sound that ends by itself, which finishes as game work with its `on_done` dropped ([decision 12](#decisions-2026-09-26)). Forever loops, named slots (`name=`) and paused sounds are cut |
| Tasks (`run_task(…)`) with no longer-lived owner | cancelled with the work they started (tasks after the other handles, so a `finally` in the body sees its timers gone). A task started at the top of the file is game work, and so is the work it starts later, also after the top level ended ([Actors — Tasks](Actors%20Design.md#tasks)) |
| A timed camera verb in flight (`canvas.pan_to(…, time=2)`), **whatever its owner** | cancelled: the camera pose is restored, and a game actor's mode that started the move would write it again next frame (review 2026-10-09 S9-5) |
| Classless `@when` / `@on_change` / `@collide` / `@leave_playfield` registrations | unregistered (a `@leave_playfield` tag the act took over goes back to the game's handler) |
| `resolve(a, b)` pairs | back to the top-level set (act pairs removed; a game pair the act removed or re-tuned comes back) |
| Links an act put on a game object (`hud["text"] @= lambda: f"Pontos {st.pontos}"` in `setup`, also `obj.center @= …`) | undone: the field gets back what it had before the act's first link on it — the game's own link (re-installed), or its value (a point field its place). Silent, also when the link read an act object or the act itself. A restart links again with no "overrides" warning, and the next act can write the field (`hud.text = "NAVES"` raised `LinkedAttributeError`). Recorded at the `@=` (`state._ACT_LINK_HOOK` → `act._note_act_link`, set at the seal of a game with acts; nothing per frame); undone in the change after the drain (`ActManager._undo_act_links`). Review 2026-10-14 PA1 |
| Formula groups (`group["alvos"] @= …`) | back to the top-level set: an act's formula leaves (a restart binds it again with no "overrides" warning, and the name is free for tagging), a game formula the act re-bound comes back (review 2026-10-09 S4-3) |
| Collision tags no surviving rule names, and `ANYTHING` interest from an act rule | retired: later members of the tag are not enrolled, and a body enrolled **only** through it leaves collision (`collidable` reads `False`; an author `collidable = True` keeps it). A game body named with `ANYTHING` in an act rule stops pairing with every body (review 2026-10-09 S8-4, S8-7) |
| Post effects, background fields | removed |
| Script-level `ready` / `recently` memory | forgotten (fixes the shooter's `ready.reset`) |
| Pending canvas one-shots (`shake`, `flash`, `explosion_at`, `fireworks_at`, …) | cleared |

### Restored (world settings)

Every world setting goes back to the value it had when the top level ended. If the
top of the file never set it, that value is the framework default (so a
wallpaper set only in `Fase` goes back to none).

| Restored | Why |
| --- | --- |
| Camera pose (everything `canvas.reset_view()` resets) | A scrolled level would leave the next act's world `Text(center=…)` off screen |
| `canvas.background` (wallpaper assignment) | An act must look the same whichever act came before it |
| `canvas.playfield` | Same; a level's widened leave area must not follow it to the title |
| `clock.scale` | A slow-motion death would leave the title in slow motion |
| `clock.paused` | A paused game over would freeze the next act |
| `collision.resolve_enabled` | An advanced hatch switched off for one level must not stay off |
| `canvas.layers.default` | An act's construction default must not decide where the next act's shapes go |
| `set_defaults(...)` (the paint prototype) | An act's default look must not become the next act's |
| `canvas.effects` / `canvas.background` membership and their `.enabled` | The stacks go back to the game's list, in order: an act's `Bloom()` leaves, and a game effect an act removed (`glow.remove()`, `canvas.effects.clear()`, `set_fly`) comes back. The hit-feedback singleton stays |
| The HUD column cursor (where the next omitted-y HUD `Text` or widget goes; `ui.stack_origin`, `ui.stack_from`, `ui.stack_column`, `ui.stack_reset`, `ui.gap`) | One game HUD item kept the column alive, so each restart stacked the act's HUD one block lower, off screen after four (review 2026-10-09 S4-5) |

The reason for all of them is one: **an act's look and behaviour must not
depend on which act came before it** — the same promise as "entering always
builds fresh", extended to settings.

### Kept

| Kept | Why |
| --- | --- |
| `st` values | Game data; `jogo_novo()` resets what a new game needs |
| Game objects and their own timers (`radio.play_sound(...)` on a top-level `radio`) | Closest owner wins; game objects live until the window closes. **Except** work and hooks the act handed them: a handle whose function, `then=` or `on_done=` is a bound method of the leaving act (or a function closing over it), and a game object's hook (`on_update`, `mode`, `on_click`, `on_collide*`, drag hooks, …) set to one, leave with the act. Otherwise they stacked on every restart, kept the dead act alive and reached its destroyed fields (decided 2026-10-09, review X-life-7) |
| A game timer whose name an act's ownerless timer took (`every(…, name="beat")` at the top and in the act) | The act's timer replaces it **for the act**: the game's pauses and resumes at the change, with its phase (an author `pause()` is kept). Before 2026-10-09 the act's cancelled it for good (review S2-6). A game **task** cannot pause, so ownerless act work named like a running game task (`run_task`, `after`, `every`, `tween`, `play_sound`) raises `ValueError` with the fix (another name, or `cancel()` the game's task first) before anything starts: no voice, no tween preempt, no body step. Before 2026-10-19 it ended the game's task silently (`Scheduler.refuse_game_task_clash`; `test_act.TestNamedSlotsAcrossTheSeal`) |
| Preferences: audio volume, `canvas.fx_quality`, `post_fx_scale`, `shape_fx_scale`, `display`, `batch_shared_filters`, `cull_offscreen`, the UI theme (`ui.scale`, `ui.font`, `ui.min_label_space`) | Player or engine settings, not world state (an options act must be able to change them; a UI size is an accessibility choice) |

**Every author-settable canvas / clock / collision setting is classified as
either restored or kept.** The implementation keeps both lists in one place
(`WORLD_SETTINGS` / `KEPT_SETTINGS` in `scena/act.py`), and a test fails
when a new setter is added without being classified
(`TestSettingsClassification` in `tests/test_act.py`; one-shots, queries and
engine hooks are listed there as `NOT_SETTINGS`). The test walks **every
instance exported in `scena.__all__`**, not a hand list of objects: `ui` was
never walked, so its settings leaked unclassified (review 2026-10-09 S4-6).
An exported instance that is not a settings surface (`st`, `group`, `mouse`,
`keyp`, `ready`, `recently`, `ANYTHING`) is excused by name, with its reason
(`NOT_WALKED`). A layer created at the top
is a game object, and its own state (`visible`, `z`, `scroll`) is its own. A
layer created **in an act** leaves with the act (the seal records the layer
names), so a restart creates it again and the Endless recipe ("create it in
the Act that uses it") can restart. A game object still on an act layer at the
change keeps that layer, and `change_act` raises after the new act is built,
naming the layer and the fix (move the object to a game layer first, or create
the layer at the top). Decided 2026-10-09 (review S4-4): before, the second
`create` of a restart raised "already exists" and left no current act.

Rule of thumb for authors: **if it should start fresh every time, create it in
`setup`. If it should survive every act, create it at the top.** Music started
at the top of the file plays across acts; music started in `setup` (looped or
named, as music is) stops on leave — same rule, no extra vocabulary. A one-shot
effect is not "started fresh every time" state: `play_sound("boom.wav")` right
before `change_act` is heard in full ([decision 12](#decisions-2026-09-26)).

### Game-wide things from inside an act

There is no `keep=` flag and no author-facing `world.…` / `stage.…` namespace.
Each need already has a home:

| Need | How |
| --- | --- |
| Data that crosses acts (score, record, won?) | `st` |
| Something started at runtime that must outlive the act (music toggled by a key, a timer) | A top-level owner: `radio = Entity()` at the top, then `radio.play_sound(...)` / `radio.after(...)` from anywhere. Closest owner wins |
| An object present in every act but shown only later | Create it at the top with `visible=False`; an act shows it (`aviso.visible = True`). Its state is its own: an act change does not hide it again |
| An object *created* from inside an act that becomes part of the game | Not in v1, on purpose. The failure is visible (it vanishes on the change → move it to the top); a `keep=` flag would bring back silent leaks |

### Where the top level ends

Not at the first line of `run()`. The top level ends after everything that runs
once at startup:

1. top-level lines;
2. the script-level `setup(canvas)` hook (called inside `run()`; it runs once,
   so it belongs to the game);
3. the framework's own HUD labels (system info, SCENA WARNING), created inside
   `run()`;
4. then the snapshot of the world settings ([Restored](#restored-world-settings))
   is taken and the top level ends;
5. then the first act's `setup()` runs;
6. then the built world is frozen for the GC (`gc.collect(); gc.freeze()`,
   [Scena Design — Frame pacing and GC](Scena%20Design.md#frame-pacing-and-gc))
   and the clock origin is set.

### Framework singletons are never act-owned

Some framework objects are created lazily on first use, often inside an act:
the hit-feedback post effect behind `canvas.shake` / `flash` / `explosion_at`
(`canvas.effects._hit_feedback()`), system labels, debug overlays, the fade
cover. They must never be recorded in an act's registry. If an act change
removed the hit-feedback effect while the canvas still cached it, every later
shake and explosion would silently do nothing. An act change instead **clears
their pending pulses** (the Removed table). The fade cover is not cleared: it
must survive the change (see [Transitions](#transitions)).

### Act rules watch changes, not states

`@when` fires on the rising edge (False → True). A condition that is already
true when the act starts never fires. In the sketch, restarting `Fase` with
`st.vidas == 0` would arm `perdeu` on a condition that is already true: the
act would never end. Guard the transition (`keyp.once("R") and st.vidas > 0`),
or check the state in `setup`. The Guia must say this next to act `@when`.


## Acts and modes

An act is *like* a mode for the whole game, with its own name so the two never
share syntax:

| | Mode | Act |
| --- | --- | --- |
| What it is | A chapter of one object's behaviour | The part of the game the player is in |
| Switch | `self.mode = self.mergulho` | `change_act(FimDeJogo)` |
| Same target again | No-op (`goto_mode` forces) | Always a fresh act |
| `then=` | Enters a **mode** | Never used for acts |
| Leave hook | `@exit_mode` | `on_destroy` |
| Owns | Timers started in the mode body | Everything created while it is current |
| Nesting | — | An act can have modes (`frota` / `batalha_do_chefe`) |

`then=` inside an act method is always a mode of that act. An act change is
always a `change_act` call, usable anywhere a function call is:
`self.after(3, lambda: change_act(Titulo))`,
`self.dissolve_out(0.4, on_done=lambda: change_act(FimDeJogo))`, or the last
line of an async mode.

Top-level `update` / `on_key_down` keep running in every act and cannot ask
which act is current (no `Act.current`). Per-act logic lives in the
act's own `on_update`. A read-only query is added only for a real case.


## `change_act`

`change_act(ActClass)`:

1. Validate (a class, an `Act` subclass, not `Act` itself, `run()` has
   started, no extra arguments, **not already changing act**). A bad call
   raises and changes nothing.
2. Mark "changing act". Run the act's `on_destroy` while everything it
   created is still alive.
3. Tear down everything created since the top level ended **as one batch**
   ([Removed](#removed)), in two phases: first every entity's own
   `on_destroy` runs while the **whole** batch is still alive (a boss's hook
   may read its escort, whatever their creation order), then teardown. An
   object created during the teardown (by a hook) leaves without its own
   `on_destroy`: it belongs to the ending act, and a self-replacing hook
   ("keep the asteroid field full") would respawn forever. A teardown that
   still does not settle stops after 100 passes and names the classes it
   keeps creating (decided 2026-10-09, review X-life-6 / X-life-9); the act's
   rules and timers are still dropped and the world settings still restored
   before it raises (S4-9). Formula
   dependents torn down in the same batch are not auto-unlinked one by one, so
   no "was unlinked because a formula source was removed" warning is printed for
   a HUD that leaves together with the hero it reads.
4. Clear pending canvas one-shots; restore the world settings
   ([Restored](#restored-world-settings)).
5. Clear "changing act". Build the new act: construct the instance, make it
   current, call `setup()`.
6. GC: the change thawed the frozen heap before step 2 and asks for one
   `gc.collect(); gc.freeze()` at the **end of the frame**
   (`run_pending_freeze`, after `_simulate_frame`'s body). That collect
   reclaims the old act (Scena objects sit in reference cycles, so without
   the thaw they would stay frozen forever) and freezes the new one. It is the
   one GC pause of the change, in the transition frame
   (`scena/gc_policy.py`; test: `tests/test_gc_freeze.py`). It waits for the
   frame end because a change made inside a handler (a collision step, a
   timer, a cover `on_done`) runs under stack frames that still hold the old
   act's bodies: a collect there froze them until the next change (review
   2026-10-09 S4-7). Two changes in one frame refreeze once.
7. Return to the caller.

**Immediate, like a mode assignment.** After the line, you are in the new act.
Code after it still runs, but the old act's objects are dead: verbs on them
raise `DestroyedError`, scheduling verbs do nothing (existing rules). Objects
created after the line belong to the **new** act. Teach: **make
`change_act` the last thing you do** (same advice as `self.destroy()`).

Called from inside the old act's own async mode, the mode script is cancelled
with the act; code after the call runs until the next `await`, then stops.

Teardown before build means a restart never sees the old act's actors:
`Heroi(group="heroi")` in `setup` leaves exactly one `group["heroi"]` member.

The same key press does not carry into the new act. `keyp.once` is consumed
by its first reader, so `FimDeJogo` → SPACE → `Titulo` does not also skip the
title in the same frame; and a change also **drops every unread edge**
(`KeyPressed._swallow_edges`, the same step as lifting a modal mask), with keys
still held counting as already reported — the key must be released and pressed
again. Without the drop, a SPACE held to shoot in `Fase` (read only as
`keyp("SPACE")`, so its edge stays pending even after release) fired
`FimDeJogo`'s `keyp.once("SPACE")` on its first frame (found building the
sample; Testing Design SC1). Since PM3 every frame ends that way too (an
unread edge expires with its frame); the drop at a change still matters for a
change made in the same frame as the press.

### `change_act` during an act change raises

Steps 2–4 run author hooks (`on_destroy` of the act and of every entity). A
`change_act` from one of them raises. The case that makes this matter:

```python
class Heroi(Sprite):
    def on_destroy(self):
        if st.vidas == 0:
            change_act(FimDeJogo)     # gameplay: the hero died
```

With `st.vidas == 0`, pressing R restarts `Fase`; the teardown destroys the
hero, whose hook would redirect the game to `FimDeJogo` in the middle of the
change. Ignoring the call would fail silently; "last call wins" would go to the
wrong act. So it raises, naming both acts and the hook:
"change_act(FimDeJogo) was called from Heroi.on_destroy while the game was
leaving Fase. Put act flow in the act: @when(lambda self: st.vidas == 0)."

### Inside a collision handler

`change_act` inside a `@collide` handler tears the world down in the middle
of the collision step. The engine tolerates it with its existing dead-pair
rules, and needs no act-specific guard (built 2026-09-28):

- the rest of the step's **old-act pairs are not dispatched**: enter / stay
  skip bodies that are not in play, and a destroyed body has no group tags for
  a handler to match and no hooks, so its exit reaches nobody;
- **new-act objects** are not in the step's contacts (detected before the
  handler ran), so nothing is delivered to them;
- **game pairs keep dispatching** in the same step. An earlier draft stopped the
  whole step on a change; that would lose a surviving pair's `enter` (next
  frame reads it as `stay`) and a game body's legitimate `exit`.

During the teardown itself, two bodies **leaving together** get no
`on_collide_exit` from each other (`CollisionSystem._both_leave_with_act`);
a game body separated from a leaving act body still gets its exit.

### Transitions

Fades compose; there is no `fade=` on `change_act` (it would be a second
spelling, [Fences.md](Fences.md)):

```python
canvas.fade_out(0.5, on_done=lambda: change_act(Fase))   # old act
# ...
def setup(self):
    canvas.fade_in(0.5)                                      # new act
```

The cover is a framework singleton and survives the change (it is not a
one-shot and not act-owned). An `on_done` an act gave a fade still in flight
does **not** survive: the change drops it and keeps the animation (as a
released sound drops its `on_done`). Otherwise the next act's `fade_in`
replaced the fade, fired the old act's `on_done` from inside `setup`, and a
`change_act(FimDeJogo)` in it redirected the game (review 2026-10-09 S4-2). A `fade=` is reconsidered only if a taught game
cannot write those two lines.

Music fades the same way, with no new spelling: start the fade in the act's
`on_destroy` (it runs before the act's work ends). A sound that is fading out
ends by itself, so it rings out across the change
([Sound Design — When the owner ends](Sound%20Design.md#when-the-owner-ends)):

```python
def setup(self):
    self.musica = self.play_sound("tema.ogg", loops="forever")

def on_destroy(self):
    self.musica.fade_out(0.5)
```

A deferred switch (apply at the next frame) was considered: safer inside
collision handlers, but `change_act(FimDeJogo)` followed by `Text("...")` would
create the text in the old act and lose it at once. Immediate matches modes.


## Restrictions and error messages

Every rejection says how to do it right.

| Mistake | Error (sketch) |
| --- | --- |
| `Fase()` | `TypeError`: "Acts are entered, not built by hand. Write change_act(Fase) — or run(Fase) for the first act." |
| `change_act(Fase())` | `TypeError`: "change_act takes the act class. Write change_act(Fase), without ()." |
| `change_act("Fase")` | `TypeError`: "change_act takes an Act class, not a string. Write change_act(Fase)." |
| `change_act(Heroi)` | `TypeError`: "Heroi is not an Act. Acts are classes like class Fase(Act): …" |
| `change_act(Fase, vidas=2)` | `TypeError`: "change_act takes only the act. Put game data in st: st.vidas = 2, then change_act(Fase)." |
| `def setup(self, vidas=3)` on an Act | `TypeError` at class definition: "Act setup() takes no parameters. Read game data from st (st.vidas)." |
| `change_act(...)` before `run()` | `RuntimeError`: "The game has not started. Start the first act with run(Titulo)." |
| `change_act(...)` from an `on_destroy` during an act change | `RuntimeError`: "change_act(FimDeJogo) was called from Heroi.on_destroy while the game was leaving Fase. Put act flow in the act: @when(...)." |
| A write to the act after its own `change_act` (more lines of `setup` after `change_act(Fim)`) | `DestroyedError`: "Fase.pontos cannot change act Fase (…): act Fase ended when the game changed act, and code after change_act() runs on the act that is gone. Write change_act(...) last, or return right after it." (CD5; the change is immediate, objects made after it join the new act) |
| `Act()` / `change_act(Act)` | `TypeError`: "Act is the base class. Write class Titulo(Act): … then change_act(Titulo)." |
| `self.destroy()` in an act | `TypeError`: "An act ends when the game changes act. Write change_act(Titulo)." |
| `self.active = False` in an act | `TypeError`: "Acts are not parked. To pause the game, write clock.paused = True." |
| `self.cancel_process()` in an act | `TypeError`: "To start this act over, write change_act(Fase)." |
| `layer=` / `group=` / `self.tag(...)` / `self.visible` on an Act | `TypeError`: "Acts do not draw and are not in groups." |
| `@collide_with` / `@collide_with_stay` / `@collide_with_exit` / class `@leave_playfield` / `on_click` / `on_collide` in an Act class | `TypeError` at class definition: "An act has no body to collide, leave or be clicked. Put the rule on the entity class (class Heroi), or for this act only write @collide(a, b) inside setup()." |
| `def update(self, dt)` / `def on_key_down(self, key)` / any top-of-file input callback (`on_key_up`, `on_char`, `on_mouse_click`, …) in an Act class | `TypeError` at class definition (review 2026-10-14 PA3; before, silently never called): "Fase.update(self, dt) would never be called: in an act the per-frame hook is on_update(self, dt)." / "Fase.on_key_down would never be called: the top-of-file input functions do not run on an act. Instead, read the key in on_update(self, dt) with keyp.once("SPACE")." Mouse: `mouse.press()` in `on_update`, or `on_click` on the actor clicked. A near miss (`on_updat`) raises "Did you mean on_update?" as on every actor class ([Actors Design — Protections](Actors%20Design.md#protections)) |
| `@collide(a, b)` in an Act class body | `TypeError` (today's class-body check), act-specific message: "For the whole game, put @collide at the top of the file. For this act only, write it inside setup()." |
| `self.inimigos = group["inimigo"]` (any Entity) | `CallableAssignError` (today's type), new message: "A group is looked up, not stored. Write group['inimigo'] where you need it." |
| A game object linked to an act object that left, by a link the act did not make with `@=` (since PA1 an act's own `@=` on a game object is undone silently, Removed table) | SCENA WARNING (decided 2026-09-28: the change finishes; the link is dropped and keeps its last value) naming both: "text of the Text made at app.py:12 read the Circle made at app.py:40, which belonged to act Fase and was removed when the game changed to FimDeJogo. The link was dropped (the last value stays). Create it in Fase.setup() so it leaves with the act." |

Other restrictions:

1. Only flat subclasses are taught; only one act at a time; no stack.
2. Acts are never owned by acts and never drawn.
3. The game part is never touched by an act change (restored settings are
   values, not objects).


## Grow path

An act is the last step of the owners grow path in
[Actors Design — How author code runs](Actors%20Design.md#how-author-code-runs)
(top-level script → classes → modes → acts). That path is about how code is organized
and who owns what, not about how code runs: formulas, questions, notices and processes
are the same at every step. The move comes when restarting hurts, not to climb a level.

1. **Script without classes** — no acts. Restart = run the program again, or a
   hand-made reset list.
2. **Author who writes classes** — the Galaga `Director(Entity)` becomes
   `Fase(Act)`; `run()` becomes `run(Fase)`; the reset list is deleted. Title
   and game-over acts are two more small classes.

Nothing written in a script without acts has to change: top-level code keeps
working in every act.


## Naming

**Decided (2026-10-06): `Act` + `change_act`**, and the persistent part is
**the game** (**o palco** in the Guia).

Why not `Scene`: the framework was renamed from Stage to **Scena** in 0.6.0 (the
name "stage" is taken). A `Scene` class inside Scena (`scena.Scene`) says the
same word twice and blurs the framework and the class. On its own `Scene` was
the best name — a Portuguese cognate ("cena"), the word Unity, Phaser and
SpriteKit use, and the theatre metaphor — so the replacement keeps what it can
of that.

`Act` keeps the theatre metaphor: Scena is the show, an act is one part of it.
It is about **time**, not place, so it fits a title screen, a space-shooter
level and a game-over screen alike (unlike `Room`). It is short. The risk:
"act" can read as behaviour — what modes and processes do. The Guia's first
example (`class Titulo(Act)`, `class Fase(Act)`) defuses it: an act is a class
named after a part of the game. A cognate is no longer required (the Guia says
"ato").

### Names considered

| Name | For | Against |
| --- | --- | --- |
| `Scene` | Best name alone: cognate ("cena"); Unity / Phaser / SpriteKit; theatre metaphor | Collides with the framework name Scena (`scena.Scene`) |
| **`Act`** | Chosen. Keeps the theatre metaphor (the show and its parts); time, not place; short | Can read as behaviour ("to act"); the Guia's first example settles it |
| `Room` | GameMaker precedent; the first draft (2026-09-25) | Place metaphor: a title or game-over screen is not a room; not a cognate |
| `Screen` | "tela de título" is how kids talk | "tela" is already used ~100× in the Guia for "visible / on screen" |
| `Level` | — | Already exported (level files); a title screen is not a level |
| `State` | — | Already exported, and `st` is the game state |
| `Chapter` | — | Book metaphor; long |
| `Part` / `Section` | — | Too vague |

### The verb

| Verb | Verdict |
| --- | --- |
| **`change_act`** | Chosen: says both halves — this act ends, another begins. Verb_noun, like `play_sound` |
| `start_act` | Does not say the current act ends; a second "start" next to `run` |
| `new_act` | Reads as a constructor; construct-to-switch was rejected ([Alternatives](#alternatives-considered)) |
| `to_act` | Reads as the infinitive "to act"; in Python `to_` means a conversion |
| `next_act` | Implies an order; a restart (`next_act(Fase)` from `Fase`) reads wrong |
| `goto_act` | Mirrors `goto_mode`; modes and acts deliberately never share syntax ([Acts and modes](#acts-and-modes)) |

### The persistent part is "the game"

Decided 2026-09-28, while the framework was named Stage. "The stage" was the
first choice — it completes the theatre metaphor — but "stage objects", a
`"stage"` scope or a `"<stage>"` owner in a STAGE WARNING would read as *owned
by the framework*, which is the opposite group (hit feedback, system labels,
the cover are the framework's own; see
[Framework singletons](#framework-singletons-are-never-act-owned)). "Game" was
already the word for this lifetime in [Decision 3](#decisions-2026-09-26)
("top-level = game"), and it is the scope value (`"game"`), so it stays after
the rename to Scena. The Guia is Portuguese, where "palco" does not clash, so it
keeps the metaphor.

### Retired names

`scena.Scene` / `from scena import Scene` (and the same for `change_scene`)
get a stub that raises `TypeError` with the fix:

- `class Fase(Scene)` → "Scene was renamed to Act in 0.6.0. Write class Fase(Act), and change_act(Fase) to enter it."
- `change_scene(Fase)` → "change_scene was renamed to change_act in 0.6.0. Write change_act(Fase)."

The stubs are not in `__all__` and not installed in builtins (no name is
shadowed): under `from scena import *` the old names are a plain `NameError`.
They are kept at least until 1.0. The ownerless handle scope `"scene"` became
`"act"` (`process.SCOPE_ACT`), and the ownerless warning label `"<scene>"`
became `"<act>"` ([Decision 11](#decisions-2026-09-26)). A string compare
(`handle.scope == "scene"`) cannot raise, so that change is listed in
`CHANGELOG.md` instead.

"Scene" in the engine and the docs now means only the **rendered frame**
(scene RT, `scene_image`, scene draw), plus "a game / workload" in prose and
benches.

### Vocabulary guards

`tests/test_message_vocabulary.py` keeps the words apart. Engine messages never
say "scene" except an allowlist: rendered-frame messages and the two
retired-name errors above (`TestMessagesDoNotSayScene`). Live docs never use
the retired Scene API names or "scene change" for an act change
(`TestDocsDoNotUseSceneForAct`; this file is skipped, since this section quotes
them), nor the 2026-09-28 registry terms (`TestDocsDoNotUseRetiredSceneTerms`).
The Guia never says "cena" (`TestGuiaDoesNotSayCena`); "ato" lives in the
`#atos` chapter.

### History

First draft "Room Design" (`Room`, `change_room`), 2026-09-25; see
[From the first sketch](#from-the-first-sketch-room-version-2026-09-25).
`Scene` / `change_scene` from 2026-09-26 to 2026-10-06. Freeing that word needed
the 2026-09-28 rename: "scene" also named the internal registry, script scope
and, in the Guia, "in the game", so the registry moved from `scene.py` to
`registry.py` (`Registry`) and the Guia's "na cena" became "na tela" /
"no mundo" / "no jogo". The internal subsystem took a neutral name, not "World":
"world" already means world space as opposed to the view-space `ui` layer, and
the registry holds the `ui` layer too — that still holds. `Act` / `change_act`
from 2026-10-06 (0.6.0).

What the rename taught (applies to any later rename of a doc, module or word):

- **Rename the old holder before promoting the new one.** The old
  `Scene Design.md` (canvas, camera, layers) became `Canvas Design.md` before
  this doc took the name, or every old link would have pointed silently at the
  wrong doc.
- **Rename a file and its citations in one change.** Citations written ahead of
  the code rename pointed at a not-yet-existing `test_registry_layers.py`.
- **Per sentence, never a blanket replace.** Each "cena" in the Guia was read in
  context: "na tela" (visible), "no mundo" (world space vs HUD), "no jogo"
  (alive / registered); script scope became "script" and the post-FX frame
  "imagem". "scene" meaning the rendered frame or a bench workload was kept.
- **Land a guard with each step**, so the old word cannot creep back: the
  [Vocabulary guards](#vocabulary-guards) above.


## Alternatives considered

| Option | Why not |
| --- | --- |
| Act = function + `goto_act(fn)` | No place for per-act logic/state; `global` needed; "goto" reads as a jump |
| Acts as modes of a built-in `game` Entity (`game.mode = playing`) | Two kinds of mode with different rules; `then=` ambiguous (mode or act?) |
| `@act` decorator on functions | Marks without giving structure |
| Construct-to-switch (`Fase()` switches) | Composes as a callback, but hides that the old act ends; an explicit verb reads better |
| Manual registration (`self.add(obj)`, `Circle(..., act=self)`) | Boilerplate on every spawn; spawns from `Heroi.on_update` need the act; a forgotten registration leaks **silently** into the next act |
| `with Act(): …` block | Owns only what is created inside the block; bullets spawned later escape |
| Director Entity + tags + `@exit_mode` (no new API) | Works today, but is the same hand-made reset list |
| Every mode owns what is born in it | Breaks wasp stings and other spawns that should outlive a mode |
| Shared base act (`class Level(Act)`, `Level1(Level)`) | Class hierarchy (outside the author guide); forces `super().setup()` and `change_act(type(self))` for restart |
| `setup` keywords (`change_act(FimDeJogo, venceu=True)`) | A second data channel next to `st`; needs a signature check and a special `setup`; makes restart ambiguous (which arguments?). In the first sketch it hid a bug (below). Revisit only with a real need |
| `restart()` verb | With flat acts and no keywords it is a second spelling of `change_act(Fase)`. It would earn a place only if keywords came back ("enter again with the same arguments") — then as an act method, `self.restart()` |
| `change_act(Act.current)` (instance = fresh copy) | Contradicts "change_act takes the class" and its error message |
| `Act.current` (read the current act) | Couples entities to acts (`Act.current.hero`); `Fase.current` would also return a `FimDeJogo`; nothing in the flat design needs it |
| Hero at the top of the file | Game object: keeps lost lives, park, dissolve, tags; visible on the title — the reset list returns |
| Hero in `st` (`st.heroi = Heroi(...)`) | `st` outlives acts: a dangling reference to a dead object, and `st` is game data, not objects |
| Leave hook `on_leave` / `on_exit` | A second name for `on_destroy`; `on_leave` already means `History(on_leave=)`; acts already use the Entity words (`setup`) |
| `@collide(a, b)` as an act method (armed on enter) | Class-body `@collide` raises for every other class; needs a new handler shape `(self, me, other, info)`; a second spelling of `@collide` inside `setup`. Revisit only if a taught game needs many act-only pair rules |
| Keep world settings as the previous act left them | An act would look different depending on the act before it (`FimDeJogo` after level 2 wears level 2's wallpaper) |
| `keep=` flag / author `world.…` or `stage.…` namespace for game-wide objects | Silent leaks come back; "world" names world space; the top of the file and game owners already cover it |
| Rename the internal subsystem to "World" | "world" already means world space vs `ui`; the registry holds the `ui` layer |
| `change_act` during an act change: ignore, or last call wins | Ignore fails silently; last-wins sends a restart to the game-over screen when a hero's `on_destroy` reacts to its own teardown |

Automatic vs manual lifetime, in one line: automatic fails **visibly** (something
you wanted vanished → create it at the top); manual fails **silently** (a leak
keeps colliding in the next act).


## Decisions (2026-09-26)

The former open questions, resolved:

1. **Name:** decided as `Scene` / `change_scene`; renamed `Act` /
   `change_act` on 2026-10-06. The internal subsystem is renamed to neutral
   names (`Canvas Design.md`, `registry.py`, `Registry`), **not** "World". See
   [Naming](#naming).
2. **Leave hook:** `on_destroy`, run first while the act's objects are alive.
3. **Act-scoped pair rules:** scoped by registration time. Top-level = game,
   entity class = object, inside `setup` = act. No class-body `@collide` on
   `Act`. Act classes accept the Entity decorators except body-only ones.
4. **World settings:** restored to the top-level value (the framework default if the
   top never set them): camera pose, `canvas.background`, `canvas.playfield`,
   `clock.scale`, `clock.paused`, `collision.resolve_enabled`. Preferences are
   kept. Every setter is classified; a test enforces it.
5. **Fade transitions:** compose (`fade_out(on_done=change_act)` +
   `fade_in` in `setup`); no `fade=`; the cover survives the change.
6. **Top-level `update` / `on_key_down`:** run in every act; no current-act
   query until a real case.
7. **Collision-handler timing:** `change_act` inside a handler is legal; the
   engine tolerates it.

Added in the same review:

8. `change_act` during an act change raises (message names the hook and both
   acts).
9. Starting game data lives in one top-level helper (`jogo_novo()`), called at the
   top and from the act that starts a game.
10. Game-wide things from inside an act: `st`, game owners, hidden game
    objects; no `keep=`.

Added 2026-09-28:

11. **Ownerless scope values:** work with no owner (a bare `after(…)`,
    `play_sound(…)`, `tween(…)`) reports `handle.scope == "game"` when created
    before the top level ends and `"act"` after it; `"entity"` / `"mode"` are
    unchanged. The owner label for an ownerless SCENA WARNING in
    `last_author_error()` follows: `"<game>"` / `"<act>"`. Scoped by **when**,
    like pair rules: a bare `after()` in the top-level `update` runs after the
    top level ended, so it is `"act"`. English docs say "the game" for the
    persistent part; the Guia says "o palco" (see [Naming](#naming)). Built
    (see [Findings](#findings)).

Added 2026-09-28 (built):

12. **Sounds that end by themselves finish.** An act change (like `destroy()`
    and a mode leave) no longer cuts every sound it owned: a sound that ends by
    itself — finite, not a named slot, not paused, or any sound with a
    `fade_out` in flight — is released to the game (`owner None`, scope
    `"game"`, `on_done` / `then=` dropped) and plays to its end; forever loops,
    named slots, paused sounds and live sources are cut (with a ~5 ms
    de-click). Reason: `play_sound("boom.wav"); change_act(Vitoria)` was
    silent with nothing pointing at the cause, while the cut only needs to stop
    what leaks (loops stacking on re-entry, callbacks reaching dead objects).
    Not a `keep=` hatch: nothing new to write, and a released sound is bounded.
    Full table and rejected alternatives (finish the current lap, a length
    cap): [Sound Design — When the owner ends](Sound%20Design.md#when-the-owner-ends).


## Findings

### From the first sketch (Room version, 2026-09-25)

Title → Level1 (fleet) → Level2 (boss) → GameOver, with `Level(Room)` as a
shared base and `lives` passed through `setup(lives=)`.

- **No cleanup code at all.** The only `destroy()` calls were gameplay. Kept.
- **Behaviour in entities, flow in acts.** The hero never mentioned rooms;
  the level decided when to move on. Kept, and made strict: entities never
  mention acts (the first sketch's `Room.current.hero` broke it).
- **Restart from the base class needed `change_room(type(self))`.** The cause
  was the base class; flat acts remove it.
- **Hidden restart bug.** `R` in `Level2` ran `change_room(type(self))`, so
  `setup(lives=3)` used the default: restarting level 2 refilled the lives and
  kept the score — infinite retries. The mix of base class, keyword defaults
  and restart made it invisible. `st` as the one channel removes it.
- **Act state in ink** (`self.hero`, `self.prompt`, `self.banner`). Works;
  now a documented rule, and most of it is no longer needed (lives in `st`,
  banners as locals in an async mode).
- **Act modes read well** (`boss_warning` → `fight` with `then=`). Kept; the
  second sketch uses async modes for the same flow with fewer lines.

### From the review (2026-09-26)

Checked against the current code; each one is now covered above.

- **Camera and clock left changed** would make world text invisible and titles
  slow-motion → restored on change.
- **The top level cannot end at the first line of `run()`**: the script-level
  `setup` hook and the framework's HUD labels are created inside it → the end
  point is fixed after them.
- **Lazy framework singletons** (hit feedback) would be removed and still
  cached → never act-owned; pulses cleared.
- **Teardown order** would print an auto-unlink `RuntimeWarning` for every HUD
  linked to an act object → teardown is one batch.
- **Inherited Entity verbs** (`destroy`, `active`, `tag`, …) had no defined
  meaning on an act → they raise with the right tool.
- **Ink rejects callables**, so storing a group raises → rule written, message
  improved.
- **`@when` rising edge** can leave a restarted act stuck → documented, with
  the guard.

### From the second sketch

The paper sketch, now a runnable sample game (in development): `Titulo` →
`Fase` (reads `st.fase`: fleet, then boss) → `FimDeJogo` → `Titulo`.

- No `global`, no base class, no `super()`, no `type(self)`, no act reference
  in any entity. The only `self.` storage is the title's blinking prompt.
- The boss HP HUD was left out: a `Text` linked to `chefe.vida` prints the
  auto-unlink warning when the boss is destroyed mid-act. That is today's
  formula rule, not an act issue; a HUD that should outlive its source needs a
  separate answer (reading `st`, or a quieter unlink for HUD text).
- The starting game data was written twice (top and `Titulo`) → `jogo_novo()`.

### From the decisions review (2026-09-26)

- **"World" collides with world space** (registry holds the `ui` layer) →
  neutral internal names.
- **Class-body `@collide` already raises** for every class → act-only pair
  rules come from registration time, not a new method form.
- **An `on_destroy` that calls `change_act`** would redirect a restart
  mid-teardown → raises.
- **An existing message said "Scene-level … then="** meaning script level →
  wrong once the concept (then named Scene) existed; renamed (now
  "Script-level …").


## Open questions

1. **HUD that outlives its formula source** (boss HP text after the boss is
   destroyed mid-act): read `st`, or a quieter unlink for HUD text? Not an
   act issue, but acts make it more common.
2. **Act-only pair rules as a class form**: deferred; reopen only if a taught
   game needs several of them and the `setup` form reads badly.


## Implementation notes

For maintainers, when built. Sketch only.

### Build status

Plan steps:

1. **Done.** `scena/act.py`: `ActManager` (singleton, `get_act_manager()`),
   `Act`, `change_act`, `ActUsageError`. `ScenaFramework._begin_game`
   (`orchestration.py`) ends the top level: script `setup` hook → HUD labels
   (`_build_system_labels`, marked `_scena_internal`) → `_seal` → first act →
   `clock._mark_play_start()`. `run(first_act=None)` validates before the
   window opens. Tests: `tests/test_act.py`; headless start is
   `SystemWorld.begin_game(first_act, setup=)`.
2. **Done.** World settings table (`WORLD_SETTINGS` / `KEPT_SETTINGS`);
   snapshot at `_seal`, restore after the teardown. Covers the post / background
   stacks too (membership restored, not only act-made entries removed).
3. **Done.** Ownerless Handles: `SCOPE_GAME` / `SCOPE_ACT` by seal
   (`process.ownerless_scope()`), `Scheduler.cancel_ownerless`.
4. **Done.** Classless `@when` / `@on_change` made after the seal are tagged
   `_act_owned` and dropped (`EventSystem.drop_act_owned`); script-level
   `@collide` entries made after the seal are dropped
   (`CollisionSystem.drop_act_pair_handlers`, pair targets pruned);
   `resolve` pairs go back to the sealed set (`collision._restore_resolve_pairs`:
   act pairs removed, game pairs an act removed or re-tuned come back);
   `HitFeedback._clear_pulses()`. Collision handlers: see
   [Inside a collision handler](#inside-a-collision-handler) (no guard needed).
5. **Done.** Batch teardown without auto-unlink warnings: `change()` marks the
   whole batch (`manager.dying_ids`, the leaving act included) **before** the
   first hook runs; `scena.act._unlink_notice` is installed as
   `state._UNLINK_NOTICE_HOOK` and, during a change, unlinks a dependent whose
   actor is leaving silently, and gives a game dependent the SCENA WARNING
   above. Outside a change the generic warning is unchanged. Census test:
   `TestNoLeaks` (6 cycles; 200 with `SCENA_SOAK=1`) — stable census, no
   zombies (`sched.every_sites` ignored like the other system suites; bound
   asserted).
6. **Done.** Ink message for a stored group (`entity._ink_callable_message`);
   exports (`Act`, `change_act` in `FRAMEWORK_EXPORTS`; `Act` in
   `surface_support.EXCLUDED` — it is never constructed); Guia chapter
   "Atos" (`#atos`, five sections, `validate_guia.py` symbols) and the scope
   table in `#mode-cancela` (`"game"` palco / `"act"` ato atual); a sample
   game (the sketch, with `Text(top_left=)` for the paper `x1=` / `y1=`);
   key edges dropped on a change (SC1); the batch
   held strongly during a change (SC2).

**Mechanism: seal, then diff.** `_seal` records the live game: a `WeakSet` of
every live entity in the registry roster (`registry.live_objects()`), the post effects, background extras,
bounds `_group_handlers`, and script `ready` / `recently` keys. A change
removes what is not in the record — no bookkeeping per spawn. Rules the build
fixed:

- **Only root entities are torn down** (`_owner is None`). Parts leave with
  their owner, so a registered part a *game* object makes after the seal
  (`show_points()` materialising a Derivate Point) is not act-owned.
- **Framework singletons** are marked `_scena_internal` (HUD labels) or are
  skipped by identity (`PostFxStack._hit`, the hit-feedback effect).
- **Current before `setup`**: `Act.__init__` attaches the instance, then the
  actor wrapper runs `setup`. A `change_act` inside `setup` is legal; the
  builder keeps whichever act is current afterwards.
- **Hook errors do not stop a change.** An exception from an `on_destroy`
  (including the "change_act during an act change" `RuntimeError`) is kept;
  the teardown finishes, the target act is built, then it is re-raised.
- **`change_act` after plain `run()` raises** ("This game started with
  run(). To use acts, start with run(Titulo).") — decided 2026-09-28.
- **`__init__` on an Act class raises** at class definition ("build the act
  in setup(self)"): one spelling for building an act.
- **`ActUsageError(TypeError, AttributeError)`** for Entity verbs on an act,
  so engine probes (`getattr(item, "visible", None)`) keep their default.
- The message vocabulary guard (`TestMessagesDoNotSayScene` in
  `tests/test_message_vocabulary.py`) covers `act.py` like every other
  module: messages say "act", and "scene" only for the rendered frame and
  the retired-name errors (see
  [Vocabulary guards](#vocabulary-guards)).

- The module is `scena/act.py` (`Act`, `change_act`); `run(first_act=None)`
  in `orchestration.py`.
- **Ending the top level.** In `_run_loop`, after `callback_if_exists(self, 'setup', …)`
  and the system / error labels: snapshot the world settings; from then on
  every Entity, classless event registration, ownerless Handle, post effect,
  background field, and script-level `ready` / `recently` slot created is
  recorded in the current act's registry.
- **Settings table.** One table lists every author-settable canvas / clock /
  collision property as `restore` or `keep`. The snapshot and restore iterate
  it. A test walks the setters on `ScenaCanvas`, the clock and the collision
  system and fails on any property missing from the table (catches the whole
  "new setting leaks across acts" class).
- **Framework-internal creations are exempt**: `PostStack._hit_feedback()`,
  system labels, debug overlays, cover — anything the framework creates for
  itself. On change, reset their transient state (pending pulses) instead.
- **Changing-act guard.** A flag set from the act's `on_destroy` through
  the rebuild; `change_act` raises while it is set, with the calling hook's
  owner in the message.
- **Batch teardown.** Mark the whole batch as dying (the leaving act too:
  a HUD reading the act's own ink, `self.pontos`, must not warn when the
  act entity goes first); run the act's `on_destroy`; auto-unlink warns
  only for dependents outside the batch. Drain to a fixed point (same pattern
  as `Registry.destroy_all`: an `on_destroy` that spawns is drained too).
- **Collision step.** After a `change_act` inside a handler the existing
  dead-pair rules drop the old act's remaining pairs; see
  [Inside a collision handler](#inside-a-collision-handler).
- Handles keep today's owner rule (mode → entity); only the ownerless fallback
  splits ([Decision 11](#decisions-2026-09-26)): `SCOPE_ACT = "act"` covers
  work created after the top level ends (renamed 2026-10-06, see
  [Retired names](#retired-names)), and `SCOPE_GAME = "game"` covers work
  created before it; `report_author_warning` labels ownerless
  warnings `"<game>"` / `"<act>"` the same way. Built; `test_audio` /
  `test_audio_capture` now expect `"game"` (they never end the top level). The
  Guia's scope lines say palco (no topo) / ato atual (depois) — the mode scope
  table, `play_sound`, `Microphone.record` (done 2026-09-29).
- Sound ring-out ([decision 12](#decisions-2026-09-26)): `cancel_ownerless(SCOPE_ACT,
  release=True)` in `_drop_script_level_work`, `cancel_owner(..., release=True)`
  on the destroy path and on mode leave; `cancel_process` and `Handle.cancel`
  still cut. Tests: `TestActSoundsRingOut` (`test_act.py`), the fate
  matrix `TestSoundRingsOut` and `TestDeclick` (`test_audio.py`), and the
  owner-end invariant in `test_sys_hyp_audio.py`. `kitchen_sink`'s sound is a
  forever loop so the no-leak census still sees it cut.
- **Resolve pairs** (`resolve(a, b)`) follow the same "scoped by when" rule as
  `@collide`, but as a restored set rather than a drop list, because an act
  can also `unresolve` or re-tune a game pair.
- `Act.__init_subclass__` rejects a `setup` with parameters, body-only
  decorators / hooks (`@collide_with` family, class `@leave_playfield`,
  `on_click`, `on_collide`), and blocks direct construction; the act's
  `destroy` / `active` / `tag` / `visible` / `cancel_process` raise (the
  framework tears down through a private path). The class-body `@collide` check
  gets an act-specific message.
- Ink: the callable check gets a group-specific message.
- Tests (when built): game objects survive N changes; act-born entities / handles /
  events / post / background fields / `ready` all gone after a change (census
  via `tests/system_support.py`); every `restore` setting restored (including
  back to the default when the top never set it) and every `keep` setting kept;
  the unclassified-setter test; `canvas.shake` still works after a change made
  mid-shake (singleton not removed); a fade cover survives the change; no
  auto-unlink warnings on teardown of a linked HUD + source; the script-level
  `setup` hook's objects and system labels survive; restart builds a fresh
  instance (one tagged hero, not two); act `on_destroy` sees its objects alive;
  `change_act` from `update`, a timer, a `@collide` handler (no pair of the
  old step reaches the new act), an act's own async mode; `change_act`
  from an act's or an entity's `on_destroy` during a change raises and leaves
  the target act built; a `@collide` inside `setup` is gone after the change
  while a top-level one stays; body-only decorators on an Act raise; every
  error message above; a restarted act with an already-true `@when` (edge
  documented); no zombies after a soak of act changes.
