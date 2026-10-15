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

F3 is the rule the C, L and T laws below are cases of: a command acts at
once; a pass already running keeps what it chose at its start.

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| F1 | A frame runs its phases once each, in one order: input poll (key and mouse callbacks), `update`, process tick, collision (handlers, then resolve), leave playfield, hover, flush (`@when` / `@on_change`), pre-draw (transients, covers), edge expiry; then the draw. An explicit `flush()` from author code is the author's, not a phase. | holds | model `frame.F1`; `test_sys_frame_order` | [Scena Design.md — Frame order](Scena%20Design.md#frame-order) |
| F2 | A door that belongs to a phase runs only in it: `update`; timers and `on_update` in the tick; enter and stay handlers in collision (an exit runs where its contact ends: the step, a destroy, a park); `@leave_playfield`; `@hover`; `@when` / `@on_change` in flush; key and mouse callbacks in the poll; pre-draw callbacks. Destroy-time hooks, act builds, actor `setup` and formula pulls run where they are called (a linked appearance field or flag is pulled at the start of hover and at the head of the draw). | holds | model `frame.F2` | [Scena Design.md — Frame order](Scena%20Design.md#frame-order) |
| F3 | **The snapshot rule.** A command (destroy, park, `untag`, a group change, `collidable`, an act change, a creation, a timer, a pose write) takes effect for the author at once (L1). A pass already running finishes against what it chose at its start: it pays what it owed when the command came (the rest of a contact's handlers, C3; its response, a removed partner as a ghost, C8; an exit the command caused, after that contact's handlers, C2) and starts nothing new with what was removed (C4, L3, L4, T3); what the command made waits for that loop's next pass (T2): a tag or rule a handler adds counts for contacts from the next step, one it removes stops at once, its exit at the next step. Flush runs to quiet: a watch a callback affected fires in the same flush, one it made waits for a change. A walk over a group copies its members at entry. An act change cancels what the ending act owed (its handlers, its own hooks on game bodies, exits and ghosts: C6, L5); the game's own work goes on. | holds | chaos `owed`; `test_laws_chaos`, `test_laws_chaos_families` | [Scena Design.md — Commands during a pass](Scena%20Design.md#commands-during-a-pass-the-snapshot-rule) |

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
A contact is per rule: a rule's contact with a touching pair begins at the
first commit that finds the rule matching it (the pair began touching, a side
joined a tag, the rule was declared or set) and ends at the first that finds
it not matching (the pair apart, a side left the tag), or at a destroy, a
park or an act change. A tag or rule a handler adds counts from the next step.

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| C1 | An enter handler runs only for a contact that began this step for its rule (the pair began touching, or the rule began matching the touching pair); a stay handler only when its rule matched the touching pair at the last step too. The step commits its contacts, and reads which rules match them, before the first handler runs, so a raising handler cannot make a pair enter twice. | holds | model `collision.C1`; `test_collision.TestARuleAContactGainsOrLosesMidContact` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C2 | A step runs its enters, then its stays, then its exits; a fast body's enters run in time-of-impact order. An exit a destroy causes runs at the destroy; one a handler causes runs after that contact's handlers. | holds | model `collision.C2` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C3 | Every handler that matches a contact runs, chosen before the first one runs: a handler that destroys, parks or untags a side does not hide the others (the outcome does not depend on spawn order or on how a handler is declared). | holds | `test_collision.TestEveryEnterHandlerOfAContactRuns`; the fixture's mine | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C4 | A body a handler destroys or parks enters and stays in no other pair that step. | holds | model `collision.C4` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C5 | An exit handler runs only for a contact its rule entered, once; a destroy, a park, an untag or a group change ends that rule's contact with its exit, also while another rule keeps the pair touching. | holds | model `collision.C5`; `test_collision.TestExitAfterGroupChange`, `TestARuleAContactGainsOrLosesMidContact` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C6 | An exit runs the handlers its contact entered under, even when a tag left meanwhile (one held at the last step: a tag joined and left between two steps is no change); an exit handler dropped meanwhile (an act change, a destroy) does not run. | holds | `test_collision.TestExitAfterGroupChange` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C7 | A destroyed body is in no contact after its destroy returns: no later step commits a pair with it. | holds | model `collision.C7` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| C8 | Every handler of a step runs before that step's resolve; a resolve partner a handler removed is still a wall for the survivor's sweep that step (a ghost: Breakout bounces off the brick it breaks, where it touched it), and is in no contact. | holds | model `collision.C8`; `test_collision.TestBounceOffAPartnerAHandlerRemoved` | [Collision Design.md — Partner removed by a handler](Collision%20Design.md#partner-removed-by-a-handler-ghost-contact) |

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

## Timers

`after` and `every` count world time (scaled by `clock.scale` and the
owner's `time_scale`, stopped by a pause, at most `MAX_FRAME_DT` a frame).

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| T1 | A timer fires on the first tick where its owner's world time since its start reaches its delay: a whole number of frames lands on that frame, never a frame late or early by rounding. | holds | model `timers.T1`; `test_process.TestDueOnTheExactFrame` | [Scena Design.md — Clocks](Scena%20Design.md#clocks) |
| T2 | A timer's time starts at the first process tick that begins after it is made: one made before the tick (in `update`, an input hook) counts that frame; one made in the tick or later counts from the next. A self re-arming `after` is "at least p apart", not a rate (use `every`). | holds | model `timers.T2` | [Scena Design.md — Clocks](Scena%20Design.md#clocks) |
| T3 | A parked owner's timers neither fire nor gain time; a dead owner's never fire. | holds | model `timers.T3` | [Actors Design.md — `active` (park)](Actors%20Design.md#active-park) |
| T4 | `every` fires once per interval of world time, at most `ceil(MAX_FRAME_DT / interval)` times in one tick; debt beyond that keeps only its phase. | holds | model `timers.T4`; `test_process.TestEveryCountsWorldSeconds` | [Scena Design.md — Clocks](Scena%20Design.md#clocks) |
| T5 | A timer whose callback is a method of an actor, or a closure over its `self`, is owned by that actor and dies with it (PA4). | holds | equation `E6`; `test_process.TestClosureOverSelfIsOwnedLikeTheBoundMethod` | [Actors Design.md — Ownership](Actors%20Design.md#ownership-no-on) |
| T6 | Work scheduled on a destroyed actor registers nothing: it never ticks, never runs. | holds | model `timers.T6` | [Actors Design.md — Ownership](Actors%20Design.md#ownership-no-on) |

## Invariance

Pairs of programs an author believes equivalent behave alike (the
equations: no expected value, only agreement).

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| V1 | A game's events (contacts, timers, creations, destroys, act changes) happen at the same game times at 30, 60 and 144 Hz and at uneven frame times, within a frame of each pacing. Known limits: an author's own Euler step and a self re-arming `after` drift by frames; many bodies bouncing off each other amplify what is left of frame dependence in many-body contacts (`bolas`, `entropia`). | holds | equation `E1` | [Scena Design.md — Clocks](Scena%20Design.md#clocks) |
| V3 | A game does not depend on the order of two independent constructions. One exception, documented: a body that enters two partners in the same step without crossing either (a tie within half its thickness) enters them in creation order. | holds | equation `E3` | [Collision Design.md — Swept detection](Collision%20Design.md#swept-detection-fast-bodies) ("Order") |
| V4 | A contact rule acts alike declared as a module `@collide`, a class `@collide_with` or an `on_collide` property (the property reaches any *registered* body: the partner joins by a rule or `collidable = True`), and whatever other rules pair the same bodies: a no-op rule beside it changes none of its calls (CD3). | holds | equations `E4`, `E15` | [Collision Design.md — Pipeline](Collision%20Design.md#pipeline) |
| V5 | A game built at the top of the file or in its first act's `setup` runs alike while that act lasts. | holds | equation `E5` | [Act Design.md — Lifetime: the game and the act](Act%20Design.md#lifetime-the-game-and-the-act) |
| V10 | Moving the whole world (65536, 4096) or mirroring it changes no motion: a mirrored world moves as the mirror of the world (no left / right bias). | holds | equations `E10`, `E11` | [Collision Design.md — Resolution](Collision%20Design.md#resolution) |
| V12 | Multiplying every mass by the same factor changes no motion (only mass ratios count). | holds | equation `E12` | [Collision Design.md — Mass split](Collision%20Design.md#mass-split-between-two-movable-bodies) |
| V13 | At 30, 60 or 144 Hz a body stays within one frame of travel of where it is at 60 Hz (over a few seconds). | holds | equation `E13` | [Scena Design.md — Clocks](Scena%20Design.md#clocks) |
| V14 | Doubling the world and its speeds doubles every path, within the budget: the slop and skin are absolute (0.08 DU), a difference below the budget at authoring scales. | holds | equation `E14` | [Collision Design.md — Resolution](Collision%20Design.md#resolution) |
| V8 | Breaking a resolve partner in its handler or between frames gives the survivor the same bounce and the same path, also off two partners at once. | holds | equation `E8` | [Collision Design.md — Partner removed by a handler](Collision%20Design.md#partner-removed-by-a-handler-ghost-contact) |

## Motion

What `resolve` does to bodies, as bounds (an exact physics model would
re-implement the solver): each law holds within the position budget.

| Law | Statement | Status | Checked by | Detail |
| --- | --- | --- | --- | --- |
| P1 | After resolve, a resolved pair overlaps by at most the slop (`_RESOLVE_SLOP`). A stack (a body between two partners) may overlap more: a documented non-goal. | holds | model `motion.P1` | [Collision Design.md — Resolution](Collision%20Design.md#resolution) |
| P2 | Resolve adds no energy: a body answered only by still STATIC partners leaves no faster than it came (`bounce` ≤ 1). | holds | model `motion.P2` | [Collision Design.md — Resolution](Collision%20Design.md#resolution) |
| P3 | Between two movable bodies, a bounce keeps their momentum: each changes by the inverse of its mass. | holds | model `motion.P3` | [Collision Design.md — Resolution](Collision%20Design.md#resolution) |
| P4 | A STATIC body never moves under resolve; a stack does not sink into it. | holds | model `motion.P4`; `test_resolve_solver.TestStaticHolds` | [Collision Design.md — Settle direction and STATIC under a stack](Collision%20Design.md#settle-direction-and-static-under-a-stack) |
| P5 | An idle body resting on still STATIC partners (no sideways motion of its own, not riding) is not moved sideways: it does not creep down a ramp. A body falling onto a slope or a corner slides there (no friction). | holds | model `motion.P5`; `test_resolve_solver.TestIdleSlope` | [Collision Design.md — Resolution](Collision%20Design.md#resolution) |
| P6 | A body standing on a moving partner moves with it, at every frame rate. | holds | `test_laws_motion.TestRiderMovesWithItsLift`; `test_resolve_solver.TestRiderCarry` | [Collision Design.md — Riders](Collision%20Design.md#riders-a-body-standing-on-a-moving-partner) |
| P7 | A body that crosses a target within one frame still registers the contact (swept detection, past half its thickness per frame). | holds | `test_sys_fast_shots.TestFastShotsAcrossPacings` | [Collision Design.md — Swept detection](Collision%20Design.md#swept-detection-fast-bodies) |
