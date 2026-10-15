# Scena Laws

The engine's behaviour in time, identity and authority, as short laws. Read
this whole page before you change frame order, lifetime (create, park,
destroy, act change), contacts, input ownership or timers. Each law states
**today's** behaviour and is checked on every run of the test families by a
model over a recorded trace; the details live in the companion docs.

**What a law promises.** Behaviour a player or an author can see. A law
about motion holds within a perceptual budget (position 0.5 px per event,
2 px over a run; angle 2°; speed 2 %; timing ±1 frame where it says so). The
engine does not promise theoretical precision: a difference within budget is
not a bug unless it comes from a wrong calculation.

**How it is checked.** `tests/laws/`: a recorder outside the engine
(`sys.monitoring`; nothing in `scena/` knows), a model per law group, canaries
that plant a bug of each law's class. Triage of what they find:
[Testing Design.md — Laws and equations](Testing%20Design.md#laws-and-equations).

**Status.** *holds*: checked, no unexplained finding. *open*: the engine
breaks it today (a finding id says where).

## Frame

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| F1 | A frame runs its phases once each, in one order: input poll (key and mouse callbacks), `update`, process tick, collision (handlers, then resolve), leave playfield, hover, flush (`@when` / `@on_change`), pre-draw (transients, covers), edge expiry; then the draw. An explicit `flush()` from author code is the author's, not a phase. | holds | model `frame.F1`; `test_sys_frame_order` | [Scena Design.md — Frame order](Scena%20Design.md#frame-order) |
| F2 | A door that belongs to a phase runs only in it: `update`; timers and `on_update` in the tick; enter and stay handlers in collision (an exit runs where its contact ends: the step, a destroy, a park); `@leave_playfield`; `@hover`; `@when` / `@on_change` in flush; key and mouse callbacks in the poll; pre-draw callbacks. Destroy-time hooks, act builds, actor `setup` and formula pulls run where they are called. | holds | model `frame.F2` | [Scena Design.md — Frame order](Scena%20Design.md#frame-order) |

## Lifetime

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| L1 | `destroy()` is synchronous: when it returns, the object is dead (out of its groups, off the draw list, its work cancelled). | holds | model `lifetime.L1`; `test_sys_lifetime` | [Actors Design.md — `on_destroy`](Actors%20Design.md#on_destroy) |
| L2 | `on_destroy` runs at most once, before the teardown starts, while the object is whole; a second `destroy()` does nothing. | holds | model `lifetime.L2` | [Reactive Design.md — Destroy and teardown](Reactive%20Design.md#destroy-and-teardown) |
| L3 | After its destroy returns, none of an object's own methods runs again as a hook (handler, timer, `on_update`, formula) — except the rest of the contact it died in (C3: every handler of a contact runs, the dying body's other methods too). A module rule that receives it (an exit with a dead `me`) is the contact laws' business. | holds | model `lifetime.L3`; `test_sys_lifetime` | [Actors Design.md — Ownership](Actors%20Design.md#ownership-no-on) |
| L4 | A parked actor (`active = False`) runs none of its own methods as a timer, `on_update`, contact, hover or leave hook until it resumes; its exits still fire and its `@when` conditions keep polling. | holds | model `lifetime.L4` | [Actors Design.md — `active` (park)](Actors%20Design.md#active-park) |
| L5 | An act change runs every `on_destroy` of the ending act's objects before it tears down the first of them: a hook can read any sibling. | holds | model `lifetime.L5` | [Act Design.md — `change_act`](Act%20Design.md#change_act) |
| L6 | An act change builds the next act only after the ending act's objects are gone, and tears down nothing made at the top of the file. | holds | model `lifetime.L6`; `test_act` | [Act Design.md — Lifetime: the game and the act](Act%20Design.md#lifetime-the-game-and-the-act) |

## Contacts

A collision step finds the contacts (the continuous layer), commits them,
runs the handlers, then resolves. The laws are about what the handlers see.

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| C1 | An enter handler runs only for a pair whose contact began this step; a stay handler only for a pair that was touching at the last step too. The step commits its contacts before the first handler runs, so a raising handler cannot make a pair enter twice. | holds | model `collision.C1` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C2 | A step runs its enters, then its stays, then its exits; a fast body's enters run in time-of-impact order. An exit a destroy causes runs at the destroy; one a handler causes runs after that contact's handlers. | holds | model `collision.C2` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C3 | Every handler that matches a contact runs, chosen before the first one runs: a handler that destroys, parks or untags a side does not hide the others (the outcome does not depend on spawn order or on how a handler is declared). | holds | `test_collision.TestEveryEnterHandlerOfAContactRuns`; the fixture's mine | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C4 | A body a handler destroys or parks enters and stays in no other pair that step. | holds | model `collision.C4` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C5 | An exit runs only for a pair in contact, once per contact; a destroy, a park, an untag or a group change ends a contact with its exit. | holds | model `collision.C5`; `test_collision.TestExitAfterGroupChange` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C6 | An exit runs the handlers its contact entered under, even when a tag left meanwhile; an exit handler dropped meanwhile (an act change, a destroy) does not run. | holds | `test_collision.TestExitAfterGroupChange` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C7 | A destroyed body is in no contact after its destroy returns: no later step commits a pair with it. | holds | model `collision.C7` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C8 | Every handler of a step runs before that step's resolve; a resolve partner a handler removed still gives the survivor this contact's velocity response (a ghost contact: Breakout bounces off the brick it breaks). | holds | model `collision.C8`; `test_collision.TestBounceOffAPartnerAHandlerRemoved` | [Collision Design.md — Partner removed by a handler](Collision%20Design.md#partner-removed-by-a-handler-ghost-contact) |

## Input

Who gets a key, a character or a button, from down to up. A press belongs
to whoever took it: the focused box (the keys it claims), a widget or a
shape under the pointer, or the script.

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| I1 | Every down the script got gets exactly one up, also when the act changed, a modal opened or a box took focus in between. | holds | model `input.I1`; `test_input_streams.TestUpsCrossAnActChange` | [Scena Design.md — Frame order](Scena%20Design.md#frame-order) (pointer, keys) |
| I2 | An up goes where its down went: a key or a button a box, a widget or a shape took never ends in the script's up, nor as a script click. | holds | model `input.I2` | [Canvas Design.md — TextInput](Canvas%20Design.md#textinput) |
| I3 | A repeat follows its press: never to the script for a press it did not get or one made in an old act; never into a box that took focus after the script got the press. | holds | model `input.I3`; `test_input_streams.TestARepeatFollowsItsPress` | [Canvas Design.md — TextInput](Canvas%20Design.md#textinput) |
| I4 | A typed character follows the key that made it: the character of a key the box did not get is the script's (`on_char`), never typed into the box. | holds | model `input.I4`; `test_input_streams.TestACharFollowsItsKey` | [Canvas Design.md — TextInput](Canvas%20Design.md#textinput) |
| I5 | A press a widget gave up when it left (destroyed, act change) ends with no release to any widget and no script up; a held Button writes its `value_off`. | holds | model `input.I5`; `test_input_streams.TestAHeldButtonThatLeavesLetsGo` | [Canvas Design.md — TextInput](Canvas%20Design.md#textinput) |
| I6 | `keyp.once` is True only in the frame of the press; an act change and a modal swallow the unread edge. | holds | `test_keyp.TestOnceIsFrameScopedInFrames` | [Scena Design.md — Frame order](Scena%20Design.md#frame-order) |

## Invariance

Pairs of programs an author believes equivalent behave alike (the
equations: no expected value, only agreement).

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| V3 | A game does not depend on the order of two independent constructions. One exception, documented: a body that enters two partners in the same step without crossing either (a tie within half its thickness) enters them in creation order. | holds | equation `E3` | [Collision Design.md — Swept detection](Collision%20Design.md#swept-detection-fast-bodies) ("Order") |
| V4 | A contact rule acts alike declared as a module `@collide`, a class `@collide_with` or an `on_collide` property (the property reaches any *registered* body: the partner joins by a rule or `collidable = True`). | holds | equation `E4` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| V8 | Breaking a resolve partner in its handler or between frames gives the survivor the same bounce. | open (LW2: two partners at once) | equation `E8` | [Collision Design.md — Partner removed by a handler](Collision%20Design.md#partner-removed-by-a-handler-ghost-contact) |

## Still to write

Timers (T) and motion (P) join as their stages land;
until then their rules live only in the companion docs.
