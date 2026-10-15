# Collision Design

Shared collider registry and narrow-phase pipeline for Shape, Sprite, and SpatialFx.
**Happy path for this subsystem** — pick one row; do not read the rest. Hub:
[Scena Design.md](Scena%20Design.md). Author calls:
[Guia da API](../docs/pt/guide/index.html#colisao). Sprite bake:
[Sprite Design.md](Sprite%20Design.md#auto-hitbox-shapeauto).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Who tests whom / ANYTHING | [Enrollment rule](#enrollment-rule) |
| Pipeline / proxy AABB | [Pipeline](#pipeline) |
| Does touching count? / exact tangency | [Touching and tangency](#touching-and-tangency) |
| `@collide` on a resting / resolved body | [Resting contact (skin)](#resting-contact-skin) |
| Fast shots / tunnelling (`@collide`) | [Swept detection (fast bodies)](#swept-detection-fast-bodies) |
| `resolve` / mass / bounce | [Resolution](#resolution) |
| Bounce off a body destroyed in `@collide` | [Partner removed by a handler](#partner-removed-by-a-handler-ghost-contact) |
| One-way / jump-through (`only=`) | [One-way pairs: `only=`](#one-way-pairs-only) |
| Walker snags on / falls into a tile seam | [Seam lips (step-up)](#seam-lips-step-up) |
| Mutual `resolve()` pools / cost | [Resolve hot path](#resolve-hot-path) |
| Instant set vs travel | [Motion vs placement](#motion-vs-placement) |
| Orbit / `rotate_by(about=)` sweep, spin not swept | [Orbit chord](#orbit-chord) |
| Spinning hazards / rotating obstacles tunnel | [Spin (not swept)](#spin-not-swept) |
| Relative-frame sweep / glue | [Relative-frame sweep](#relative-frame-sweep) |
| Two movable bodies: who gives in a sweep stop (mass split, crate push, springy body) | [Mass split between two movable bodies](#mass-split-between-two-movable-bodies) |
| Floor snap / grounded flicker | [Floor snap / grounded flicker](#floor-snap--grounded-flicker) |
| Ledge / "will I fall?" (`floor_below`) | [Floor ahead: `floor_below`](#floor-ahead-floor_below); cost: [`floor_below`: cost](#floor_below-cost) |
| Tile hull as an AABB prim | [Axis-aligned hulls](#axis-aligned-hulls) |
| Box vs polygon sweep (closed form, GJK skin) | [Polygon sweeps](#polygon-sweeps) |
| Queries / raycast | [Queries](#queries-on-demand) |
| Sprite colliders | [Sprite colliders](#sprite-colliders) |
| Hitbox parts (detect-only) | [Hitbox parts](#hitbox-parts) |
| Main hitbox off (`g.hitbox.active = False`) | [Main hitbox switch](#main-hitbox-switch) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/` or the private archive / proposals unless a named campaign or visual proof is the task.

## Router

| Need | Start | Also |
| --- | --- | --- |
| Collision **engine** / `resolve` | `collision.py` | `entity.py` (enroll) |
| `@collide*` **sugar** | `interaction.py` | `collision.py` (engine) |
| Sprite hitbox **bake** | `atlas.py` | [Sprite Design.md](Sprite%20Design.md#auto-hitbox-shapeauto) |
| Mutual `resolve()` **cost** | `collision.py` (`_resolve_partners`, `_settle_body`, `_declared_broad_pairs`, `_world_prims`) | [Resolve hot path](#resolve-hot-path) |
| `resolve(..., only=)` | `collision.py` (`_normalize_only`, `_OnlyGate`, `_only_view`, `_resolve_partners`) | `tests/test_resolve_only.py` |
| Riders, settle direction, STATIC holding under a stack | `collision.py` (`_carry_riders`, `_sweep_and_slide`, `_settle_normal`, `_nudge_pair_along`, `_share_sweep_stop`) | [Riders](#riders-a-body-standing-on-a-moving-partner), `tests/test_resolve_solver.py` |
| `floor_below` | `collision.py` (`CollisionSystem.floor_below`, `_floor_march`, `_floor_probe_envelope`, `_QueryOnlyGate`, `_note_floor_probe`) | `entity.py` (`Graphic.floor_below`), `tests/test_floor_below.py`, `tests/test_floor_below_fast.py` |
| `only=` read-only guard | `purity_check.py` (`check_read_only`, `_READING`) | `formula_check.py` (locator, context) |
| Simultaneous contacts, bounce sub-step, partner removed by a handler | `collision.py` (`_earliest_toi` ties, `_joint_stop`, `_cone_response`, `_substep_restitution`, `_GhostPartner`, `_answer_unreached`) | [Joint stop](#joint-stop-simultaneous-contacts), [Bounce sub-step](#bounce-sub-step), `tests/test_joint_response.py` |
| Swept detection (fast bodies) | `collision.py` (`_commit_pending_motion`, `_declared_broad_pairs`, `_swept_contacts`, `note_collider_motion`); orbit chord: `entity.py` (`_rotate_as_motion`, `_rotate_as_placement`) | `tests/test_collision.py` (`TestSweptDetection`, `TestOrbitMotion`), `tests/test_sys_fast_shots.py` |

**Do not slurp:** `collision.py`.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `@collide` on a script | sugar in `interaction.py` | the sweep/AABB engine (`collision.py`) |
| Formula `group["name"] @=` | decoration-time membership | a live collision tag |
| `hitbox_shape="auto"` bake | `atlas.py` | runtime pairs (`collision.py`) |
| Outline crossing | `geom.py` | contact `CollisionInfo.points` |
| Empty `info.point` | exit (no current contact) | missing clip on enter (now a support witness) |

## Not in this doc

See the list at the **bottom** of this file. Do not open those unless the jump box sent you there.


# Enrollment rule

**Colide com quem você nomeou; `collidable` só liga ou desliga o corpo; empurrar é `resolve`.**

Overlap tests in `step()` run only for **declared** relations:

| Declaration | Enrolls bodies | Tests in `step()` | Callback | Auto-push |
| --- | --- | --- | --- | --- |
| `@collide(a, b)` | both sides | that pair | yes | no |
| `resolve(a, b)` | both sides | that pair | no | yes |
| `on_collide` / `@collide(..., ANYTHING)` | this body (and its pair groups, like `collidable = True`) | this × every enrolled | yes | no |
| `collidable = True` | this body | **no pair by itself** | no | no |
| `collidable = False` | opt-out (sticky; recorded even before any enrollment) | — | — | — |

`collidable = True`, `on_collide = f` and resume from park join through one
path (`Entity._enter_collision`): `ensure_collider` copies the actor's
callbacks into the new Collider, and the actor enrolls in its pair groups.
Park leaves through `Entity._leave_collision` (exits fire, callbacks stay on
the actor, no opt-out). `ensure_collider` refuses a parked actor. The engine
reads a part's or actor's play state from the stored flag (`_active`), not
the public `active`: a linked `hb["active"]` runs once per step
(`_refresh_linked_parts`), never once per contact (graphics review HP5).

`collidable = True` puts a hitbox in the registry for **unnamed** queries (`query_point` / `query_circle` / `query_sector` / `query_shape` / `raycast` with `group` omitted or `ANYTHING`), and as a partner for bodies that declared `ANYTHING`. It does **not** create pairwise tests against other flagged bodies. A query that **names** a group does not need this flag — see [Queries (on-demand)](#queries-on-demand).

**A tag enrolls while a rule names it.** `_pair_tags` is derived from the live
`@collide` and `resolve` declarations. When the last one naming a tag goes (act
change, `unresolve`, the destroy of an object side such as `@collide(boss,
"bullet")`), `retire_unused_pair_tags` drops the tag: later members are not
enrolled, and a body enrolled **only** through it leaves collision (exits fire,
`collidable` reads `False`). A body some declaration still names stays: an
author `collidable = True` (`_collision_opt_in`), its own `on_collide*`, another
live tag, an instance side, a registered hitbox part. Before 2026-10-09 a tag
never left: an act's `@collide("coin", "hero")` enrolled every later coin of
every act, each paying a proxy per step and answering unnamed queries (review
S8-7).

Enrollment keys on **string tags** (and live tag `group["name"]`). A formula name
(`group["enemies"] @=`) is not a collision tag — partners stay decoration-time, like
a snapshot. Prefer the source tag strings in `@collide` / `resolve`.
[Actors Design.md — Formula groups](Actors%20Design.md#formula-groups).

**Query info is the handler's view.** `test_collision(a, b)` returns the same `CollisionInfo` a `@collide(a, b)` handler would get: `info.a` / `info.b` are the author's bodies (a `Collider` for its pieces when it is enrolled; a non-enrolled shape answers as itself, never as the throwaway probe it was tested through), the normal points from `a` to `b`, `side` is `a`'s. The narrow phase works in canonical (lower `id()` first) order, so every path that hands info to an author goes through `_oriented_info` (bug PM11: the query returned the raw canonical payload). Guard: `test_collision.TestQueryInfoIsTheAuthorView`.

**A piece that is also a body (AC10, decided 2026-10-10: two boundaries).** A piece of a multi-piece `Collider` may be a body of its own (`collidable = True`, or a rule naming its group enrolls it): the weak-point pattern. The two stay separate bodies with one coherence rule each: the body never pairs with its own pieces' bodies, and two pieces' bodies of one Collider (two weak points) never pair with each other (`CollisionSystem._multi_bodies`, registered at `register`; the broad phase's `kin` pair set, like a sprite and its hitbox parts), so it never touches or pushes its own torso; queries put multi-piece bodies first (`_bodies_first`: `query_point`, `query_circle`, `query_sector` — its wedge and `spread=0` segment paths too, since the 0.8.0 release audit — and `query_shape`) and a `raycast` tie goes to the multi-piece body, whatever line ran first; `query_shape(piece)` does not report the body the piece belongs to. A rule on `ANYTHING` sees both bodies (two contacts for one shot): documented, by design. Guard: `test_collision.TestPieceThatIsAlsoABody`; pattern: `test_documented_patterns.TestWeakPoint`; Guia: Collider, "Ponto fraco".

**Compound body (`Collider`).** `Collider([torso, head])` is author API (in `scena.__all__`, since the Guia's only import is `from scena import *`): several shapes collide as one identity, and handlers see the Collider. Its author surface is `Collider(shapes)`, `.shapes` and the three `on_collide*` callbacks (properties: a set refuses an `async def` and keeps `ANYTHING` interest in sync; the class has no `__setattr__` hook, so the step's internal writes are plain slot writes); everything the engine needs is underscored (`_pair_targets`, `_add_pair_target` / `_remove_pair_target`, `_sync_anything_interest`, `_wants`, `_group_tags`, `_identity`, `_unregister`, and the constructor keywords `_identity_shape` / `_register` / `_bind`, hidden by the published `__init__.__signature__`). Every piece must be an `Entity` (shape, sprite, SpatialFx) or a `Hitbox` part, checked for every path (registered body or query probe) before any mutation: anything else raises `TypeError: Collider pieces must be shapes or sprites; got function. Write Collider([torso, head]).` (the value shown only for `None` / numbers, as for Pair sides). Before that check, any weak-referenceable object (a function) registered a body with no geometry that nothing could unregister: a `Collider` has no `destroy` (A33). Tests: `tests/test_collision.py` `TestCompoundCollider.test_collider_comes_with_the_star_import`, `TestCompoundCollider.test_non_shape_pieces_are_refused_before_registration`.

A destroyed body never re-enters the index: `ensure_collider` raises `DestroyedError` for it, so every path that enrolls on demand (`resolve_now`, pair enrollment) refuses a dead actor (A6 in [Testing Design](Testing%20Design.md#a--api-surface)).

## ANYTHING interest lifecycle

`ANYTHING` in `_pair_targets` means **this body tests against every other enrolled participant** in broad phase. It is kept only while a live declaration needs it:

| Source | Adds `ANYTHING` | Removed when |
| --- | --- | --- |
| `on_collide` / `on_collide_stay` / `on_collide_exit` ≠ `None` | yes | all three callbacks are `None` |
| `@collide(x, ANYTHING)` / `@collide_with(ANYTHING)` | yes (on the named side) | handler dropped (destroy / act change / module unload) |
| `resolve(x, ANYTHING)` | yes | `unresolve(x, ANYTHING)` / act change |

A subclass may define `on_collide(self, other, info)` / `on_collide_stay(self, other, info)` / `on_collide_exit(self, other)` as methods: `Entity.__init_subclass__` wraps each in `collision._pair_method_adapter`, so the method gets the other body and the info like a property callback `fn(me, other, info)` gets them. Before, the bound method was called by arity with `self` passed again: `other` was the object itself (AC6; `test_collision.TestOnCollideMethodArguments`, every family × the three hooks). A `Collider` subclass is not an Entity: its methods override the three properties and are called as the property callback is (`fn(me, other, info)`, so a method takes `self, me, other, info`); construction counts them as set (ANYTHING interest), and `Collider.__init_subclass__` refuses an `async def` one at the class line, as the setters refuse it at the assignment (`test_cache_gaps.TestColliderSubclass`).

Every door that drops a pair re-derives `ANYTHING` from what is left
(`_prune_pair_targets` → `_sync_anything_interest`, which counts callbacks,
handlers and resolve pairs). Before 2026-10-09 the prune skipped `ANYTHING`
and `unresolve` never pruned: `unresolve(hero, ANYTHING)` and an act's
`@collide(hero, ANYTHING)` on a game hero left the hero pairing with every
body for good (review S8-4; `TestAnythingInterestLifecycle`,
`test_act.TestActOwnsItsRegistries`).

Clearing `on_collide = None` **silences the object callback** and drops callback-sourced `ANYTHING`; **`@collide(a, b)` handlers on the same contact are unaffected** (dispatch runs object callbacks first, then pair handlers). If `@collide_with(ANYTHING)` (or `@collide(self, ANYTHING)`) still applies, `ANYTHING` stays.

# Pipeline

Happy path each `step()` (`collision.py`). Search; do not slurp.

1. **Enroll** — `@collide` / `resolve` string tags enroll on construct / group change (not a full group walk each `step()`). `on_collide` enrolls + declares `ANYTHING`.
2. **Proxy AABB** — refresh a cheap world AABB per enrolled collider (closed-form / circumradius / cached sprite local extents turned by the heading when possible; never tighter than the exact prim union). In-place translation when only the pose translates. Not a classic fat AABB (permanent circumradius pad). Tight-when-axis-aligned OBB extents; circumradius only where rotation would otherwise rebuild prims just for the proxy. Tiny `_PROXY_EPS` is float robustness, not a fat pad. Exotic kinds (Line, Track, …) may fall back to an exact snapshot (Track: baked samples + half `line_width`). SpatialFx uses `_domain_aabb` (never tighter than `_collision_specs`); pose key includes `_pad_frame` / `_beam_frame` / `_point_frame` size. Graphics put live angle / size in the same extra so `shape.angle =` rebuilds even when `_collision_epoch` was not bumped. **RegularPolygon** extra is `(rot, scale, angle, radius, side)` from Defining slots (no vertex walk — verts are Derivate). **Sprite** extras pack the **hitbox** pose box (`_hitbox_pose_wh` — reference cell, not the current blit) plus heading / flip / offset, so `play()` that only retargets drawn aspect does not resize the collider. **Track** extra is `(rot, scale, line_width, rebuilds, begin, end)` so bake / thickness / stroke-window changes rebuild the stroke tube.
3. **Broad phase** — `_declared_broad_pairs`: AABB overlap only on pairs from `@collide` handlers, `resolve()` registrations, and `ANYTHING` expansion (no full n×n over all colliders). Self-paired tags (`resolve("ball", "ball")`) iterate `i < j` once. Swept proxy boxes (start-of-frame ∪ end, for resolve bodies and this frame's fast colliders) are built once per `step()`; pools of 8+ (same-tag, and cross-tag when both sides are 8+) use a numpy AABB test on that array. See [Resolve hot path](#resolve-hot-path).
4. **Exact prims** — build world prims only for overlapping pairs; prim-AABB reject; then narrow (circle/AABB fast paths, SAT for polygons, GJK+EPA when either prim is an ellipse). A standing `resolve()` pair that does not overlap is still a contact when its GJK gap is within `_CONTACT_SKIN` — see [Resting contact (skin)](#resting-contact-skin). On a step with a fast collider, a second pass tests that collider's pairs along the frame's path — see [Swept detection (fast bodies)](#swept-detection-fast-bodies).
5. **Handlers** — `@collide` / stay / exit run in the same `flush` window as `@when` / `@on_change` (see [Scena Design.md — Datapath](Scena%20Design.md#datapath)). Handlers may start processes; first tick next frame is fine. This frame's contacts are committed **before** handlers run, so a handler that destroys a partner — even in the frame the pair entered — finds the pair and fires its exit, and a raising handler cannot leave stale contacts that re-fire `enter`. Destroying one partner fires `@collide_exit` for the survivor (and the dying body, while it still exists) before its handlers are dropped, and that pair is not entered again. Every other way out of the system does the same: `collidable = False` fires exit for its current pairs and drops those contact keys (so a later collider reusing the same `id()` cannot inherit them); a collider pruned for having no shapes drops its keys silently (no identity left to report). Enter and stay are skipped when either side is already out of play, so a body a handler destroyed enters no *other* pair this step: one bullet cannot damage a second enemy (review 2026-10-09 S8-2). **Within** one contact, every enter (and every stay) handler runs (PB5, 2026-10-14): `_dispatch_contact` lists the handlers that match — `on_collide*` callbacks, class `@collide_with*` methods, module `@collide*` — before the first runs, so a handler that destroys or parks a side does not hide the rest; they get the dead-but-readable partner (verbs on it are no-ops or refuse). Before, the rest stopped, and since per-instance `@collide_with` handlers are appended at construction, whether a `Tiro` that destroys itself let the `Inimigo` score depended on which was spawned first (the same for a module rule and a class method). A destroy or park in those handlers ends the contact, but its exit waits until the contact's last handler has run, so for one contact an author always sees its enter (or stay) handlers, then its exit: an enter / exit counter reads +1 then −1 whichever handler destroys. The exit's handlers are chosen at the destroy, while the leaving side still has its tags and handlers (`_end_contacts_of` → `_deferred_exit` for `_contact_key`), and run in a `finally` after the contact (`_run_exit`), so a raising handler does not lose it. One exception keeps the lifetime rule (a destroyed actor runs no hook of its own: `test_sys_lifetime`): the leaving body's *own* exit hooks — its `on_collide_exit`, its `@collide_with_exit` methods, an `@collide_exit(body, …)` naming it — still run inside the destroy, while it exists (`_own_hook_of`); module tag handlers and the survivor's hooks wait. The dying body's *other* open contacts exit inside the destroy, as below. During an act change the exit is not deferred. An act change mid-dispatch is the exception (`_act_change_epoch`, bumped by `drop_act_pair_handlers`): a dead side then ends the contact and a handler the act took with it does not run (S4-1), the act's own hooks on game bodies included: an `on_collide*` the act set as a closure over itself, cleared by the change (`_drop_act_callables`), is re-checked against the side's current hook, at enter, stay and exit (`_run_exit` takes the act epoch its runs were chosen at; CD2). A hook that does not close over the act is the game's and runs on. An exit goes only to a pair whose enter ran: a body destroyed during this step's enter dispatch drops its not-yet-entered pairs silently, and a pair that separated this step gets its exit at the destroy, while the body still exists, not later from the step's exit loop (S8-3, X-life-2). The dying body is out of its groups before any exit runs, so a survivor's exit counting `group["enemy"]` sees it gone (S9-2). An exit runs the handlers its contact entered under: they are chosen before the first one runs (a handler that destroys or untags a side does not hide the rest, PB3), and a tag a side left while touching (`untag`, a group change) still matches that contact's exit, never a contact begun after (`_note_left_tag`; PB1). **A contact is per rule (CD3, 2026-10-16).** The step commits pairs, but which rules a touching pair is in is read at each commit: a rule that begins matching a pair that keeps touching — a side joined a tag, a pair handler was declared, an `on_collide` / `on_collide_stay` was set — enters at that step (among the step's enters, in the order the pair would have if it had just begun touching) and stays from the next; a rule that stops matching — a side left a tag — exits after the step's exits, and its stays stop. Before, enter / stay / exit were decided per pair of colliders, so whether `@collide("shield", "lava")` entered when the hero gained `shield` inside the lava depended on an unrelated rule: alone, the pair was new and entered; beside `@collide_stay("hero", "lava")` the contact already existed and the shield rule only got stays. The mirror lost the exit: a tag left while another rule kept the pair touching never ran `@collide_exit("shield", "lava")`, not even at the separation (an enter / exit counter stayed +1); and a tag joined and left between two steps (a blink) ran an exit that no enter came before when the pair then separated (CD3-b). Mechanism: `_note_flux` records, per collider that may be touching (`Collider._born` older than the last commit: a body spawned with two pair tags records nothing), each tag's membership at the last commit (the first change sets it) and, for a tag left, the partners whose contact had entered under it; `add_pair_handler` and the hook setters record the rules set (`_note_new_rule`, `_note_new_hook`; an exit handler set mid-contact is not a gain: it runs at that contact's end). The commit (`_commit_rules`) moves them to `_flux_now` / `_new_rules_now`; `_rule_changes` compares, for each touching pair of a changed collider, the rules matching now with those matching as of the last commit (`_pair_matches_as_of`), and fills `_gain_pending` (enter rules, dispatched with `only=`), `_stay_skip` (gained stay rules wait a step) and `_lost_pending` (exit runs). An exit at a destroy before a gained rule's enter ran reads the rules as of the commit before (no exit without its enter: S8-3 per rule) and runs the lost rules still owed. A tag or rule a handler adds during the step is left out of the rest of that step's contacts and counts at the next commit (`_rule_filter`; F3: what a command made waits); one a handler removes stops at once and exits at the next step. Untag and retag in one frame, or tag and untag, is no change. Guards: `test_collision.TestARuleAContactGainsOrLosesMidContact` (alone and beside a stay, an enter, an `on_collide` and an exit rule), equation E15 (a no-op rule beside every program's and example's rules changes no other call; canary: the per-pair rule). Cost: in the steady state one test at the commit and two per dispatched contact; `_exit_matches` lost its two `_left_tags_of` calls. Interleaved A/B against the tree before (collision step, CPU median): 300 touching pairs with enter / stay / exit rules −0.6 %, 60 bullets with two pair tags spawned and destroyed every frame −0.8 %, 150 pairs entering and leaving every other frame 0.0 % (12 rounds): within noise. An exit handler dropped meanwhile (the dispatch epoch moved, bumped when a collider leaves or a pair handler is removed) does not run. Park leaves collision after the actor reads parked: its exit handlers see `active` False, and their flag writes go to the stash (X-life-1). Per contact, `_dispatch` walks only this phase's handlers (`_phase_handlers`: a snapshot keyed by the dispatch epoch and the list length, cleared on every removal so it never holds a dropped side) and skips a handler with a tag side whose tag index holds neither collider (a necessary condition of `_collider_on_side`, so nothing that matched before is skipped, and order is kept). With 30 unrelated tag handlers, `_pair_matches` was 40 % of a step; the step is ~33 % faster (review 2026-10-09 perf).
6. **Resolution** — standing `resolve()` pairs: tag-indexed partners (identity list cached across frames; motion deltas live) → sweep to TOI (AABB-reject) → slide (up to 4 times) → bounded settle (current-proxy AABB cull) → floor snap (full partner list; O(1) skip when a bottom contact was already recorded). Movable bodies collected from declared resolve sides, not every enrolled collider. See [Resolution](#resolution) and [Resolve hot path](#resolve-hot-path).

Internals: [Sprite Design.md — Mass sprite hot path](Sprite%20Design.md#mass-sprite-hot-path).

## Contact payload

`CollisionInfo` is ephemeral: one overlapping pair, one frame. Handlers receive it as `info`.

| Member | Role |
| --- | --- |
| `a` / `b` | Identities of the pair (Shape, Sprite, …) — a hitbox part reports its host |
| `a_hitbox` / `b_hitbox` | The `Hitbox` part on that side, or `None` (the body) |
| `normal` | Unit separation from `a` toward `b` (zero if unavailable) |
| `depth` | Penetration along that normal; `0.0` for a resting skin contact ([Resting contact (skin)](#resting-contact-skin)) and for a swept contact ([Swept detection](#swept-detection-fast-bodies)) |
| `points` | Contact manifold — list of `(x, y)`; empty only on exit |
| `point` | **Derived:** centroid of `points`, or `None` if empty |

Prefer `info.point` for VFX (explosion, marker). When a face manifold carries two clip points, `.point` is the segment midpoint.

**Enter / stay** always publish a location while the pair overlaps: the clip centroid, or — if the clip list is empty — a **prim-support witness** (furthest point of each body along the contact normal; unique vertex when one side is a corner on a face). Same helper resolve uses for `TouchingContact.point`. That is a point on the skin, not a body-center midpoint. Do not invent a location from body centers when there is no contact.

**Exit** builds `points=[]` (and thus `point is None`). This does not stash last enter/stay geometry onto exit — last-touch VFX is author policy.

Canvas `*_at` accepts `info` / `info.point` (or `(x, y)`, Point, Vec2, Graphic). `None` is a no-op. Splat `*info.point` is legal on enter/stay; on exit it raises.

## Touching and tangency

**Contact means real overlap. Touching counts, but at exactly zero gap either answer is allowed.**

- Every narrow path uses closed tests: AABB rejects only a strict gap, SAT only a negative interval overlap, circles with `1e-9` slack. Bodies that share a face or a point are a contact with `depth ≈ 0`.
- At *exact* tangency (a corner on an edge, two faces flush, a circle kissing a slanted edge) float rounding decides. The answer is deterministic for the same coordinates, but a whole-number shift of the world changes the rounding, so the same pair can touch at one position and not at another. Example: a Rect corner exactly on a Polygon edge is 1 ulp out at `y` and 1 ulp in at `y + 1` (G2 in [Testing Design](Testing%20Design.md#g--geometry-properties-2026-09-28)).
- Why not fix it: a game never lands on an exact tangency (positions come from `vel × dt`), and standing `resolve()` rests bodies `_RESOLVE_SLOP` (~0.08 DU) apart, 10¹³ ulps. A translation-invariant narrow phase (local frame per pair, quarter-turn snapping, a scale-relative epsilon) costs code and SAT time for no visible gain.
- Tests: a property that compares contacts across positions treats pairs within `TANGENT_EPS` (1e-6) of zero gap as "either" (`test_sys_hyp_collision.TestTranslation`). An oracle that demands an exact-tangency answer is stricter than this contract.

Fence: do not add a local-frame narrow phase or a tangency epsilon to make zero gap translation-invariant. Reopen only with a case a player can see.

Leaving collision (park, `collidable = False`) clears `touching_sides` / `touching_contacts` (the step no longer writes them; a stale `"bottom"` floor-snapped a body that rejoined in mid-air: review 2026-10-09 S8-5). With no resolve pair left, the settle memory and the one-way pass state are cleared too (S8-6). A compound `Collider([a, b])` whose pieces all die fires its survivors' exits and drops its pair handlers: it is its own identity (S8-9). The step's group / object expansion cache is the step's: it is cleared at the end of the step and whenever a collider leaves, so a query in `update()` never tests a body parked meanwhile (S8-8).

What a player *does* see is contact flicker on resting bodies. `touching_sides` is steady at any frame pacing ([Floor snap / grounded flicker](#floor-snap--grounded-flicker)); `@collide` on a resolved pair is kept steady by the detection skin ([Resting contact (skin)](#resting-contact-skin)).

Author catalog: [Guia da API — Colisão](../docs/pt/guide/index.html#colisao). Resolution helpers on `CollisionInfo`: `mtv_split`, `velocity_split`, `push_apart`, `bounce_apart`, `resolve`, `reflect_velocity`; ramp reading: `side`, `slope_angle`, `tangent`, `slide_along`.

# Resolution

Detection (`@collide`, `on_collide`) and resolution (`resolve`) are **separate enrollments**, but **both declare detection pairs**. A collectable is `@collide` only — never named in `resolve()`. There is no `.solid` / `.is_sensor` flag. Hitbox parts are detection-only by construction: `resolve()` / `resolve_now()` refuse a `Hitbox` side (all-or-nothing, before any pair registers), and manual `info.resolve()` / `push_apart()` / `bounce_apart()` raise on a part contact. A **group** a part claims stays a legal resolve side — resolve moves its members' bodies ([Hitbox parts](#hitbox-parts)).

## Movability: `.mass` and `STATIC`

- **`Graphic.mass`** — default `1.0`. Mass-weighted push/impulse split. `mass <= 0` raises; use **`STATIC = float("inf")`** for immovable bodies (walls, floors).
- **`Graphic.vel`** — optional `Vec2`, unset until assigned. Required on at least one moving body for `bounce=`. Pose movers (`move_along`, timed `move_to` / `move_by`) never write it — the Handle reports rate. A missing `.vel` on the other side (including a finite-mass floor) is treated as rest, same as `STATIC`. If neither side has `.vel`, the velocity step is skipped. Not linkable: every `@=` spelling raises (the solver writes it); set it in `on_update`.
- **SpatialFx** — detection only; no `.mass` / `resolve_now`.

## Standing resolve: `resolve()` / `unresolve()`

```python
resolve(player, "walls")              # enroll + detect + position-only each overlapping frame
resolve(player, "walls", bounce=0.0)    # + velocity along normal
resolve(player, "thin", only="bottom")  # one-way: see One-way pairs: only=
unresolve(player, "walls")
```

Same target grammar as `@collide`: tag, shape, list/tuple OR, `ANYTHING`. Self-paired tags cover mutual push pools: `resolve("crates", "crates")`. No separate `collidable = True` required on either side.

**`ANYTHING` makes every enrolled body solid.** `resolve(hero, ANYTHING)` pushes against collectables, bullets and triggers too: anything enrolled by `@collide`, `collidable` or `on_collide` (hitbox parts are excluded), because there is no sensor flag to opt a body out (above: a collectable is never named in `resolve()`, and `ANYTHING` names it implicitly). The `@collide` handler still fires; the coin is shoved instead of passed through. Kept on purpose (2026-10-13): it is the right spelling for a world where every body is solid, it costs about what a tag pool costs (400 bodies: `resolve("p", "p")` 4.2 ms/step, `resolve("p", ANYTHING)` 4.7, `resolve(ANYTHING, ANYTHING)` 4.8), plus a partner-cache drop on every enroll / leave ([Resolve hot path](#resolve-hot-path)). Not refused, unlike `@leave_playfield(ANYTHING)` ([Canvas Design](Canvas%20Design.md)), where it would mean every actor. The Guia warns at [Parede e chão](../docs/pt/guide/index.html#res-basic): name the solid groups instead. Guard: `tests/test_collision.py` `TestResolveAnythingIsSolid`.

**Pair sides.** One rule for `@collide` / `@collide_stay` / `@collide_exit` / `resolve` / `unresolve` (`_check_pair_sides`, `collision.py`): a side is one atom or a list / tuple of atoms, and an atom is an actor (`Entity`), a group tag string, `group["tag"]`, `ANYTHING`, a `Collider`, or a `Hitbox` part. Anything else (`5`, `None`, `True`, a dict / set, a post effect, a function) raises `TypeError` at the call, naming the call, the type and the spelling to write (`resolve(player, "walls")`); the value is shown only for `None` / numbers (no object reprs). The check runs before anything is registered or removed, and before `only=` is read, so a bad side is always the first error. Before it, `resolve` / `unresolve` registered a junk atom silently: a pair nothing could ever match. Later, more specific refusals still apply on top (a hitbox part is a valid atom, but `resolve()` refuses it: parts only detect). An empty side keeps its own "must not be empty" message. A shape's Point part (`c.center`, `line.p2`) is an `Entity` but not a body: the same check refuses it first, naming the owner and `@collide(owner)` + `info.point` / `contains_point` / a follower `Point` ([Actors — A part is not an actor](Actors%20Design.md#a-part-is-not-an-actor)); `collidable = True` / `on_collide*` on a part and a registered `Collider([part])` refuse the same way, `ensure_collider` is the backstop, and queries (`test_collision`, `collides_with`) still take a part through an unregistered probe. Tests: `tests/test_pair_sides.py`, `tests/test_part_lifecycle.py`.

Each `step()` after enter/stay/exit dispatch, for each resolve-enrolled body in `_collider_index` order:

1. Rewind the frame's **motion-channel** translation (`move_by` / `_by` / `time=` ticks), not every pose-key jump. Instant `*_to` / `=` / `@=` / `tween(center)` are **placement** and do not produce a swept segment. Rotation, resize, and hitbox rebake are not sweepable — those overlaps go to settle, and a bounds change that crosses into a previously clear body separates across that face ([Unswept bounds](#unswept-bounds)). See [Motion vs placement](#motion-vs-placement).
2. Sweep against **tag-indexed** declared partners (not a scan of every enrolled collider) to the earliest time of impact, in the pair's **relative** frame (`d_self − d_other`), so a rising elevator generates a TOI against its rider. Closed-form for AABB/circle; **conservative advancement** (about 32 support rounds, then a thickness-capped bisect) for rotated, ellipse, and polygonal prims. If the body did not move but a partner did, one relative sweep still runs. If the body already overlaps at `t = 0`, there is nothing to sweep — that is settle.
3. Stop at the contact, back off by `_RESOLVE_SLOP` (~0.08 DU skin), respond to velocity there if `bounce=` is a number, and give the leftover motion the same answer: its part along the surface slides on, and its closing part comes back by the restitution the velocity got (none with `bounce=0`: the slide) — [Bounce sub-step](#bounce-sub-step). Repeat up to 4 slides. Every partner reached within the skin of one stop is answered at that stop, together ([Joint stop](#joint-stop-simultaneous-contacts)). A relative-frame TOI is against the partner's start-of-frame pose, so the body inherits the partner's leftover displacement (`d_other × (1 − t)`) to convert the contact back to world space — **every** contact side, not only a standing rider (see **Relative-frame sweep**). Against a movable (non-`STATIC`) partner the stop is then split by inverse mass: the partner is pushed by its share and the body follows ([Mass split](#mass-split-between-two-movable-bodies)). A body standing on a moving partner first moves with it, as motion ([Riders](#riders-a-body-standing-on-a-moving-partner)). After a floor contact, leftover motion is discarded only when this frame had no horizontal intent (`abs(dx) < 1e-3` on the body's own motion channel, before sliding, a rider's carry left out) — **stop-on-slope**, internal, no author knob. A walk keeps its slide. An idle body on a slope does not creep: a body that stops this way backs its skin off along its own motion (relative to the partner), by `slop / cos` of the angle between that motion and the normal, so it ends where its fall met the surface (`_skin_back_off`; within 60° of the normal, else along the normal). Backing off along the normal moved it `slop × sin(slope)` downhill every frame, and the next vertical fall kept it: 24 DU in 10 s on 30° at 60 Hz, 57.6 at 144 Hz (PE2 in [Testing Design](Testing%20Design.md)). A body that slides on backs off along the normal, which leaves its slide untouched. Run speed stays horizontal, not along the surface (`floor_constant_speed` off, no v1 knob). A partner with no `.vel` is infinite mass in that impulse, same as `STATIC`. A grounded body that meets the side face of a still partner whose top is at most `_SEAM_STEP` (2 DU) above its feet steps onto it instead of stopping — [Seam lips (step-up)](#seam-lips-step-up).
4. A **bounded settle** recovers overlaps the body's own motion did not cause (spawned inside a wall, a platform moved into it, a pair that was already overlapping). Correction is `clamp(0.5 × (depth − slop), 0, 8 DU)` per iteration, along the **persistent** contact normal (last TOI normal cached per pair, so a settling body does not oscillate between SAT axes). A pair with no remembered normal separates along the **minimum overlap** (the SAT axis, the side the overlap is on), never along a guess from `.vel` ([Settle direction](#settle-direction-and-static-under-a-stack)). Between two movable bodies the correction is split by inverse mass, but no share carries its body into a `STATIC` partner of its own: that share is cut at the wall and the other body takes the rest; a partner whose turn is still to come carries its share in its motion channel, so its own sweep travels it. Containment depth is the distance to the nearer face, so a sunk box can correct more per iteration than a partial overlap; the 8 DU cap stays. That capped path never writes `.vel`. Exact overlap tests run only for partners whose **current** proxy AABBs overlap; a body with no overlapping proxy skips settle. When the pair's last resolved **prim** bounds were clear, the current prims overlap, and this frame's box is not that box shifted by the motion channel, separate across the crossed face by the **prim-support** gap along the entry normal (not the fat prim AABB) — see [Unswept bounds](#unswept-bounds). See [Resolve hot path](#resolve-hot-path).
5. If the body was grounded at frame start and is not *leaving* the candidate floor, **floor snap** pulls it back onto a floor within `max(16 DU, |this frame's downward motion| + 8 DU)` so walking downhill, climbing a ramp, and short-frame resting contact against a rising platform do not hop. The snap is a straight drop, and its skin is taken back up the drop (vertically, `slop / |ny|`), not along the normal (PE2). Snap keeps the **full** partner list (a floor 16 DU below does not overlap the current proxy). If sweep/settle already recorded a `"bottom"` contact for this body, snap returns immediately (O(1) bottom refcount — see [Resolve hot path](#resolve-hot-path)). “Leaving” is bounce-aware along the contact normal — see **Floor snap / grounded flicker**.

Push direction and stopping distance both come from **this frame's motion**, not from end-of-frame minimum-overlap SAT. SAT itself is reused: at the moment of touching the overlap is ≈ 0, so the minimum-overlap axis *is* the true contact normal. Do not add SAT-axis heuristics, a `bounce=0` “platformer stop”, or approach-bias normal flips — those exist only to paper over deep-overlap SAT and were measured to trade one broken case for another.

A side impact at a ledge is a wall (for an airborne body at any height, for a grounded one above the seam step); a jump into a ramp end face is not a floor. Small-extent bodies no longer tunnel through thin slabs at realistic speeds (any speed against non-rotating geometry). Sweeping is the default for `resolve()` pairs; there is no `continuous=True` flag. Detection-only pairs sweep too, gated by speed, again with no flag ([Swept detection](#swept-detection-fast-bodies)). Resolve cost is zero for scenes with no `resolve()` pairs (Galaga-style `@collide` only). Mutual pools (`resolve("ball", "ball")`) stay cheap via the [Resolve hot path](#resolve-hot-path) — not by asking the author to drop the pair.

`side` stays `"top"` / `"bottom"` / `"left"` / `"right"`. Given Scena's fixed y-up world, floor ≡ bottom, ceiling ≡ top, wall ≡ left or right. An exact 45° normal (`abs(nx) == abs(ny)`) is top or bottom, so a 45° ramp is a floor. A per-body `up` (wall-walking, gravity flip) is deferred.

`touching_*` is published from the sweep/settle contacts, not from the pre-correction detection snapshot. `@collide` handlers still see that detection snapshot, plus the resting skin for resolve pairs ([Resting contact (skin)](#resting-contact-skin)) and a fast body's path ([Swept detection](#swept-detection-fast-bodies)). `@collide`-only scenes skip the per-Graphic `touching_*` walk until a previously published set must clear (e.g. `unresolve()`).

Debug outlines (`show_colliders`): gold = enrolled in a `resolve()` pair; cyan = hitbox part; green = other detection-only colliders (`_debug_color_for`).

Manual `info.resolve()` / `push_apart()` apply MTV via `move_by` (same `_ensure_writable` contract as other one-shot transforms). Standing `resolve()` nudges through `_nudge_collider` → `_move_by` after an **eager** enroll-time / link-time check: a linked `center` on either side raises `LinkedAttributeError` at `resolve(...)` (or when `@=` lands on an already-enrolled center), not on first overlap. `resolve()` checks every member of every side before registering any pair (all-or-nothing, like the hitbox-part side check), and the message names the group that pulled the member in; a late group join names the group being joined. The `ui` / parallax layer refusal and `bounce=` are checked for every member before the first pair too, in `resolve()` and in `@collide` with list sides, and a pair that still fails midway rolls the call back (`_restore_resolve_pairs`, `_drop_pair_entries`). Before 2026-10-09, `@collide([hero, hud_icon], wall)` raised `UiLayerError` with `hero × wall` already live (review S8-1). A **motion in flight is not a conflict**, in either order: timed `move_*` / `move_along` / `tween` started before `resolve()` compose with it exactly as when started after (push motion is swept; a part tween is placement). Pointer drag under standing `resolve()` is placement — not swept, and floor snap pulls a grounded held body back; see [Shapes Design.md — Persistent drivers](Shapes%20Design.md#persistent-drivers-vs-linked-pose) (pointer hold). See [Shapes Design.md — Persistent drivers vs linked pose](Shapes%20Design.md#persistent-drivers-vs-linked-pose). Escape: `unresolve()` / explicit `.unlink()` — there is no `force=` on the standing registration. A tag side is one side however it is spelled: `"walls"` and a live `group["walls"]` match each other in `unresolve` and in the act restore (`_resolve_target_equal` compares their tags; a fresh `GroupOperator` per lookup never matched by identity: review 2026-10-09 S9-7).

`collision.resolve_enabled` (bool, default `True`) is an advanced hatch next to `show_colliders`. When `False`, skip standing `_apply_auto_resolve` (sweep / settle / floor snap) but keep enroll, proxy, narrow phase, `@collide` / stay / exit, queries, and raycast. `touching_*` clears while off. On `True` again, the next `step()` settles residual overlaps. Not the taught reset path — use placement (`center =` / instant `move_to`) instead.

## Seam lips (step-up)

**A grounded body that walks into the side face of a still partner whose top is at most `_SEAM_STEP` (2 DU) above its feet steps onto that partner.** It neither stops (solid pair) nor passes into it (`only=` pair). SU in [Testing Design](Testing%20Design.md#su--seam-lips-2026-10-11).

Why: a walker rests `_RESOLVE_SLOP` (0.08 DU) above its floor. Two tiles placed a hair apart leave a lip at their seam: a rotated row (each tile turned about its own center), integer coordinates, a scaled sprite hull (one source pixel ≈ 0.6 DU at 80 / 128). Any lip above the slop puts the next tile's **side face** in front of the walker's leading corner, and the sweep's contact normal is then horizontal. Solid: the walker stopped dead at a 0.1 DU lip. One-way: `only=` rejected the side hit, a pass started, the walker rode the previous tile's corner and dropped into the tile (reported in `ninja_perigos`, a 15° platform with a 0.34 DU lip). The one-way threshold was frame-rate dependent: a 0.05 DU lip held at 60 Hz and dropped at 144 Hz.

| Condition | Rule |
| --- | --- |
| Grounded | `"bottom"` in last frame's `touching_sides` (`grounded_at_start`), or a bottom contact already recorded this frame (`_solve_bottom_count`) |
| The hit | A side normal (`abs(nx) > abs(ny)`: the `left` / `right` bucket) of a partner that did not move this frame (`odx == ody == 0`, `_seam_candidate`) |
| Height | Vertical: the face's top at most `_SEAM_STEP` above the feet. A seam offset `d` across a row turned by `a` is a rise of `d / cos(a)` |
| Probe | `_try_seam_step`, from the slide's start pose: **lift** along the face (its upward tangent, so a rotated tile's leaning face is not scraped) by `_SEAM_STEP + slop` vertically, a ceiling clips it; **forward** redo the slide's motion; **drop** must land, from above (`t > 0`), on the **same** partner with a `"bottom"` normal. Casts use partners with motion zeroed and a non-marking `_QueryOnlyGate` |
| Cheap refusal | Before the full casts, one cast from the full lift against the face's own partner only: the same face still blocking is a wall (two casts per frame became one, for a walker pressed into a wall) |
| Commit | `_take_seam_step`: the body moves to the landing pose; the **landing** bottom contact is recorded (never the side one, so `_contact_memory` does not learn a side normal and settle does not push sideways), and `bounce=` responds along the landing normal (`vel.x` is kept). The forward motion left after a hit continues the slide loop, so a real wall further on is still met |
| One-way | `_earliest_toi(deferred=)`: for a grounded body the sweep defers the marks of rejected hits. If the earliest is a seam candidate and the step lands on it, it is not marked; otherwise every deferred hit is marked exactly as before (the accepted-hit-precedes rule is unchanged) |

What it does not do: no ledge grab (an airborne body hitting a low slab end is a wall, `test_side_impact_at_ledge_height_is_never_floor`); no step onto a moving partner; no step onto a face too steep to stand on (a 60° rise at 240 Hz, where one frame's run is under the step, lands on a side normal: refused); no author knob (`_SEAM_STEP` is private; 0 turns it off, the bench A/B switch). A taller lip is unchanged: a wall (solid) or a walk-through (one-way semisolid). `floor_below` already agreed: its march lifts 9 DU per sub-step, so a lipped seam was floor there.

Why this is not the fenced SAT-axis guess (Standing resolve) or the S2 "was above" rule (one-way fences): the normal is never reinterpreted. The probe is a geometric question asked with the solver's own casts — is there floor on the same partner within 2 DU up, reachable along this frame's motion — and it runs only for a grounded body against a still side face. S2 for an arbitrary height would change diagonal falls; a 2 DU step for a standing walker does not.

Cost: nothing unless a grounded body's sweep meets a side face. Measured 2026-10-11 (`scripts/bench/perf_seam_step.py`, in-process interleaved, 11 rounds; 30 walkers, 100 tiles): flat row +0.2 %; every walker pressed into a wall every frame (the worst case) +1.5 % after the cheap refusal (+7.9 % before it). `resolve-2` probes against a clean HEAD copy, 7 interleaved runs: balls `coll_ms` −1.2 %, platformer −2.0 % (noise).

Tests: `tests/test_seam_step.py` — flat lips 0.1–1.9 × solid / `only="bottom"` / `only=` function × 30 / 60 / 144 / 240 Hz and 5 / 28 ms; the `ninja_perigos` hulls uphill and back; random rows at ±15° / ±30°; the refusals above; `_SEAM_STEP = 0` restores the snag (the tests catch the bug class).

Fences:

- Do not measure the lip from the partner's AABB top or a support point: a rotated tile's AABB top is its high corner (20 DU above the seam on a 15° row of 80 DU tiles). The casts are the measure.
- Do not lift straight up: a 15° tile's side face leans 15°, and a vertical lift from a pose touching it scrapes it after 0.3 DU.
- Do not land on any partner: the drop must reach the face's own partner from above, or a wall pressed while standing would "step" back onto the floor and lose its side contact.
- Do not expose `_SEAM_STEP` as an author knob or per-body attribute without a taught game that needs another height. Revisit: a game with stairs as level geometry (a real step-up height is a character-controller feature, not a seam fix).

## Motion vs placement

Two orthogonal axes on pose writes. Naming carries **abs vs rel** (`_to` / `=` vs `_by`). **Placement vs motion** is instant set vs travel (`time=` on the pose verbs, or a per-frame `move_by`).

> Instant `*_to` and `=` **set** the pose (placement).  
> `*_by` and pose verbs with `time=` **travel** (motion).

| Spelling | Collision |
|---|---|
| `.center=` / `.center.x=` / `.center.y=` / `.angle=` / `.scale=` | Placement: re-baseline; settle only. Graphics have no `.x` / `.y` |
| Instant `move_to` / `rotate_to` / `scale_to` | Same |
| `move_by` / `rotate_by` / `scale_by` (± `time=`) | Motion. Translation is swept (by `resolve()`, and by detection when the body is fast — [Swept detection](#swept-detection-fast-bodies)). A turn about another pivot (`about=`, an orbit) moves the pose anchor: that chord is translation, swept the same way ([Orbit chord](#orbit-chord)). The turn itself (spin) and scale stay settle-only until those axes are sweepable |
| `move_to(..., time=)` / `rotate_to(..., time=)` / `scale_to(..., time=)` | Motion. `timed_move_to` ticks **`move_by` deltas** (not absolute `_move_to` each frame) |
| `tween(shape.center, …)` / `center @=` | Placement every write — walls do not sweep-stop a linked or tweened center |
| `move_along` | Motion (`move_by` deltas) |

**Motion channel:** apply a delta and mark the collider (`note_collider_motion` → `_pending_motion_*`). `_update_proxy` copies that into `_motion_dx` / `_motion_dy` for `_sweep_and_slide` and leftover inheritance. Solver nudges use `_move_by` so they do not mark next-frame motion.

**Placement channel:** apply the absolute pose; pending motion is zero (or cleared by instant `move_to`). The proxy re-baselines — start-of-frame AABB is **not** unioned with the new pose — so a teleport across a slab is not a swept segment. A teleported `STATIC` platform reports **zero** leftover that frame (finite-mass and `STATIC` alike). A placement that ends clear is left where it landed. A placement that ends overlapping a previously clear partner is an unswept bounds change ([Unswept bounds](#unswept-bounds)), not a swept stop. Spawn with no resolved history, and a pair that was already overlapping, stay on bounded settle.

**A group's member on `ui` or a parallax layer has no body.** A tag, a live `group[...]` or a snapshot of groups reaches only members that can collide: one on a refused layer is skipped silently, whether the rule or the tag came first, in `@collide`, `resolve`, a later `tag()` and construction (`_try_enroll_item`, `_colliders_for_shapes`). Naming such an actor itself (`@collide(hud_icon, x)`, `resolve(cloud, …)`) still raises `UiLayerError` / `ParallaxLayerError` (`_assert_named_sides_not_parallax`). Before 2026-10-09 the outcome depended on statement order: the rule raised for a member already tagged, and a later tag was swallowed (review S9-1, decided).

**Every author placement clears the pending motion**, as instant `move_to` always did: `shape.center =` (the route hook in `Entity.__setattr__`), `center.x =` / `.y =` on an actor's point (`Point.__setattr__`) and `center << p` (`Container.__lshift__`, through `state._PLACEMENT_HOOK`) call `entity._placement_write`, which runs `note_collider_placement` when the body has motion pending. After a `move_by`, a respawn by `center =` was swept along a segment ending at the spawn point: a ghost `@collide` and a resolve stop at a wall it never crossed (review 2026-10-09 X-writers-4; S7-4 was the same hole in `confine`). Engine recomputes write the point's slot directly, not through `=` (Line's derived center). Cost: one slot read and a compare per author point write when nothing is pending.

**A handler's write reaches this step's resolve.** `@collide` handlers run before `_apply_auto_resolve`, which trusts the proxies built before dispatch (`_trust_proxy_world`). When author code ran in the dispatch (`_author_ran`), the movable resolve bodies refresh their proxies first, so a respawn in a hazard handler lands on the spawn point instead of being pushed by the old pose's wall contact, and a body grown in a handler settles with its new size (review 2026-10-09 W-G1). A `STATIC` partner moved by a handler follows on the next step.

Taught reset / respawn: `center = spawn` or instant `move_to`. Do not suspend `resolve_enabled` for that. Do not treat `@=` as motion. Keep `move_to(..., time=)` on the taught surface; its ticks go through the motion channel.

Author catalog: [Guia da API — Mover](../docs/pt/guide/index.html#mover) and [Colisão](../docs/pt/guide/index.html#colisao). Tracks: [Tracks Design.md](Tracks%20Design.md).

### Orbit chord

`rotate_by(..., about=p)` with `p` off the pose anchor (`_collision_pose_xy`) carries the anchor along an arc. The **outermost** `rotate_by` measures the anchor before and after and notes the difference with `note_collider_motion`, so an orbiting body is swept along the chord between its two poses, like a `move_by`. Timed `rotate_by` / `rotate_to(..., time=)` tick through `rotate_by`, so their orbit is motion too. Hitbox parts get the host's chord (their anchor is the host's `center`).

| Rule | Detail |
| --- | --- |
| Where | `entity._rotate_as_motion`: the instant path of the `_install_timed_pose` wrapper (every Shape subclass override) and the shared `Shape.rotate_by` (Sprite, Text). Only when `about` is given and the shape is enrolled; `about=None`, the per-frame spin path, pays one `None` check |
| Once | A depth counter: an override that calls `super().rotate_by` (Track, Text) notes once, from the outermost call |
| Placement turns | Instant `rotate_to(..., about=)`, and the face snap (`_face_to_heading`, settle-only) run under `entity._rotate_as_placement`: the `rotate_by` they call notes nothing. `angle =` has no pivot, so it never orbits |
| Error | Chord vs arc: the sagitta `r·(1 − cos(Δθ/2))`, under 1 % of `r` below 16° per call. A larger turn (a fast orbit, or a hitch that multiplies the angle per frame) is swept as an arc: `_note_orbit_path` records waypoints every ≤ 16° (`note_collider_path` → `_pending_path`), the swept box covers them, the fast gate reads the path's length (a full turn ends where it began), and `_toi_along_paths` tests each sub-chord in order, earliest hit first (review 2026-10-09 W-T5, decided). Detection only: `resolve()` keeps the end chord. The swept prims keep the end orientation (spin is not swept) |
| Noise | A turn about the anchor itself moves it by float noise; below `_ORBIT_EPS2` (1e-6 DU) nothing is noted, so a spinning `resolve()` platform is not turned into a moving one |

Any new pose verb that turns about a pivot must route through `_rotate_as_motion` (motion) or `_rotate_as_placement` (placement); a direct write to the angle and `center` notes nothing and is placement. A new internal caller of `rotate_by(about=)` that is a snap, not travel, wraps it in `_rotate_as_placement`. Guard: `TestOrbitMotion` (every kind notes its anchor chord once; placement turns and spin note nothing; timed orbits; hitbox parts; a resolve shelf).

### Snapshot cache anchor (translate fast path)

World prims are cached per collider under a pose key `(epoch, x, y, *extra)`; when
only `(x, y)` changes the cached prims are **translated** instead of rebuilt
(`_world_prims`, `snapshot_shape`). So `(x, y)` must be the point the prims are
rigidly attached to. For Shapes that is the geometric centre. For a **Sprite** it is
`center` (the pivot; `Sprite._collision_pose_anchor`) — **not** `Graphic._center_xy()`,
which is the drawn box centre and moves when a cell of another size or pivot plays
while the baked body does not. Keying on the drawn box slid a resting walker's body
by the visual shift on every clip change (floating while sliding, sinking when
dead). Any new actor kind whose collider is not centred on its drawn box needs its
own `_collision_pose_anchor`; anything that changes the prims without moving that
anchor must change `extra` or bump `_collision_epoch`. Tests:
`tests/test_sheet_scale_anchor.py` (`TestRestingBodyAcrossClips`).

## Unswept bounds

Sweep rewinds the **new** prims by this frame's motion channel only. A resize, an offset, a hitbox rebake, or a `center` write does not enter `_motion_dx` / `_motion_dy`, so the sweep never sees the face that box crossed. At the apex under a thin slab, gravity (or `bounce=0` on an earlier hit) has already turned `.vel` downward while the box grew upward. Capped settle exits along the minimum overlap, which for a box grown past a thin slab's middle is the **far** side, and can spend its 32 DU budget there (before 2026-10-14 it oriented the exit by that turned velocity, with the same result).

Before that loop, when all of the following hold, the pair separates on the **entry face** instead:

- Both sides have a resolved box from the end of the previous step, those boxes were clear of each other, and the current boxes overlap. The box is the collision-prim AABB (`_exact_bounds_aabb`), stored at the end of the step. It is not the broad-phase proxy. Only `resolve()` bodies and partners store it (`_in_resolve`); every other collider keeps `None` and no world prims, so a collider that joins resolve has no history for one frame, the same as spawn.
- The collision prims themselves overlap. A prim AABB is still only a bounding box. A rotated rect, ellipse, or polygon leaves the corners of that box empty, and empty space is not a crossed face.
- The body's current box is not the previous box shifted by `_motion_dx` / `_motion_dy` (tolerance 0.75 DU — skin and float noise, not a real resize).
- The sweep did not already record this pair.

The sprite proxy is its turned extent box, and a loose bound wherever rotation would otherwise rebuild it. That looseness is for the broad phase only. Do not tighten the proxy so this recovery can keep using it — [Fences](Fences.md), and **Sprite colliders** / Proxy.

A sweep stop against one partner makes the motion-channel test fail for every other partner that frame. Recovery still runs the checks above against those others, and it records a contact only when their prims overlap. A contact with a shape the prims miss, answered with `bounce=0`, cancels velocity along that normal every frame. The body then sticks — pose and speed — until the sweep stop goes away (the push into the real wall is released). The false normal is whatever face the fat box crossed, so the same stick is a floor under a side slide, a ceiling over one, or a wall beside a vertical slide. Do not special-case the side, the held key, or the example game.

The face is the latest side the bounds crossed, both boxes interpolated, with the other axis overlapping at that time. Overlap at entry is ≈ 0, so the normal is that face and points from the body toward the partner. The body moves back across it by the full support gap of the **current** prim bounds, plus `_RESOLVE_SLOP`. There is no 8 DU cap on this pull. Finite masses split the gap the same way settle does. The normal is written into contact memory **before** the velocity response, so a later settle pass cannot turn a ceiling into a floor. `.vel` still changes only when it is approaching along that normal.

This is not a locomotion solid for `hitbox_source="each"`. It does not smooth `"bottom"` flicker, and it does not CCD a cell morph. Walkers stay `hitbox_shape="rect"` + `hitbox_source="all"`. Spawn (no resolved history), a pair whose previous bounds already overlapped, a partner placed into a body whose own box only translated, and a hit the sweep already stopped stay on the capped path.

Regression: `TestSweepAndSlideGates.test_sweep_correction_does_not_invent_a_contact_the_prims_miss` — a fat sprite proxy (circle hitbox turned 45°) and rotated bounds, all four sides; each case asserts its fat box actually overlapped during the run. A real crossing stays `test_unswept_growth_into_ceiling_stays_on_entry_side` and `test_unswept_ellipse_shift_into_ceiling_stays_on_entry_side`.

## Relative-frame sweep

The first slide of `_sweep_and_slide` finds TOI in the partner's **relative** frame (`d_self − d_other`), against the partner's **start-of-frame** pose. Later slides (`relative=False`) sweep leftover motion against the partner's **end-of-frame** pose. A STATIC body still has `_motion_dx/_motion_dy` from `move_by` — infinite mass does not mean zero motion this frame.

That relative TOI is not yet a world-space placement. After stopping at time `t`, the body must inherit the partner's leftover displacement `d_other × (1 − t)` so it sits on the contact **where the partner ends the frame**, not where the partner began it. This is a coordinate conversion. It is also all the carry a standing rider got before 2026-10-14, and `t` is the share of the rider's gravity step spent closing its skin: a sideways lift carried its rider 97 % at 30 fps, 87 % at 60, 1 % at 240. Riders now move with their partner before the sweep ([Riders](#riders-a-body-standing-on-a-moving-partner)); for them the conversion is not applied.

Two operations share the same loop and must **not** share a gate:

| Operation | What it is | When |
| --- | --- | --- |
| Leftover inheritance `ox += odx×(1−t)` | Relative-frame → world-space conversion | Any contact against a moving partner |
| Stop-on-slope | Discard a tiny horizontal remainder so gravity does not creep downhill | `side == "bottom"` only |

`side` classifies the contact normal (`"top"` / `"bottom"` / `"left"` / `"right"`). It is not a permission bit for solver mechanics that come from how the sweep is framed. Gating leftover inheritance to `"bottom"` was the standing-rider special case from the redesign draft; it is the wrong axis. A head-bonk (`"top"`), a wall shove (`"left"`/`"right"`), and a floor ride need the same conversion whenever the partner translated this frame.

`bounce=` is a separate step: it writes `.vel` along the normal. Position conversion does not write `.vel`. A body can have a correct (even diverging) velocity and a glued pose.

### Mass split between two movable bodies

Bodies sweep one at a time in `_collider_index` order. Without a split, the body swept first stops at the contact and absorbs the whole approach, whatever the masses: an earlier wall of mass 50 was carried by a mass-1 ball's whole step, an earlier crate was pushed at full player speed (and a later one never), an earlier mass-1 floor sank under its rider (a later one held). Settle and `velocity_split` already weighed both masses; only this conversion did not. A **position-dependent** force on such a body gained energy every hit: a spring-held wall moved by `move_by` read its stretch from the pose, so each shove stretched it for free (+45 % energy in 10 s; first seen in a springy-walls draft of `examples/entropia.py`, MS1).

The rule (`_share_sweep_stop`, from both `_sweep_and_slide` and `_sweep_idle_against_partner`):

| Step | What |
| --- | --- |
| Gap | After a stop at `t`, the pair would still close by `g = (relative motion · n) × (1 − t)` along the unit normal (body → partner): relative motion on the first slide, the body's own on later slides (the partner's end pose), minus the partner's motion on the idle sweep |
| Share | A non-`STATIC` partner takes `(g + _RESOLVE_SLOP) × inv_b / (inv_a + inv_b)`; the skin is split too, or the outcome still depends on who backs off. A `STATIC` partner takes nothing (one mass lookup). With a bounce the share is of `(1 + e) × g` and the body's own leftover comes back by `e × g` ([Bounce sub-step](#bounce-sub-step)): equal masses at `bounce=1`, the mover stops and the struck body takes the whole leftover |
| Push | The partner moves by its share, and the body follows by the same vector, so the contact holds. A partner whose turn is still to come (`_swept_ids`) also gets the push in its motion channel (`_snap_hot` resets it next step): its own sweep travels it and relative sweeps against it see where it started |
| Clamp | The push is swept against the partner's **STATIC** partners first (`_push_reach`, `only=` read through a `_QueryOnlyGate`), and both bodies get only what it reaches: a light ball shoved toward a 2 DU wall stops at it, and so does its pusher. The pass collects its STATIC bodies while it reads masses, so a push meets the partner list only when a wall is near |
| Body's walls | The body's own unswept travel (the inherited leftover, the skin, the follow) is swept against **its** STATIC partners too (`_travel_to_walls`: up to a wall, then along it, at most three walls), and the partner comes back along the normal by what the body could not travel, so the contact holds (PE4). This runs for an inheritance alone as well (no closing gap). A light ball under a falling heavy one stops on the floor; a light body swept before its fast pusher stops at the thin wall behind it, and so does the pusher |

Outcome: the crate, floor and spring cases above are equal in both enrollment orders, to the float; an equal-mass crate is pushed at half the player's step; a floor at the default mass 1 yields under an equal mass (the Guia says floors, walls and platforms are `STATIC`; "Tornar sólido" gotcha). Velocity is unchanged (`_respond_velocity`).

Limits, kept on purpose:

- A movable body in the pushed partner's way is not swept here: the partner's own sweep meets it (when its turn is later), or settle does. A row of crates pushes along in index order; otherwise there can be one frame of overlap.
- The tangential part of the inherited leftover is not split: a body still rides a partner's sideways motion during a contact, by `1 - t` of it on that frame (`examples/entropia.py` pins its piston's height for that reason). A body **standing** on the partner is carried whole instead ([Riders](#riders-a-body-standing-on-a-moving-partner)); for side and head contacts this partial, frame-rate dependent ride is the rule.
- Closed 2026-10-14 (PE4): the inheritance was placed, not travelled, so when the **lighter** body was swept first a fast partner could put it past a thin wall behind it (116 DU past a 2 DU wall at 6000 DU/s), and a light ball resting on a 10 DU floor went through it under a falling mass-30 ball. Row "Body's walls" above.

Cost (`_SWEEP_MASS_SPLIT = False` is the old rule, A/B): nothing new unless a sweep stops against a partner. Measured 2026-10-13, interleaved against a clean HEAD copy: `perf_resolve_balls` n=40 −0.9 %, n=80 −6.7 % (noise), `perf_resolve_platformer` +0.5 % (11 rounds). Worst case, a gravity pile of 150 balls where almost every contact is between two movable bodies: about +6 % (86 → 91 ms/step), the partner pushes themselves (~350 nudges a step) and the walls-near test; it was +11 % before the walls-first prefilter in `_push_reach`.

Tests: `tests/test_collision.py` `TestSweepMassSplit` — spring-held wall energy, crate push and a mass-1 floor, each in both orders; a STATIC partner takes nothing; a push into a thin wall stops at it (fails without `_push_reach`); a canary that turns the split off and sees the energy gain. `tests/test_resolve_solver.py` `TestStaticHolds`: the body's walls (PE4), with the `_SWEEP_INHERIT_CLAMP` canary.

### Riders: a body standing on a moving partner

**A body that ended the last step on top of a resolve partner (a `"bottom"` contact) and is not leaving it moves with that partner's displacement this frame, at every frame rate; its own motion adds** (PB2, decided 2026-10-14). Before, the only carry was the relative sweep's leftover `d_other × (1 − t)` ([Relative-frame sweep](#relative-frame-sweep)): 97 % of a sideways lift at 30 fps, 87 % at 60, 1–24 % at 144, ~1 % at 240. Vertical lifts carried through the relative sweep and floor snap, so only the part along the surface was missing.

| Rule | Detail |
| --- | --- |
| When | Before the sweeps (`_carry_riders`, from `_apply_auto_resolve`), for each movable body grounded at frame start. The carrier is the first `"bottom"` entry of last step's `touching_contacts` whose partner moves and is still a resolve partner |
| As motion | The carry joins the rider's pose **and** its motion channel (`_snap_hot` resets it next step). Its own sweep then travels it: a wall on the lift's path stops the rider, and a relative sweep against the rider sees where it started. Order-free: every carry is computed from the motion channels before any is applied |
| What a carrier passes on | `STATIC`: its whole displacement (it is never blocked). A movable body with no `.vel` (a platform moved by `move_by`, `time=` or `move_along`): the part of its motion along the contact surface; the sweep, settle and snap already handle the part along the normal, and a blocked push or gravity step there is not travel. A movable body **with** `.vel` (a physics body): only the carry it rides on itself, along the surface (a crate on a hero on a lift). Its own velocity is not a platform's motion: a crate on a pushed crate, or a ball falling with another, is not dragged (frictionless contact, as before) |
| Not carried | A body leaving the partner, by the floor snap's leave gate along last step's normal ([Leave gate](#leave-gate-current-rule)): a jump, an elastic bounce off a moving paddle. Once airborne there is no contact and no carry |
| In the sweep | A rider's first-slide stop against its carrier slides on by its motion **relative** to the carrier (a walk on the lift), and the carrier's leftover is travelled on the next slides instead of placed. A stop on a floor ends the rider's own motion (stop-on-slope reads its own `dx`, the carry left out), not the carry. A stop against a partner that rides the same carry (stacked or side-by-side riders) slides on by the own motion: that partner's inherited leftover already holds the carry |
| Frame rate | 30, 60, 144 and 240 Hz carry the whole displacement (to 1e-6 DU over 0.6 s in the tests), for `move_by` per frame, eased yoyo `move_by(time=)` and `move_along` |

Why `.vel` decides what a movable carrier passes on: a carrier's motion channel is its intent, not its travel. A resting crate's intent includes its gravity step, which the floor blocks, and a body that integrates `.vel` already shares its partner's normal velocity after a `bounce=0` contact. Carrying that intent dropped the upper crate of a stack twice per frame and dragged balls in a pile along their neighbours' falls. A body with no `.vel` is moved by pose movers only, so its motion is a platform's motion. This is not the mass split's `.vel` fence ("positions split by `.mass` alone"): the split decides who yields, the carry what a support's motion is.

Not done: a side or head contact against a moving partner keeps the partial `1 − t` ride listed in the mass split limits (a walker pressed into a rising lift's side is lifted by part of its motion, more at a fast walk). Sliding on by the motion relative to the partner at every contact removes it, but changes how walkers meet moving lifts' sides (the `test_resolve_vector` platformer fixture lost ~6 % of its contact frames); left for a decision.

Tests: `tests/test_resolve_solver.py` `TestRiderCarry` (STATIC and mass-50 lifts at 30 / 60 / 144 / 240 Hz, walking on the lift, jumping off, a wall on the lift's path, two stacked riders in both orders, a crate on a pushed crate, a ball bouncing off a moving paddle, the `_RIDER_CARRY = False` canary) and `TestRiderCarryTimedMovers` (eased yoyo `move_by(time=)`, `move_along`).

### Settle direction and STATIC under a stack

**Settle separates an overlap along the overlap.** With no remembered contact normal for the pair, `_settle_normal` returns the minimum-overlap (SAT) axis. It used to flip that axis whenever the pair's velocities separated along it, a guess that the body had entered from the far side. Every case that reached it was the opposite: two balls spawned overlapping and moving apart were pushed through each other (sides swapped in 6 frames; stuck forever without `bounce=`), a ball spawned 5 DU inside a 4 DU wall and moving into the room escaped outside, a STATIC paddle placed onto a ball lost it below, a three-ball wedge resolved by creation order (PE1). A crossed face is not settle's to guess: a body's own resize is [Unswept bounds](#unswept-bounds), its motion is the sweep. A body placed past a floor's middle now leaves by the near (bottom) face, whatever its `.vel`; the old `test_resolve_lifts_body_sunk_past_floor_midpoint` pinned the guess and was turned around.

**STATIC never gives way under a stack** (PE3). Settle split a correction between two movable bodies by mass without looking at their STATIC partners, so a light crate under a heavy one was pressed into the floor (mass 5: 8 DU in; mass 20: almost fully in; a 10 DU floor in a bin of 100 balls: five fell through). `_nudge_pair_along` (settle and unswept recovery) now casts each share against its body's STATIC partners (`_push_reach`), cuts a share at its wall and gives the rest to the other body, up to that one's wall. A partner whose turn is still to come gets its share in its motion channel instead (`_push_partner`), as a sweep push does: placed, the share moved the start of its own sweep, so the sweep began inside the floor. Stacks of movable crates may still overlap each other a few DU and jitter (no stacking guarantee); nothing ends inside or below a STATIC body. A body squeezed between two walls keeps the overlap (neither share can move).

Tests: `tests/test_resolve_solver.py` `TestSettleIgnoresVelocity` (the pair moving apart, the ball in a wall, the placed paddle, and the class guard: random overlapping pairs settle to the same poses with random velocities as with none; `_SETTLE_MIN_OVERLAP = False` canary) and `TestStaticHolds` (crate stacks at masses 1–100 on 2 / 16 / 40 DU floors in both orders, a 40-ball bin on a 10 DU floor, PE4 above; `_SETTLE_STATIC_CLAMP = False` canary).

Cost (2026-10-14, collision step against a clean HEAD copy, separate processes interleaved, best of 7–9 rounds): 40 bouncing balls +1.4 %, 80 balls +0.8 %, 30 walkers on a tile row with lifts +0.6 %, `perf_seam_step` flat and walls within 0.3 %; `game_bench` (5 rounds) mundo resolve −5 % and work −0.3 %, ninja_perigos work +0.4 %. Two scenes pay for new work: 30 riders on 10 sideways lifts +10 % (they are carried now: the carry pass and the carry's extra slides), and the 150-ball gravity pile, the mass split's worst case, +9 % after caching each body's partner set for `_push_reach` (+11 % before): two casts per settle correction between movable bodies, one per stop for the body's walls, and a pile that no longer sinks (19 % more broad pairs). `_SETTLE_MIN_OVERLAP`, `_RIDER_CARRY`, `_SKIN_ALONG_MOTION`, `_SETTLE_STATIC_CLAMP`, `_SWEEP_INHERIT_CLAMP` turn each rule off (A/B, canaries).

### Joint stop (simultaneous contacts)

**The partners a sweep reaches within the contact skin of its earliest hit are answered at that stop together: the velocity, the leftover and the contacts.** (LW2, 2026-10-15.) Before, the earliest hit answered alone (a tie went to partner order) and the next slide met an already turned velocity: a ball straight up into the seam of two bricks left 7–60° off vertical by creation order (gap 1–8 DU), and the E8 twin's ball differed by up to 46° between breaking the bricks in the handler and a frame later.

| Rule | Detail |
| --- | --- |
| Ties | `_earliest_toi(ties=)` keeps every accepted hit with `(t − t_best) × |motion| ≤ _CONTACT_SKIN`: the partners `@collide` would call touching at the stop. A hit whose normal is parallel to the earliest is dropped there (a flat seam answers alike), so a walker on a flat tile row takes the one-contact path |
| Mutual blocking | `_joint_stop`: a tie joins only when the slide along each contact runs into the other within the skin (a probe cast from the backed-off stop, its length scaled by the approach rate), both ways: what the next slide of a one-at-a-time answer would meet, asked in both orders so a tie's "earliest" does not matter. A tile seam's side face that a walker's floor slide passes 0.08 DU above stays out (the internal edge: the joint stopped walkers dead at seams at 5 / 28 ms); a ball's slide along one seam corner meets the other |
| Velocity | `_cone_response`: `p` is the projection of the velocity onto `{u : u · nᵢ ≤ 0}` (`_cone_split`: a face or the apex in 2D), `v − p = Σ jᵢ nᵢ` with `jᵢ ≥ 0`, and `v' = v − Σ (1 + eᵢ) jᵢ nᵢ`. One contact: `velocity_split` against a still partner. Order-free; `p ⟂ (v − p)`, so a uniform `bounce=` adds no energy (P2), and mixed restitutions that would (obtuse normals) take the smallest. A seam's two corners send a ball straight back; a room corner reflects each component; a fall onto a floor-and-ramp joint stops |
| Leftover | The same answer on the frame's leftover, each contact's `e` only if the velocity approached it ([Bounce sub-step](#bounce-sub-step)); stop-on-slope drops the slide and keeps the bounce |
| Skin | Backed off along the summed normal by `slop / min cos` (at most 3 slop), so every contact keeps its slop; an idle stop backs off along its own motion, as one contact does (PE2) |
| Who | Still, immovable partners only: `STATIC`, or a removed partner with no `.vel`. A moving partner, a movable one (the mass split takes a share), a rider meeting its carrier, a contact more than 78° from the summed normal (an obtuse wedge) or more than `_JOINT_MAX` (4) contacts: the earliest answers alone, as before |

Not done: ties with **movable** partners answer one at a time (a cue ball sent exactly into the gap between two resting balls still leaves by creation order); the mass-weighted projection is the same 2 × 2 algebra, but the follow of two pushes is new design, and no game shows it. A ball off a seam's centre by more than the skin allows (about 0.3 DU on a 4 DU gap) meets one corner first and leaves at that corner's angle: that is the geometry, not a tie. Smoothing it (Box2D's ghost vertices) would reinterpret normals, which [What not to add](#what-not-to-add) fences.

Tests: `tests/test_joint_response.py` (`TestJointAlgebra`: one contact is `velocity_split`, random sets add no energy, ignore order and leave no contact approached; `TestSeams`: gaps 0–12 × 30 / 60 / 144 Hz × plain / handler / later × both orders, phases, off-centre agreement, the E8 twin; `TestInternalEdges`; canary `_JOINT_RESPONSE = False`), `tests/test_laws_equations.py` (`test_two_bricks_at_once_agree`).

### Bounce sub-step

**After a stop, the closing part of the frame's leftover gets the restitution the velocity got: the rest of the frame's travel continues along the reflected motion.** (LW7, 2026-10-15.) Before, only the part along the surface slid on, so a head-on bounce lost `(1 − t) × d` every time, by frame rate: a ball between two walls at 700 DU/s lost 5.2 DU a bounce at 30 and 60 Hz, 1.4 at 144, 2.3 at 240 (a ball in a box ran 3–6 % slow); a `bounce=1` ball dropped from 200 came back to 190 at 30 Hz, 195 at 60, 198 at 144; two balls hit head on ended up to 4.4 DU off their paths.

| Rule | Detail |
| --- | --- |
| Gap | `g = (relative motion · n) × (1 − t)`, the closing part of the leftover (relative to the partner on the first slide) |
| Restitution | `_substep_restitution`: the pair's `bounce=` when the velocity response really answered (the body has `.vel` and its velocity approached the partner), else 0. `bounce=0`, a position-only pair, or a body moved by `move_by` with no approaching `.vel`: the slide, exactly as before |
| Leftover | `remaining = slide − e × g × n`: swept on the next slide like any slide (no tunnelling), within the 4-slide budget; what a fifth stop would need is dropped, as before, and the velocity is still right |
| Movable partner | The mass split shares `(1 + e) × g` and the body follows, then its own `− e × g`: momentum and the ideal paths (head-on balls 0.04–0.06 DU off, the skin) |
| Rest | No sub-step on a floor (`"bottom"`) contact for a body that started the frame grounded: one frame's gravity kick (`g × dt`) reflected as travel kept a bouncy ball hopping 2.7 DU forever at 30 Hz. A landing starts airborne and keeps it. `bounce` 0.2 / 0.5 rest at the slop at every rate; 0.8 rests by 12 s (its ideal settle time is 6 s; the author's Euler step adds hops); 0.9 still hops at 12 s, as it should (12.7 s) |

Outcome: the two-wall lag is 0.08 DU a bounce (the skin) at 30 / 60 / 144 / 240 Hz and 5 / 28 ms; the dropped ball peaks at 200.0–200.1 at every rate; E1 holds on a ball in a STATIC box and on two walls at 700 DU/s, which it failed before. Not done: a partner moving into an idle body (`_sweep_idle_against_partner`) has no sub-step: a paddle that hits a resting ball loses `(1 − t)` of the ball's first frame (small, and it needs a `.vel` on the paddle).

Cost of the four rules together (2026-10-15, M4 at load 2–4; base = the tree before them): separate processes interleaved, minimum of 7 rounds, a headless resolve step: 40 / 80 bouncing balls +1.0 / +1.5 %, 30 walkers on 100 tiles +1.5 %, 8 balls breaking 72 bricks −0.5 %, a 150-ball gravity pile −0.7 %; `game_bench` (3 rounds) mundo work +0.8 % (median −0.1 %), ninja_perigos −0.2 %. In-process interleaved A/B per flag (blocks of 50 steps, minimum): walkers +0.1 % or less for each, 80 balls −0.1 to −0.9 %. What it pays for: a lone hit costs no tie bookkeeping (the tie list starts at a second accepted hit), a removed partner is walked after the partner pool (the pool loop is unchanged), the skin answer's list is built only when some pair bounces. Mundo meets about one joint stop a frame (a walker in a floor-and-wall corner): 25 ms of 2030 ms of resolve over 586 steps.

Tests: `tests/test_joint_response.py` `TestBounceSubstep` (two walls at every rate, the elastic drop, rest at 0.2 / 0.5, head-on balls at three mass ratios, `bounce=0` path identical with the sub-step off, canary `_BOUNCE_SUBSTEP = False`), `tests/test_laws_equations.py` (`test_two_wall_twin`, canary `test_e1_catches_the_dropped_leftover`).

### Already-overlapping TOI

Closed-form AABB TOI (`_aabb_toi`) has a `currently overlapping` branch: if the bodies already overlap at `t = 0`, it returns `t = 0` and a SAT-style axis, independent of approach/separation. Design step 2 still applies: overlap at `t = 0` is settle, not a sweep blocker.

Resolver invariant: when TOI returns `t = 0`, keep the hit **only** if this slide's relative motion is approaching along that normal (`dot(relative_motion, normal) > 0`). If motion is separating or tangential, drop the sweep hit and let settle handle any residual depth.

Settle cannot substitute for that placement. It is bounded (`clamp(0.5 × (depth − slop), 0, 8 DU)` per iteration, four iterations), never writes `.vel`, and a moving partner can recreate more overlap than settle removes.

### Polygon sweeps

One convex polygon prim (`AABB`, `OBB`, a `POLY` ring that `_convex_ring`
accepts) swept against another takes the closed-form **swept SAT**
(`_toi_sat`, from `_toi_prim_sets` for each pair of prims).

- **The sweep.** It projects both rings on every face normal of both, and
  takes the latest entry and the earliest exit. The entry time is exact, and
  the normal is the face the body enters through.
- **A start overlap or touch** is the narrow contact, as in conservative
  advancement. The `t = 0` rule above then applies. A motion that crosses no
  face (float residue under 1e-15, a rider moving with its platform) with an
  overlapping start goes to advancement too: SAT has no entry time to give,
  and it answered "no hit" (review 2026-10-12).
- **What advances.** Circles, ellipses, capsules and rings that are not
  convex keep GJK advancement (`_toi_advance`), one pair at a time.
- **Sets are swept pair by pair** (`_toi_prim_pairs`, when either side has
  more than one prim): each pair takes the rules above, and the earliest pair
  is the union's first contact; pairs whose swept boxes miss are skipped.
  GJK on a set measures the distance between the sets' **convex hulls**, so a
  concave partner swept as one set stopped the body on its hull: a ball
  rolling into a `Concave` scoop met the chord from the foot to the lip and
  flew off at 45° (peak 80 of 149), and a ball could not drop into the notch
  of a U-shaped `Polygon` (it rested on the hull's top) — CV1 in
  [Testing Design](Testing%20Design.md). A convex partner's own pieces meet
  at shared vertices and coplanar faces; a body sliding across them keeps
  going by the `t = 0` rule above (a touch with tangential motion is not a
  stop). Cost (2026-10-14, in-process interleaved, 30 balls, 240 frames):
  a 2-wedge half-disk partner (same behaviour both ways) −10 %; six
  quarter-pipes, where the balls now ride the curve every frame instead of
  flying off the hull, +7.6 %. Single-prim pairs take the same one length
  test as before. Guards: `tests/test_sweep_sat.py`
  (`test_multi_prim_sets_sweep_pair_by_pair`, `test_a_body_enters_a_concave_set`),
  `tests/test_concave.py` (`TestRides`).

**The skin.** Advancement stops once the gap is under 1e-3, so SAT differs
from it only inside that skin:
- SAT is never earlier, and at most 1e-3 later along the normal.
- The normal is the same face.
- A pass that grazes within 1e-3 and never touches is a hit for advancement
  (a phantom corner snag, or a swept `@collide` contact) and no hit for SAT,
  as for two boxes, which were already exact.

**Ties.** Two floors that a drop meets at the same instant (a foot corner
exactly on a joint) tie. The first partner wins, the same as two level
boxes. Before, the skin made a polygon beat a box by ~1e-5.
`test_floor_below.test_walkable_slopes_are_floor` had pinned that by
accident at two joint positions; it now accepts either floor there.

Why: level tiles with rounded ends (tutorial 27's platform ends) are
8-vertex hulls. Every walker probe against them went to GJK, at ~50 µs a
cast. Ninja: work 4.25 → 3.17 ms, `floor_below` 2.6 → 1.5 ms. Mundo,
corrida and horda: flat. `_SWEEP_SAT = False` is advancement (oracle, A/B:
`game_bench.py --ab scena.collision:_SWEEP_SAT`).

Tests: `tests/test_sweep_sat.py`:
- random convex pairs against advancement (hit agreement, skin bound,
  normal);
- the exact entry time;
- grazing cases at the platform end, where a SAT miss is proved by no
  overlap along the path;
- fallbacks and `_convex_ring`;
- walkers over rounded tiles agree frame by frame;
- a canary that drops one ring's axes.

### Glue loop

A moving partner plus residual overlap is a self-sustaining clamp:

1. Contact this frame. Sweep stops at TOI in the partner's start pose. Leftover partner motion is **not** applied to the body (wrong gate, missed conversion, …).
2. Partner finishes its frame; body is left overlapping by roughly `|d_other| × (1 − t)`.
3. Settle halves that remainder; a typical elevator step (~1.3 DU at 80 DU/s) outruns the remainder. Residual overlap (~0.15 DU) survives.
4. Next frame (if the `t=0` approach gate is missing): already-overlapping TOI → `t = 0` → this frame's real (often **separating**) motion is discarded. Only the tiny settle nudge moves the body.
5. Partner translates again into the leftover gap. Overlap is recreated. Repeat.

Visible symptom: the body is glued to the partner and follows it. Logged `.vel` is free — gravity keeps integrating, speed diverges from the partner — because the clamp is **pose**, not impulse. `touching_sides` keeps reporting the contact (`"top"` for an underside hit) every frame.

Canonical case: jump up into the underside of a descending elevator (a platformer with a moving lift). Same loop for any side if leftover conversion is skipped. The standing-rider path hid the bug because `"bottom"` already inherited leftover, so a floor ride never left residual overlap.

### Diagnosing a stuck body

Split **pose** from **velocity** before touching normals, SAT, `bounce=`, or author `update()`. Isolate with axis-aligned `Rect`s — sprites and ramps are a different class of bug until the Rect case fails.

| What you log | Glue loop (pose clamp) | Impulse / `bounce=` | Author double-carry |
| --- | --- | --- | --- |
| `.vel` vs partner | Diverges (gravity keeps adding) | Matched or reflected along normal | Matched, and author also `move_by`s the partner's delta |
| Gap / overlap after `step()` | Stuck near 0 or `_RESOLVE_SLOP`, same sign every frame | Separates after the contact frame | Body moves *twice* the partner's delta |
| TOI `t` on later frames | `0` every frame (already overlapping) | `None` once separated | Sweep is fine; author motion is the extra |
| `touching_sides` | Contact side persists | Clears after the hit | Rider `"bottom"` as intended |

Headless repro: rewind both bodies, `move_by` their frame deltas, `get_collision_system().step()`, print `center`, `.vel`, gap, `touching_sides`. Instrument `_earliest_toi` / `_record_solve_contact` / `_respond_velocity` if `t` vs leftover is unclear. The example game is a reporter, not the unit of fix.

A stick only while the body keeps approaching, with a second contact against a shape the hitbox misses, is a fatter box treated as a crossed face. The sweep stop made the pose differ from the motion channel. See [Unswept bounds](#unswept-bounds).

Related traps already in this doc — do not rediscover them as new resolver features:

| Symptom | Actual layer | Pointer |
| --- | --- | --- |
| Rider hops on a **rising** platform, or uphill/downhill walk loses `"bottom"` on short frames | Floor snap leave-gate (wrong axis: world `+vy`, then speed-only) | **Floor snap / grounded flicker** |
| `"bottom"` flickers with animation | Sprite hitbox rebake (`hitbox_source="each"`), or a kind flip under `"auto"`. Kind is locked for `"each"` / `"clip"`; params may still breathe. Not a resolve bug | **Sprite colliders** |
| Body pops through a thin slab after a resize, offset, or hitbox rebake while `.vel` has turned back | Capped settle oriented the exit by `.vel`, which is no longer the approach | **Unswept bounds** |
| Airborne body sticks only while pushed into a wall; releasing the push drops it; a second contact names a shape the hitbox misses | Recovery used a fat box (the sprite broad-phase proxy, or a rotated body's bounds) after the wall slide broke the motion-channel match. `bounce=0` then cancels that normal every frame | **Unswept bounds** |
| Launch off a ramp end / ledge classified as floor | Deep-overlap SAT axis, not a missing `side` heuristic | “Do not add SAT-axis heuristics…” above |
| Hero on an elevator moves too far (twice the lift's step) | Author carries the rider too (`move_by` with the lift's step, `vel` copied from the lift or its Handle), on top of the engine's carry | [Riders](#riders-a-body-standing-on-a-moving-partner); delete the author line |
| Elevator top turnaround loses `"bottom"` for ~0.3 s | Real detach (platform velocity sign-flips; rider keeps old `+vy`) | Correct physics — not a snap bug; ease the reversal in author code if unwanted |

### What not to add

Do not gate leftover inheritance on `side`, approach direction, or “is this a platform.” The rider carry is a separate rule, gated on the `"bottom"` contact on purpose ([Riders](#riders-a-body-standing-on-a-moving-partner)); do not fold it back into the inheritance (a carry by `1 - t` is the frame-rate bug). Do not orient settle by `.vel` (or by approach) again: an overlap leaves along the minimum overlap, unless the pair's normal is remembered or the bounds crossed a face from a clear pose. Do not split a settle correction into a STATIC body: a share stops at its body's walls and the other body takes the rest. Do not back the skin off along the normal for a body that stops on a floor: it creeps downhill. Do not make the mass split depend on which body has `.vel`, on enrollment order, or on bounce: positions split by `.mass` alone, as settle does. Do not add an already-overlapping leave test inside `_aabb_toi` to paper over residual overlap — that branch exists because overlap at `t = 0` is settle. Do not grow settle's gain so it can chase a moving partner; the capped path stays `clamp(0.5 × (depth − slop), 0, 8 DU)`. The full-gap pull in [Unswept bounds](#unswept-bounds) is a separate rule for a face crossed from a clear pose, not a higher cap on spawn or on a moving partner. Do not special-case elevators or `hitbox_source="each"` in a game. Do not tighten the sprite proxy, and do not add a side gate, to stop a false contact from a fat box — recovery compares prim bounds and requires the prims to overlap. Simultaneous contacts (2026-10-15): do not answer them with one combined normal (the normalized sum, or one weighted by depth): it is wrong in a room corner, off a floor-and-ramp joint and for every `bounce` below 1, where it leaves a contact approached; the joint answer is the projection ([Joint stop](#joint-stop-simultaneous-contacts)). Do not let a tie whose normal is parallel to the earliest, or one that fails mutual blocking, into the joint stop: a tile seam's side face would stop a walker dead. Do not reflect the leftover of a body that started the frame grounded off that floor: it never rests. Do not answer a skin contact along the detection's gap normal: cast along the velocity.

Regression: `TestResolution.test_jump_into_descending_platform_underside_does_not_glue` and `test_corner_underside_and_elevator_side_contact_does_not_glue`; rider stability is probe 8 in `scripts/diag/collision_probe2.py`, underside glue is probe 9. Standing-rider tests (`test_bounce_zero_moving_floor_carries_rider`, `test_descending_elevator_with_side_contact_does_not_stall_horizontal_input`, `test_moving_platform_pushes_resting_body_without_launch`) must stay green — leftover on every side is a generalization of the rider conversion, not a replacement.

## Floor snap / grounded flicker

Floor snap is the backstop for resting contact that the primary sweep briefly misses. It is **not** hysteresis on `touching_sides`, and it is **not** a rider/elevator special case.

### Why primary contact misses on short frames

Standing resolve backs off by `_RESOLVE_SLOP` (~0.08 DU) after every contact. Gravity is what closes that gap for a resting body: the deficit is second-order in `dt` (`g · dt²`), not `g · dt`. Closing 0.08 DU at `g = 900` needs

```text
dt  ≥  √(slop / g)  ≈  √(0.08 / 900)  ≈  9.4 ms
```

Any frame shorter than that (vsync beat, hitch recovery, alternating 5 ms / 28 ms pacing) can leave a real sub-slop gap after `move_by` + sweep. Floor snap exists to heal that gap **in the same frame**, before `touching_*` is published. Without it, `"bottom"` flickers at the frame-timing frequency — often too fast to see without `play(…, min_hold=…)`, which is a visual bandage, not the fix.

This is **symmetric** for rising and falling rides, and for static floors, once the leave-gate is correct. The asymmetry people notice (“only when the elevator goes up”, “only walking uphill”) is almost always the leave-gate disabling the backstop in one direction.

### Leave gate (current rule)

Snap runs only if the body was grounded at frame start. It then refuses when the body is *leaving* the candidate floor. `n` is the snap TOI normal (body → other; down into a floor).

```text
leave_v    = −((v_body − v_floor) · n)     # outward-normal relative speed
leave_d    = −((d_body − d_floor) · n)     # outward-normal relative displacement this frame
leave_frac = leave_d / |relative motion|   # 1 = this frame's step is straight off the floor
```

`bounce=` is the author's intent for this pair. Geometry alone cannot split a 45° ramp-walk miss from a glancing elastic bounce — they are the same numbers in one frame — so the gate is **bounce-aware**:

| Pair `bounce=` | Refuse snap when | Why |
| --- | --- | --- |
| omitted / `None`, or `≤ 0.5` (**walker**) | `leave_v > 8` **and** (`leave_d > 2 DU` **or** `leave_frac > 0.85`) | World-axis `vel.x` on a slope looks like leave-speed; displacement / fraction is the honest walk-vs-jump split. `leave_frac` is the high-FPS path: a jump of 460 DU/s at 2 ms only moves 0.92 DU, so the 2 DU conjunct would glue it. |
| `> 0.5` (**elastic**) | `leave_v > 8` alone | Last frame's impulse already wrote an honest separating `.vel`. `leave_d` is `~|vy|×dt`; requiring 2 DU glues `bounce=1` balls at high FPS or moderate speed (the bouncing-balls floor stick). Snap still runs when `leave_v` is small — a nearly-resting projectile still heals slop. |

Walkability is `abs(slope_angle) ≤ 45`, so a walk-miss `leave_frac` is at most `sin(45°) ≈ 0.71`. `0.85` sits above that and below a real jump (`≈ 1`). Do **not** disable snap entirely when `bounce > 0`: snails at `0.2` and a `bounce=0.7` ball that has actually stopped still need the slop heal.

History of the walker half (why speed-only is not enough for `bounce ≤ 0.5`):

| Gate tried | What it got right | What it broke |
| --- | --- | --- |
| Absolute `vy > 8` | Blocked jumps from static floors | Disabled snap for every **rising** ride (carried `vy` matches the platform) |
| Relative `vy − ovy > 8` (world-Y) | Fixed rising elevators | Disabled snap while **climbing a ramp** (`bounce=0` keeps tangential speed; uphill walk has large world `+vy` while resting) |
| Normal-projected **speed** only | Fixed uphill climb | Disabled snap on **downhill** walk when authors set world-axis `vel.x` (looks like tens of DU/s of leave while this frame’s motion barely separates); also glued **elastic bounces** whose `leave_d` is under 2 DU |
| Speed **and** displacement along `n` | Rising ride, uphill, downhill, short frames; 60 Hz jumps still clear both | Glued `bounce=1` at high FPS / moderate `vy`; glued high-FPS `bounce=0` jumps (`leave_d < 2`) |
| Bounce-aware (this rule) | Walkers as above; elastic contacts leave on `leave_v`; high-FPS jumps via `leave_frac` | — |

A walker jump clears speed plus displacement or fraction. An elastic bounce clears speed. Resting / walking fails the tests that apply to that pair.

### Not every `"bottom"` drop is a bug

| Observation | Verdict |
| --- | --- |
| Alternating `"bottom"` while riding up / walking a ramp, far from any turnaround | Snap leave-gate (or snap disabled) — fix the gate |
| `"bottom"` false for ~15–20 frames at an elevator **top** turnaround (instant `vel.y` sign flip) | Correct: rider still carries `+vy`, platform falls away — real projectile until re-contact |
| `"bottom"` false for one animation cell | Sprite `hitbox_source="each"` rebake — **Sprite colliders** |
| `"bottom"` false while `.vel` matches the floor and gap stays ~slop | Glue loop / leftover — **Relative-frame sweep** (opposite symptom: contact stuck *on*) |

Do **not** paper over a real detach with sticky `touching_sides`. Coyote time / jump buffer / `play(min_hold=)` are author policy on top of honest geometry.

### Diagnosing grounded flicker

Split **contact truth** from **animation**. Isolate with axis-aligned `Rect`s and a scripted `dt` pattern before blaming sprites or the example.

| What you log | Short-frame miss (snap should heal) | Leave-gate too strict | Real turnaround detach | Hitbox rebake |
| --- | --- | --- | --- | --- |
| `dt` pattern | Alternating short/long; misses on the short half | Same | Near velocity discontinuity | Independent of `dt` |
| Gap after `step()` | Oscillates 0 ↔ ~slop | Gap opens and snap refuses | Opens by many DU for many frames | Changes with clip cell |
| `body.vy` vs floor | Matched (or tangent on a ramp) | Matched / climbing, but gate sees “leave” | Diverges after flip | Unrelated |
| `leave_v` / `leave_d` along `n` | Both small → snap should run | One large spuriously (wrong axis) | Both large, correctly | N/A |
| Direction asymmetry | Appears only where the old gate blocked (up / uphill) | Same | Only at top (or authored) reversal | None |

Headless repro: `Rect` rider + `STATIC` floor with `.vel`, `resolve(..., bounce=0.0)`, alternate `dt ∈ {0.005, 0.028}`, print `"bottom" in touching_sides` each frame. Warm the carry first (matched velocities). Instrument `_floor_snap` leave_v / leave_d if the gate decision is unclear. The example game is a reporter, not the unit of fix — `min_hold` on `play()` can hide a 30 Hz square wave without curing it.

### What not to add

Do not add hysteresis or stickiness to `touching_sides` / `touching_contacts`. Do not special-case elevators or ramps in author examples as the framework fix. Do not restore absolute world-`+vy` as the leave test. Do not raise `_FLOOR_SNAP_LEAVE_VY` alone to paper over world-axis slope walk — that conflates “jump-sized leave” with “spurious leave-speed”; the displacement conjunct is the correct split for **walkers**. Do not treat a top turnaround detach as a snap failure. Do not add a taught `snap=` / stick flag — `bounce=` is the intent. Do not disable snap entirely when `bounce > 0` (low-bounce walkers and resting projectiles still need the slop heal). Do not hunt for a universal motion-only test that keeps 45° walks snapped and glancing bounces free; those two are geometric aliases.

Regression: `TestSweepAndSlideGates.test_rising_platform_short_frames_keep_grounded`, `test_uphill_walk_short_frames_keep_grounded`, `test_jump_from_rising_platform_is_not_snapped`, `test_jump_from_ramp_is_not_snapped`, `test_jump_from_floor_high_fps_is_not_snapped`, `test_elastic_bounce_high_fps_does_not_stick_to_floor`, `test_glancing_elastic_bounce_does_not_stick_to_floor`, `test_elastic_ball_does_not_snap_onto_other_ball`, `test_low_bounce_walker_short_frames_keep_grounded`, plus `test_downhill_walk_stays_grounded` and the standing-rider tests above. Walker tests and elastic-leave tests must stay green together.

## Velocity: `bounce=` (`None` or restitution)

`bounce=` is **`Optional[float]`** — not one continuous dial with a default tick at zero. Two distinct cases:

| `bounce=` | Mode | `.vel` |
| --- | --- | --- |
| omitted / `None` (default) | **position-only** | never read or written |
| `float` in `[0, ∞)` | **position + velocity** along `normal` | two-body impulse (momentum-conserving; energy loss when `bounce < 1`) |

Internally the engine stores these as separate tokens (`_RESOLVE_POSITION_ONLY` vs. a float), not as “unset = 0.”

**Vocabulary:** “no bounce” in plain English usually means `bounce=0.0` (inelastic stop). Omitting `bounce=` means something else — **skip the velocity step entirely**. Docs call that **position-only** `resolve()`, not “no bounce.”

- `bounce=0` — fully inelastic along the normal; equal finite masses end at shared velocity (documented surprise case).
- `bounce=1` — elastic along the normal; `>1` — super-bounce (no upper clamp).

Mental model when velocity *is* engaged: **`.mass`** decides who moves; **`bounce=`** decides how much normal velocity survives. `bounce=0` is an inelastic impulse at the contact normal — it removes the approaching component and keeps the tangent (walking a ramp, sliding). It is not a special “platformer stop.” Floor snap reads the same token: elastic pairs (`bounce > 0.5`) leave on separating speed so a `bounce=1` ball is not glued to the floor; walkers keep the displacement conjunct — see **Floor snap / grounded flicker**.

Position-only `resolve()` still never writes `.vel`. The sweep already stops the body at the surface each frame; if author code keeps accelerating into the contact, the next frame's sweep stops it again. To cancel the normal component of `.vel` as well, pass `bounce=0.0`.

Pose movers (`move_along`, timed `move_to` / `move_by`) do **not** write `.vel`. The Handle reports this tick’s rate (`.velocity` / `.speed` / `.heading`); the author copies into `.vel` if physics should inherit it. See [Actors Design.md](Actors%20Design.md) (Handle clock).

```python
# A — engine cancels velocity along the normal at each contact
resolve(player, "walls", bounce=0.0)

# B — position-only resolve; author clamps the offending component
resolve(player, "walls")

def update(dt):
    player.vel.y -= GRAVITY * dt
    ...
    for c in player.touching_contacts:
        if c.side == "top" and player.vel.y > 0:
            player.vel.y = 0.0   # head-bonk — other is above
    player.move_by(player.vel.x * dt, player.vel.y * dt)
```

`side == "top"` means the other body is above `a` (y-up). Reads last frame's `touching_contacts` (same one-frame lag as `touching_sides` for grounded). For same-frame policy, use `@collide_stay(player, "walls")` and `info.side` / `info` before auto-resolve runs.

## Manual-resolution ladder (same idiom, five zoom levels)

| Level | Call |
| --- | --- |
| Declarative | `resolve(a, b, bounce=…)` |
| One-shot detect + resolve | `shape.resolve_now(target, bounce=…)` |
| This pair in a handler | `info.resolve(bounce=…)` |
| Named apply | `info.push_apart()` / `info.bounce_apart(bounce=…)` |
| Raw tuples | `info.mtv_split()` / `info.velocity_split()` |

`reflect_velocity` remains; `velocity_split` generalizes it when both masses are finite.

## Grounded / touching

- **`touching_sides`** / **`touching_contacts`** — only pairs registered with standing **`resolve()`**. Detection-only overlaps (`@collide` sensors, collectables, triggers) never appear here, even when overlapping. One-shot **`resolve_now()`** without a registry entry does not feed **`touching_*`** either.
- **`touching_sides`** — `frozenset` of `"top"` / `"bottom"` / `"left"` / `"right"` (±45° buckets from contact normal). Engine-written each frame. When a formula depends on it (e.g. `hero["grounded"] @= lambda: "bottom" in hero.touching_sides`), updates propagate through a **`ScalarAnchor`**; otherwise cold ink write with no graph traffic.
- **`touching_contacts`** — plain tuple of `TouchingContact` (`.other`, `.side`, `.slope_angle`, `.normal`, `.tangent`, `.point`). Same resolve-only filter; recomputed each collision step. `.point` is a world-space contact location (manifold centroid when available; otherwise a prim-support witness — vertex-on-face prefers the resting corner) — useful for VFX or for hugging art to the surface. Enter/stay `@collide` `CollisionInfo.point` uses the same fill.

Sensors still fire **`@collide`** / **`collides_with()`** — only **`touching_*`** is resolve-scoped.

`@collide` on a resolved pair is steady while resting — see [Resting contact (skin)](#resting-contact-skin). For "standing on", still prefer `touching_sides` / `touching_contacts`: they come from the resolved pose and are steady in every case.

## Floor ahead: `floor_below`

`body.floor_below(dx=0, depth=None, group=None)` → the floor body `body` would stand on after stepping `dx` (signed, `+` = right), or `None`. The platformer ledge question: the patrol that turns before falling, the teeter animation. Guia: [Chão à frente](../docs/pt/guide/index.html#colisao-floor).

**Invariant: it asks the solver's own question.** `None` must mean "the resolver would let this body fall", so every ingredient is the solver's:

| Ingredient | Source |
| --- | --- |
| Shape | the body's collision prims (`_world_prims`), never `graphic.box` (padded sprite art is wider than its hitbox) |
| Floor | first hit's normal classifies `"bottom"` (`_side_from_normal`, ±45° — same buckets as `touching_sides`) |
| Fall | a drop deeper than `depth`; default `_FLOOR_SNAP_MIN` (16 DU) — a drop within it floor snap steps down, beyond it the body leaves `"bottom"` |
| Ground | default: the body's standing `resolve()` partners (`_resolve_partners`), `only=` included via `_QueryOnlyGate`. `group=` names the ground instead (query grammar; hitbox parts never count) |

**March.** Sub-steps of at most `_FLOOR_PROBE_STEP` (8 DU, capped by `depth`), each: **lift** by the step + `_FLOOR_PROBE_LIFT_MARGIN` (a 45° rise; a ceiling clips it) → **across** by the step → **drop** by lift + `depth`. Every sub-step must land on a floor, so a tile join is never an edge and a walkable slope never a ledge; a sheer drop deeper than `depth` anywhere along the path is `None`. **`depth` is a sheer-drop threshold only**: the sub-step shrinks with it, so a slope up to 45° drops at most `depth` per sub-step and stays floor at any `depth` (`test_depth_never_turns_a_walkable_slope_into_a_ledge`). A scene with slopes and no step between two `depth` values shows no difference — that is correct. Casts are `_earliest_toi` against the live pose with partner motion zeroed.

**Walls are not ledges.** An across cast that hits, or a drop that lands on a too-steep face whose normal points *forward* (a rise ahead the lift margin cleared), rewinds to the last pose that stood and answers the floor there. A too-steep face whose normal points *back* is a slope falling away: `None`. Do not drop from the part-advanced pose after a block — it scrapes a slanted wall and reads "no floor" (the first implementation did; `test_steep_rise_is_a_wall_not_a_ledge`).

**A read.** Live pose via `_update_proxy(commit_motion=False)`; motion stays pending for `step()`; a body not enrolled is probed through an unregistered collider, candidates through `_query_collider` (no enroll, like named queries). The `only=` gate never marks a pass (`_QueryOnlyGate.mark` is a no-op). Dead or inactive → `None`. No ground at all (not in any `resolve()` pair and no `group=`) → `ValueError` naming both fixes.

**Debug.** With `show_colliders`, each call keeps the body's end pose (one per body, capped at `_FLOOR_PROBE_DEBUG_CAP`); `debug_draw` strokes it magenta (floor) or red (none) and clears the set.

**Not grounded.** `floor_below()` finds a floor up to `depth` below — also early in a jump. "On the ground now" stays `"bottom" in touching_sides`.

**The width is the hitbox's.** "Front edge reached the ledge" is `dx = g.hitbox.box.width` (signed). `sprite.box.width` is the drawn cell, transparent padding included, so a padded sprite would turn early ([Sprite Design.md — Measuring a sprite](Sprite%20Design.md#measuring-a-sprite)).

### `floor_below`: cost

A walker that asks every frame pays one call per frame per robot, so the march is
a hot path (ninja tutorial 27: 7 calls a frame were 75 % of the frame,
[games.md](../scripts/bench/games.md), D1). Two reductions, switched off together
by `_FLOOR_PROBE_FAST = False` (the oracle; `game_bench.py --ab`):

- **Trust the partners' world prims during the march.** Every partner proxy is
  refreshed (`_update_proxy`) at the start of the call, and nothing moves a body
  until it returns, so the casts run with `_trust_proxy_world` on, as the narrow
  and resolve passes do: `_world_prims` returns the cached prims when
  `_world_key == _proxy_key` instead of rebuilding up to 15 pose keys per partner.
  An `only=` function runs inside that window, as it does in resolve.
- **Reject on the whole march once.** `_floor_probe_envelope` bounds every cast:
  the probe, `[0, dx]` sideways, and per sub-step at most `step + margin` up and
  that plus `depth` down, over `ceil(|dx| / step) + 3` sub-steps. A partner whose
  fresh proxy misses it is dropped before the casts, not re-tested by each.
  The march still runs with an empty list, so the debug end pose is the same.

Still O(group) per call: every candidate's proxy is refreshed first (a moved tile
must be seen). Making that refresh cheap or skippable is the pose-revision /
vectorized-candidate proposal, not this. Tests: `tests/test_floor_below_fast.py`
(randomized scenes, fast vs plain: same floor and end pose; a tile moved by `=`
just before the call is seen; canaries: a too-small envelope, a skipped refresh).
Measured: ninja `floor_below` 6.6 → 6.0 ms per frame on its own; with
[axis-aligned hulls](#axis-aligned-hulls) 6.2 → 3.7 ms.

### `floor_below` fences

- No `@at_ledge` / `@leave_floor` event, no `facing=` knob, no auto-turn: the query stays a read the author polls; direction is the sign of `dx`. Revisit: a taught script needs an edge event that polling `floor_below` in `update()` cannot express.
- No side-sensor helper (two hitbox parts beside the feet, read through `touching_sides`). `touching_*` is resolve-scoped and parts cannot resolve; a sensor hard-codes `dx` / `depth` as box sizes, is Sprite-only, placed in image pixels, and answers "ground under this spot", not "will I fall". Authors can still build one (a hidden `Rect` linked with `@=` + `collides_with(group=)`; `scripts/smoke/ledge_probe.py` shows both). Revisit: same bar as above.
- No `has_floor` / bool twin and no `collision.floor_below(body)` spelling: one method on `Graphic` (sibling of `touching_sides`). A returned body is truthy while alive.
- Do not let `floor_below` bypass the resolver's floor definition (its own angle, its own reach). If the solver's floor rule or snap reach changes, this changes with it. The seam step needed no change here: the march's lift (sub-step + 1 DU) already covers a `_SEAM_STEP` lip (`test_floor_below_agrees_across_a_lip`).

## One-way pairs: `only=`

```python
resolve(heroi, "fina", bounce=0.0, only="bottom")          # jump-through platform
resolve(heroi, "fina", bounce=0.0, only={"bottom", "left", "right"})  # solid sides
resolve(heroi, "porta", only="left")                        # one-way door
resolve(heroi, "fina", bounce=0.0,
        only=lambda c: c.side == "bottom" and not st.descer)  # drop through
resolve(heroi, "barreira", only=lambda c: c.other.fill != heroi.fill)
```

**Rule.** `only=` lists which of the **first argument's** sides this pair may produce in its `touching_sides` — the same words, the same ±45° buckets. `"bottom"` = standing on it. An accepted contact is an ordinary `resolve()` contact (sweep stop, `bounce=`, `touching_*`, floor snap, riders). Any other first contact makes the pair **pass**: sweep, settle, unswept recovery and floor snap ignore it until the two bodies stop overlapping. Walking into the side of an `only="bottom"` platform passes through it (genre semisolid); list the sides to block them.

**S1: the side is the contact normal at first contact** — the same normal a solid pair would use. Not "the feet were above the top at frame start" (S2). A diagonal fall that meets the side face first falls past, exactly as it would slide down a solid wall. Forgiveness (corner grace) is author policy, like coyote time.

**Values.** A side string; a `list` / `tuple` / `set` / `frozenset` of sides (OR — order does not matter, like `group=`); or a function of a `TouchingContact` returning True to block. All four sides is no filter (stored as `None`). Refused at `resolve()`: an empty collection (`unresolve` instead), a non-side word (`"floor"` / `"above"` hint `"bottom"`, `"ceiling"` / `"below"` hint `"top"`, `"bottom, left"` hints a set), a non-string item, any other type.

**Perspective.** Always the first argument's view. When the solved body is the second argument, set specs are mirrored (top↔bottom, left↔right) and a function gets the flipped contact (`c.other` is then the solved body). A self-paired side (`resolve("caixa", "caixa", only=...)`) sees each contact from both bodies: a set must be mirror-symmetric (`{"top", "bottom"}`, `{"left", "right"}`) or it raises; a function should be symmetric.

**The function** runs inside the collision step, possibly several times a frame (each slide, settle, snap). It must only read, and answer the same way for the whole frame; side effects belong in `@collide` (which keeps firing while the pair passes — detection is not filtered). `c.point` is `None` when the solver has no contact points yet (a sweep contact).

**Read-only guard** (`purity_check.py`), two layers, neither on a hot path:

| Layer | When | Refuses | Error |
| --- | --- | --- | --- |
| Static | at `resolve()`, once (same source locator as `@=` formulas; plain helpers it calls are followed, 4 deep) | attribute / index writes and `@=` on Scena objects, the contact, or an alias (`h = heroi; h.x = …`); Scena verbs that change the world or consume per-frame state (`move_by`, `destroy`, `tag`, `play`, `after`, `recently`, `ready`, `chance`, `keyp.once`, `resolve`, …); creating a Scena object (except `Vec2` / `Color`); `setattr` / `exec` / `global` / `nonlocal` | `TypeError` naming the line (and the helper) |
| Runtime lock | while the function runs (`_OnlyGate.ok`, callable branch only) | cold choke points: `Registry.register` (spawn), `add_to_group` / `remove_from_group`, `destroy`, `resolve` / `unresolve` / `@collide` registration, `after` / `every` / `tween`, `play_sound`, `recently` / `ready` polls, `keyp.once`, `chance`, `change_act`, `st.x = …` | `RuntimeError` naming the function (`file:line`) |

Allowed: reads, loops, `print`, locals, and writes to the author's own plain objects (a module dict / list, a local built from a literal, an author object's attribute). Not covered: a pose / slot write (`heroi.x = …`) inside code the static pass cannot read (no source, a `__call__` object) — those write paths are the engine's hottest, so they carry no runtime check. The lock refuses *before* the change (the registry's collision notify swallows exceptions, so the group check sits in `add_to_group` itself).

**Last call wins.** Re-registering an equal pair replaces `bounce=` **and** `only=`, in the new call's order. Scene snapshot / restore carries `only=`.

**Registration conflicts raise.** When two registrations reach the same body pair with different `only=` (a platform in both `"plataforma"` and `"fina"`), first-wins would drop the filter by declaration order. `resolve()` raises and rolls back; a later tag join raises on the next `step()`. Give one-way platforms their own tag.

**Passing state.** `_passing` maps body → {partner: collider}, stored on both bodies. A pass starts when (1) a rejected sweep hit comes before any accepted hit in that slide (later rejected hits are re-judged from where the body really is), or (2) settle / unswept recovery rejects an overlap. It ends at the body's next solve once the prims no longer overlap, or when the pair is no longer filtered. Floor snap never grabs a passing pair, so drop-through does not snap back. Cleanup does not rely on `_only_view`: a body whose partners are all gone never reaches it, so the end of `_apply_auto_resolve` drops bodies **and partners** that left the resolve world (`test_destroy_mid_pass_leaves_no_state`; `_passing` is in the system census).

**Where the gate sits (cost).** `_has_only` is False unless some pair has `only=`; then `_apply_auto_resolve` reads one bool per body and nothing else changes. With filters, only bodies with a filtered partner get an `_OnlyGate`, and `ok()` runs only **after** `_toi_prim_sets`, `_collision_info_for_colliders` or `_aabb_entry_normal` already found something (≈5 per frame in the 40-ball pool, against ≈3,600 partner visits). Measured 2026-09-29 (`resolve-2` probes, 9 / 7 interleaved runs): balls `ms_resolve` 0.674 → 0.677, platformer 1.973 → 1.981 — noise.

**Known limits.** Sides are world buckets: a one-way slope steeper than 45° needs a function comparing `c.normal` with the platform's rotation. A row of one-way tiles holds the walker on aligned seams through the resting skin (`_RESOLVE_SLOP`; `TestTileSeams` pins 30 / 60 / 240 fps), and on seams with a lip up to `_SEAM_STEP` through the seam step ([Seam lips](#seam-lips-step-up)); a taller lip is walked through, like any side face.

### One-way fences

- Do not put the filter in the `(cb, token, odx, ody)` partner tuple or test it per partner visit — that is thousands of checks per frame for a feature most scenes never use. Dispatch per body; read the gate after a hit.
- No second keyword (`unless=` / `except_=` / `pass_through=` / `sides=`): `except` is reserved, and a negative form would be a second spelling of the same filter. Revisit: a taught game that `only=` cannot express.
- No shape-level `one_way` / `.solid` flag — the pair decides push (see the `.solid` fence), and a shape flag cannot say "the hero passes, the crate does not".
- Do not mark a pass on a rejected hit that an accepted hit precedes: the next slide would then ignore a platform the body lands on (`TestTileSeams` fails).
- No S2 "was above" rule inside the engine; express it in a function if a game wants it. The one bounded exception is the seam step: a grounded body, a still side face, at most `_SEAM_STEP` of rise ([Seam lips](#seam-lips-step-up)).
- No solver-lock check on pose / slot / `Vec2` write paths or `Entity.__setattr__` — hot for every scene. The static pass refuses those writes; the runtime lock stays on cold choke points. Revisit: a taught game that writes pose through unreadable code inside `only=`.
- Do not put a lock check behind a `try/except Exception` (the registry's collision notify): the refusal is swallowed after the change already happened.

## Resting contact (skin)

**A standing `resolve()` pair within `_CONTACT_SKIN` of each other is a contact for `@collide` / stay / exit.** (F1 in [Testing Design](Testing%20Design.md#f--contact-flicker-2026-09-29).)

Why: `@collide` reads the detection snapshot, taken *before* resolve. The sweep stops a body `_RESOLVE_SLOP` (0.08 DU) short of its partner, so a resting body is a small gap. Without a skin it only overlapped when that frame's fall (g·dt²) was deeper than the slop: steady at 60 Hz, "not touching" at 200 Hz, enter / exit every other frame with 5 / 28 ms pacing.

| Rule | Detail |
| --- | --- |
| Which pairs | Both colliders on a standing `resolve()` registration that matches this pair (`_resolve_bounce_for`), and `collision.resolve_enabled` is on. Sensors (`@collide` only), `resolve_now`, and queries (`test_collision`, `collides_with`, `query_*`) stay strict overlap (a sensor also sees a fast body's path — [Swept detection](#swept-detection-fast-bodies); queries never sweep) |
| Skin | `_CONTACT_SKIN = 2 × _RESOLVE_SLOP` (0.16 DU): margin over the slop for the gap settle / snap actually leave |
| Carry (PB4) | A rider on a `STATIC` floor that moved away this frame (a lift going down by `move_by`) is a gap of the slop + the floor's drop − the rider's own fall before resolve, past any fixed skin (60 DU/s at 60 Hz; 30 DU/s at 144 Hz), while floor snap keeps it grounded: `touching_sides` said `"bottom"` and `@collide` exited, a yoyo lift exited at the top and never re-entered. So a floor gap (normal within 45° of vertical, from the rider down) counts up to the skin plus the floor's motion-channel travel along the gap normal (`_carry_opening` → `_skin_contact`). Only when the floor side is immovable and moved, and the rider is movable and was grounded at the start of the frame — snap's own precondition. A rider's own motion (a jump off the lift) and a wall moving away are not a carry, and a placement (`center =`) carries nothing |
| Gap | True prim distance (`_prim_gap`: closed form for AABB / circle pairs, `_gjk_distance` otherwise), not the AABB: a circle near a rotated box's AABB corner is not a contact |
| Payload | `depth = 0.0`; `normal` A → B from GJK; `point` from the prim-support witness (same fill as enter / stay) |
| Cost | Only for resolve broad pairs that did not overlap and whose prim AABBs are within the skin (plus the carry, which costs two attribute reads per pair with a moving side: in-process A/B within noise, 2026-10-14). 30 walkers on 100 tiles at 5 / 28 ms pacing: within noise (GJK alone for boxes cost ~8 %, hence the closed forms); a 200-ball `resolve("ball", "ball")` pile: ~6 %. `last_stats["skin"]` counts skin contacts |
| Resolve | A zero-depth skin contact never pushes. One that the body's sweep never reached is answered for velocity that step (LW8, 2026-10-15; `_answer_unreached`, `_SKIN_ANSWER`): a body that made no stop, was airborne at the start of the frame, on a `bounce > 0` pair, whose velocity approaches the partner. The normal is a cast of `2 × _CONTACT_SKIN` along the velocity (the sweep's question: the detection's gap normal at a seam is a corner-to-corner artefact, and it once gave a landing walker `(54.9, +7.5)`); the contact is recorded, so `touching_*` agrees with what `@collide` saw. Why: a brick broken the frame after its `@collide` was gone before the sweep that would have bounced the ball, which flew through it (2 % of hits at 60 Hz, 5 % at 144). Not for `bounce=0` (the next sweep answers it; answering early turned an idle hero's fall into a slide down a ramp, P5) nor for a grounded body (floor snap's) |

Accepted limitation (F2, by design): a **curved** body (circle, rounded hitbox) walking over tile seams with **uneven** frame times can enter and exit the *next* tile for a few frames near the seam. The pre-resolve pose sinks by g·dt² (0.6 DU on a 28 ms frame, none on a 5 ms one), so its gap to the tile's corner swings across any fixed skin. It needs all four: a curved body, a seam between separate pieces, uneven pacing, and per-tile `@collide` enter / exit. The tile it stands on stays in contact; grounding and motion are unaffected; steady 60 / 144 / 200 Hz and flat-bottomed bodies are clean. "Which tile am I on" is `touching_contacts` (resolved pose, steady at any pacing) — the Guia teaches that ([Tocando](../docs/pt/guide/index.html#colisao-touching)).

Fence: do not move resolved-pair `@collide` to the resolved pose (dispatch after resolve, or a post-resolve membership test) to cure F2 or a carry case like PB4 (widen the skin by what the solver will provably undo instead). It splits the [Frame order](#frame-order) rule ("handlers see this frame's detection, then resolve runs"), drops the impact `depth` on enter, and breaks same-frame policy in `@collide_stay` — more cost to teach than the artifact. Reopen only with a real game that shows it. Guard: `tests/test_sys_resting_contact.py` (F2 kept as an `expectedFailure` tripwire: if the behaviour changes, the unexpected success says so; `TestRiderOnAMovingLift` for the carry, with a guard that turning the carry off loses the contact again).

Coyote time / jump forgiveness = author policy on top (e.g. timestamp on `@collide_exit`), not built into `touching_sides`. Short-frame / rising-ride / ramp-walk flicker of `"bottom"` is a floor-snap leave-gate issue, not coyote — see **Floor snap / grounded flicker**.

A Sprite collider that **changes shape every animation frame** (`hitbox_source="each"`,
or a kind flip) will drop `"bottom"` and bob the body even when `_RESOLVE_SLOP`
is doing its job. `"auto"` with `"each"` / `"clip"` locks kind after the first
bake of that reference set so the family stays put while the fit breathes.
That is a hitbox-stability issue, not a resolve bug — see **Sprite colliders** below.

## Swept detection (fast bodies)

**A body that travels more than half its thickness in one frame is detected along its path, not only at the end pose.** Before this, a `@collide` shot moving faster per frame than the overlap window passed through its target, and how often depended on the frame rate (CT1 in [Testing Design](Testing%20Design.md#ct--continuous-detection-2026-10-05)).

| Rule | Detail |
| --- | --- |
| Fast | Motion-channel travel `d` this frame (`move_by`, `time=` ticks, `move_along`, the chord of an orbit — never placement) whose length exceeds `_FAST_MOTION_FRACTION × thickness`. `_FAST_MOTION_FRACTION = 0.5`; thickness = the smaller side of the proxy without `_PROXY_EPS` (a circle: its diameter), cached as `_thick2` when the proxy is rebuilt |
| Why 0.5 | Two convex bodies pass through each other within a frame only if their relative travel exceeds `thick_a + thick_b`. Each side moving at most half its thickness keeps the relative travel under that, with room for a rotated proxy's √2. Below the gate, detection can miss at most a shallow corner graze (depth ≲ travel / 2), the same as before; never a pass-through |
| Which pairs | Every broad pair with a fast side — `@collide`, `on_collide` / `ANYTHING`, `@collide_with`, and resolve pairs (detection runs before resolve, so the [Frame order](#frame-order) rule holds). Hitbox parts travel with their host (`note_collider_motion` adds the host's delta to each part) and are judged by their own thickness |
| Test | Relative motion `d_a − d_b` in `b`'s end frame; proxy reject (`_aabb_toi`), then the resolve TOI (`_toi_prim_sets`: closed form for circle / AABB, conservative advancement otherwise) on `a`'s prims rewound to the start pose. Pairs moving together (`d_a == d_b`) are skipped |
| Contact | A hit with `t > 0` is a contact this frame: enter if new, stay if the pair was already open (a body pushed into a resolve wall). A hit at `t = 0` (already overlapping at the start pose) counts only if the pair was not open: a contact already reported has ended. A detection-only crossing therefore enters, exits next frame, and never stays |
| Payload | `depth = 0.0`; `normal` A → B at the time of impact; `point` from the prim-support witness with both bodies placed at the impact time. The bodies stay where they ended — detection never moves a body, and `info.resolve()` / `push_apart()` do nothing at depth 0 |
| Order | Enters with a fast side run in time-of-impact order, the rest after them in collider order. A new end-pose contact with a fast side gets its entry time too. With `_dispatch` skipping enters for a body already destroyed, a shot that destroys itself hits the enemy it reached first. With no fast collider, enter order is unchanged |
| Cost | Nothing is fast: one multiply and one compare per **moving** collider inside `_commit_pending_motion` (still colliders never reach it), one empty-list check per step; no extra broad pairs, prims or TOIs. The list `_fast_colliders` is filled only in `step()`'s proxy loop (`_fast_k2` is `inf` elsewhere, so a commit from `register()` or a query never lists) and emptied when the narrow phase ends. A fast body pays a widened broad box and one TOI per candidate pair with no end-pose contact. `last_stats["fast"]` / `["swept"]` / `["swept_hits"]` count them. Bench: `scripts/bench/perf_collision_fast.py` (`--sweep-off` is the in-process A/B) |

Known limits (same as resolve's sweep): translation only — a spin (turn about the anchor), scale, and placement (`center =`, instant `move_to`, instant `rotate_to`, `tween(center)`, `center @=`) are not swept. An orbit is swept along its chord ([Orbit chord](#orbit-chord)); the parts of a spinning host orbit the host but carry no motion. Spin: [Spin (not swept)](#spin-not-swept). The proxy overestimates thickness for diagonal Line / OBB / Track pieces, sprites with a hitbox offset, and spinning sprites, so those are swept less often; it matters only when both bodies are thin. A compound `Collider([a, b])` with no identity shape carries no motion. `show_colliders` draws the end pose.

Fence: no `continuous=` / `bullet=` flag on the pair or the body. The gate is what keeps slow scenes free, and a flag would leave the default silently wrong — tunnelling is invisible until a player notices it on a slower machine. Do not lower `_FAST_MOTION_FRACTION` to "catch grazes": it only adds sweeps (grazes stay frame-rate dependent at any gate). Guards: `tests/test_collision.py` (`TestSweptDetection`, including `test_slow_scene_pays_nothing`, the perf contract, and a canary with the gate off), `tests/test_sys_fast_shots.py` (same hits at 30 / 60 / 120 Hz and 5 / 28 ms), `tests/test_sys_hyp_collision.py` (`TestFastMotionAgainstSweptOracle`).

## Spin (not swept)

A turn about the body's own anchor (`rotate_by(30)`, a spinning `angle`) moves no anchor, so nothing is swept: a saw blade sweeps its tips along an arc between two poses, and only the end pose is checked. An orbit is swept ([Orbit chord](#orbit-chord)); a spin is not. Parked since the sweep redesign; the 2026-10-05 review (CT4) split the question in three:

| Part | Answer |
| --- | --- |
| Orbit (`about=` off the anchor) | **Shipped** — [Orbit chord](#orbit-chord) |
| Spin in `@collide` | **Parked.** Rare at Scena's scale (numbers below). If built, use the sub-pose design below |
| Spin in `resolve()` | **Do not build.** It is not a sweep: the relative-frame conversion (`ox += d_other × (1 − t)`, [Relative-frame sweep](#relative-frame-sweep)) becomes carrying the body around the pivot — rotational rider carry, rotating pushers — in the most fragile solver code (glue loop, floor snap). Physics-engine territory. A rider that does not turn with a spinning platform is a separate feature request, not tunnelling |

**How rare.** A spinning body tunnels only when its tip travels, in one frame, more than about its own thickness plus the target's. Tip travel is `ω · r · dt`. The sample games that spin a collider (measured 2026-09-29), at 60 Hz:

| Sample | Body | Spin | Tip travel / frame | / thickness |
| --- | --- | --- | --- | --- |
| Platformer wheel (`roda`, `resolve()`) | 120 × 20 | 150°/s | ≈ 2.6 DU | 0.13 |
| Bouncing balls wheel (`roda`, STATIC) | 100 × 20 | 50°/s | ≈ 0.7 DU | 0.04 |
| Shooter enemies | `RegularPolygon`, radius 22 | 60°/s | ≈ 0.4 DU | ≈ 0.01 |

All are 4× or more below the 0.5 fast gate. A tunnel takes something like a 300 × 6 blade turning 20° per frame (1200°/s) against a small target.

**If a game needs it (detection only).** Reuse the gate's argument ([Swept detection](#swept-detection-fast-bodies), "Why 0.5") instead of a rotational TOI:

- Gate: cache the max anchor-to-proxy-corner radius `r_max` with the proxy. A fast spinner has `|Δθ| · r_max > 0.5 × thickness`. Slow scenes pay one multiply + compare per rotating collider.
- Sub-poses: split the frame into `N = ceil(|Δθ| · r_max / (0.5 × thickness))` interpolated poses. Each step is under the gate, so a plain overlap test at each sub-pose cannot be passed through. Cost: `N` narrow phases per candidate pair, fast spinners only. Broad box: the disc of radius `r_max` around the anchor.
- Channel: one float, the accumulated `Δθ` this frame, noted by every turn that is motion (`_rotate_as_motion` already sees every `rotate_by`; also timed rotations, sprite heading, hitbox parts). Accumulate, never diff angles: `rotate_by(360)` in one frame is a full sweep. The pivot need not be stored — start and end anchors plus `Δθ` fix the rigid motion.
- Payload: as swept detection — depth 0, normal and point at the first overlapping sub-pose.

Not taken: conservative advancement with an angular bound (closing speed `|v·n| + |ω| · r_max`). Correct, but in pure Python every iteration rebuilds rotated prims, and a rotated AABB prim loses the closed-form `_toi_fast` paths. Author fallback meanwhile: cast a ray along the blade tip's path ([Queries](#queries-on-demand)).

Reopen on a real report (a spinning hazard missing the player, e.g. at 30 Hz), not hypothetically. A report about riders on rotating platforms is the `resolve()` row above, not this.

## Ramps

Reading tools on `CollisionInfo` / contacts: `slope_angle`, `tangent`, `slide_along(velocity)`. Walkability threshold is author code (`abs(slope_angle) <= 45`), not a framework property. With sweep-and-slide the contact normal is the obstacle's face, so `slope_angle` and `"bottom" in touching_sides` are trustworthy on ramps (including the end face, which reads `left`/`right`, not `bottom`).

Do **not** rotate a `resolve()` collider to match the ramp — that invalidates the pose the solver just settled. For sprites, lean the art only with `Sprite.tilt`.

### Two recipes

**A — sugar (preferred for walkers):** assign every frame; auto-picks a bottom contact and clears when airborne.

```python
heroi.tilt = "ground"  # or AUTO_GROUND
```

While `"bottom"` is in `touching_contacts` and `hitbox_anchor` is the bottom face, paint **rotates** about that anchor by the contact's `slope_angle` and **shifts along `normal`** until the anchor lies on the contact plane. It does not slide to the resting corner. With no bottom contact, lean is **0** and the shift is **0** — nothing sticks after a jump or ledge leave.

**B — explicit contact:** author chooses which contact; must clear first or the last lean sticks.

```python
heroi.tilt = 0
for c in heroi.touching_contacts:
    if c.side == "bottom":
        heroi.tilt = c   # rotate about the feet; seat along the normal
```

The leading `heroi.tilt = 0` is required: `tilt = c` stores the contact's angle. If the loop finds no bottom contact (airborne), that assignment never runs and the previous lean would remain. `"ground"` does not need this reset because it re-reads `touching_contacts` every paint.

### What `tilt` does (and does not)

`Sprite.tilt` is visual-only; it does not touch the hitbox, `.angle`, or the solver pose.

| Assignment | What it does | Clears when airborne? |
|---|---|---|
| `tilt = <number>` | rotate about the baked `hitbox_anchor` by that angle. No seat | no — sticks until you overwrite |
| `tilt = <TouchingContact>` | same rotation, angle = `slope_angle`. If `side == "bottom"` and the anchor is the bottom face, also shift the paint along `normal` onto the contact plane | no — sticks until you overwrite (`tilt = 0` first each frame) |
| `tilt = "ground"` / `AUTO_GROUND` | same rotation and the same normal-only seat, from one bottom contact | yes — angle 0 and no shift when no bottom contact |

`reset_rotation()` also clears `tilt` (back to angle mode at 0).

All three spellings rotate about the anchor on the baked hitbox **as drawn** (mirrored under `flip_x` / `flip_y`, the same point the emitted collider uses), not a point on the PNG and not a support vertex. None of them move `center`. The seat is along the contact normal only: a hull's toe and the upright box's resting corner do not drag the art sideways. `"center"` and `"top"` are not dropped onto the floor. Teach `hitbox_anchor="bottom"` for walkers so the pivot is the feet and the lean sits on the ramp. The two lines go together: with the default `"center"`, `"ground"` leans the art about the collider's middle, so on a slope the feet slide sideways and float (the 0.8.0 ninja: ~11 DU sideways, ~5 DU up on a 15° plank). Tutorial 27 ("A tábua inclinada") teaches the pair; `test_tutorials.TestGroundLeanHasBottomAnchor` (TU7) keeps every step and example honest. Do **not** auto Y-scale the hitbox from `tilt` — the upright collider is the gameplay geometry; a taller yellow debug box than the leaned silhouette is expected, not a cue to shrink `hitbox_scale.y` each frame.

A rigid axis-aligned box on a slope still rests on **one corner**. The art's bottom-centre is seated on the plane through that corner; the collider is not.

Ceiling head-bonk is the mirror (`side == "top"`, clamp positive `vel.y`) — see **Velocity** above.

Sweep-and-slide is sequential (body B sees A's already-corrected pose; deterministic via `_collider_index`, not order-free). Exhausting 4 slides in an acute inside corner **stops** the body — the right failure, not a glitch. It does not stack piles of mutually-resolving crates (Scena is not a physics engine). Fast-spinning obstacles (a turn about their own anchor) can still be tunnelled (the sweep assumes linear relative motion this frame); an orbit is swept along its chord ([Orbit chord](#orbit-chord)). Sub-stepping for spin is **parked, not v1** ([Spin (not swept)](#spin-not-swept)). One-way pairs are `resolve(..., only=)` — [One-way pairs: `only=`](#one-way-pairs-only); a filter alone was not enough (settle and snap must honour it too). A rounded/capsule bottom would close the one-corner rest gap; not built.

Headless regression: `scripts/diag/collision_probe*.py` (probe 8 = elevator rider, probe 9 = jump into a descending underside). Glue-loop unit test: `tests/test_collision.py` — `test_jump_into_descending_platform_underside_does_not_glue`. Floor-snap leave-gate: `test_rising_platform_short_frames_keep_grounded`, `test_uphill_walk_short_frames_keep_grounded`, and the jump-not-snapped pair — see **Floor snap / grounded flicker**.

## Queries (on-demand)

Queries and `raycast` refresh the live pose (`commit_motion=False`). They do not consume `move_by`'s pending motion; `step()` is the only consumer. A probe that is not already collidable is not enrolled. A named query does not enroll its candidates either.

**Two meanings of `group=`.**

- **Omitted, `None`, or `ANYTHING`** — the enrolled collision world: registered **body** colliders only (`collidable`, `@collide`, `resolve`, `on_collide`). Hitbox parts are excluded. This is what `query_point(mouse)` means.
- **A tag, `group["name"]`, or a collection of those** (`list` / `tuple` / `set` / `frozenset`, same OR grammar) — the in-play members of that group, whether or not any `@collide` / `resolve` declared the tag. `collides_with(group="enemy")` means "which enemies overlap me". Members with `collidable = False`, `active = False`, or already destroyed are out. A hitbox part that claims the tag answers instead of the body; a switched-off part answers for nothing. Members on `ui` or a parallax layer are skipped (a HUD icon in the group must not fail the query). A bare `Entity` has no collision geometry and is skipped. Object atoms (a Shape, a Collider) keep the pair-target path and may enroll, same as `@collide`.

Naming a group has **no side effects**: no new registry entry, no `_pair_tags` bit, no new `ANYTHING` partner. An unregistered member is tested through a cached transient collider (`register=False`, `bind=False`) so the next frame reuses world prims. Do not read `_tag_colliders` as group membership — it is the broad-phase index for **declared** tags only. A declared plain tag may use that index because enrollment already matches the member list; a formula name (`group["foes"] @= …`) always walks the formula, because those members are not tagged with the formula's name.

**Caster.** On `query_point`, `query_circle`, `query_sector`, and `raycast`, a Graphic or SpatialFx origin that is not a `Point` is the caster. The caster and its hitbox parts are never hits — the probe starts inside its own body. A plain position (`Point`, `Vec2`, `(x, y)`, `mouse`, `guard.center`) has no caster. `query_shape` already skips its own probe.

**`ignore=` adds to the caster.** A body (identity, including that body's parts), a tag, a live `group["name"]` (formula groups included), or a list of those. `ANYTHING` raises. A number or other type raises `TypeError`. A tag with no members is legal and matches nothing. Tags match registry membership, not `_tag_index`, so a body that is only `collidable = True` is still skipped.

- **`collision.query_point(x, y)`** or **`collision.query_point(p)`** — identities whose hitbox contains the point (not `Graphic.contains_point`, which is pointer/draw geometry). `p` is any point-like, snapshotted. Optional `group=` and `ignore=`.
- **`collision.query_circle(x, y, radius)`** or **`collision.query_circle(p, radius=r)`** — identities overlapping that circle. A positional radius after a point-like (`query_circle(p, 80)`) raises: pass `radius=` by name. A negative `radius` raises (`magnitude`); `0` is legal. Optional `group=` and `ignore=`.
- **`collision.query_sector(origin, angle=, radius=, spread=, group=, ignore=)`** — identities overlapping a circular sector. The origin is positional; the rest is by name. `angle=` is degrees (0 = +x, CCW) and defaults to a Graphic origin's `.angle` (Sprite world heading — `art_angle` and flips are already in it; do not add `art_angle` again). A plain position without `angle=` raises. `radius=` is the reach. `spread=` is the full opening in degrees (`60` means ±30). `0` is the center segment and returns every hit along it. `360` is `query_circle`. Above 360 raises. A negative `radius` or `spread` raises; `0` is legal. Hits are overlap, in candidate order — no distance sort. The sector is convex wedges of at most 90°, each a polygon whose chords stay within 0.25 design units of the arc (at most 64 chords per wedge). Draw the same wedge: `Circle(center=, radius=, angle=, spread=)` (`use_center` defaults to that pie; `False` is the chord segment). Closest body: `nearest(guard, collision.query_sector(...))`. Line of sight is a second query, not a knob on this one:

```python
seen = collision.query_sector(guard, radius=300, spread=60, group="enemies")
visible = [e for e in seen if collision.raycast(guard, p2=e, group="walls") is None]
```

- **`test_collision(a, b) -> Optional[CollisionInfo]`**
- **`collision.query_shape(shape, group=)`** — `group=` as above. The probe is not a hit against itself or its own parts. Like the other queries it rejects a candidate whose (fresh) proxy box misses the probe's before building world prims (`_QUERY_SHAPE_REJECT`; inclusive, and proxies contain their prims, so a touching pair still reaches the narrow phase). Before 2026-10-12 it built prims for every candidate (games.md B3; `tests/test_query_shape_reject.py`).
- **`entity.collides_with(group=)`** — sugar for `query_shape(self, group=)`.

`collision.raycast(p1, ...)` — sensor-style cast. The start is positional. The end is exactly one of `p2=` (a point-like), `vec=` (a displacement: Vec2 or `(dx, dy)`; a Point, Graphic, or mouse raises), or `length=` with optional `angle=` (degrees). `angle=` omitted uses the caster's `.angle`; a plain position then requires `angle=`. A positional second argument raises. Mixing end forms raises. A negative `length` raises.

`group=` is the same grammar as `query_shape`. The caster rule and `ignore=` are as above. The destination is not skipped unless it is the caster or named in `ignore=` — a clean shot at `enemy` reports `enemy`. Something in between:

```python
collision.raycast(hero, p2=enemy, ignore=enemy)          # any other body
collision.raycast(hero, p2=enemy, group="walls")         # walls only
```

A ray that starts inside a circle returns `t == 0` (the caster itself no longer does). OBB, ellipse, and convex polygons are analytic; a non-convex polygon samples about one sample per design unit. Standing `resolve()` already sweeps, and so does detection for a fast `move_by` body ([Swept detection](#swept-detection-fast-bodies)); this recipe is for movers driven by placement (`center =`, `@=`, tween), for geometry the linear sweep does not cover (fast rotation), and for code that needs the hit inside `update()`. Cast from last position to current and treat a hit as the puncture:

```python
def update(dt):
    prev = bullet.center
    bullet.move_by(bullet.vel.x * dt, bullet.vel.y * dt)
    hit = collision.raycast(prev, p2=bullet.center, group="walls", ignore=bullet)
    if hit:
        identity, t, point = hit
        bullet.center = point
        bullet.destroy()
```

This under-approximates for shapes with real extent (a wide, fast box can still miss a corner a single center-ray misses). For small/point-like movers it is effectively exact.

### Query fences

No `occluded_by=` and no sort option on `query_sector` — line of sight is `raycast` after the sector, and the closest body is `nearest`. No bare aliases (`query_circle`, `collision_with_circle`): the `collision.` prefix is the hitbox world, distinct from `distance` / `nearest`. No positional end on `raycast`: a `Vec2` is a point-like, so `raycast(p, vec)` would aim at a point. No auto-ignore of the destination: that body is a valid hit. Visual check: `scripts/smoke/queries.py`.

## Frame order

One detection snapshot per frame (post-`update(dt)`, pre-resolution). `@collide` handlers read that snapshot; a standing resolve pair also counts a gap up to `_CONTACT_SKIN` ([Resting contact (skin)](#resting-contact-skin)), and a fast body counts its path from the start-of-frame pose ([Swept detection](#swept-detection-fast-bodies)). Standing `resolve()` then sweeps from the start-of-frame pose. `touching_*` is indexed from the post-sweep contacts.

### Partner removed by a handler (ghost contact)

**A resolve partner a handler of this step removes is a still wall for the survivor's sweep that step: the survivor stops and bounces where a live partner would leave it; the removed body moves for nothing and is in no contact.** (PE5, 2026-10-14; a wall since 2026-10-15, G2.) Handlers run before resolve, so a brick destroyed in `@collide(ball, "brick")` was gone when the solver ran, and a `resolve(ball, "brick", bounce=1)` ball ploughed through every brick it broke. The first answer (velocity only, no pose) left the ball going on into the dead brick's space for the rest of the frame (9.9 DU at 30 Hz, 300 DU/s), and answered every removed brick the frame's original path crossed, one after another: a ball near a seam was answered by a corner it would never have reached (19° where a live pair gives −10°).

| Rule | Detail |
| --- | --- |
| When | A collider in a resolve pair leaves collision (destroy, park, `collidable = False`) while this step's enter / stay / exit handlers run (`_dispatch_current` is set only then). A body removed in `update()` made no contact this frame and leaves nothing |
| Kept | `_note_ghost_contacts`, at the top of `_end_contacts_of` while the body still has its tags and pose: for each of this frame's detection contacts with a resolve partner whose pair has a `bounce=` number — the partner, the detection `info`, the dead body's world prims, its frame motion, its mass and `.vel` |
| Applied | `_apply_ghost_contacts`, after dispatch and before `_apply_auto_resolve` (only with `resolve_enabled`), builds a `_GhostPartner` per removed body and survivor (frozen prims, mass, `.vel`, the `only=` entry; one wall even when the pair had two detection entries). `_sweep_and_slide` gets them as `ghosts`: `_earliest_toi` walks them after the partner pool (a plain sweep, the partner still), so the pool loop pays nothing. A stop at one answers like a live one, jointly with live partners at the same stop ([Joint stop](#joint-stop-simultaneous-contacts)), with the bounce sub-step: `_ghost_velocity` (`velocity_split` with its mass and velocity, written on the survivor) |
| Movable | A removed body with mass and `.vel` is not pushed; the survivor travels as if it had pushed it (its `(1 + e)` share), so an equal-mass mover still stops where it touched |
| Unreached | A removed partner the sweep did not meet (a resting-skin gap) still answers what the handler saw: `_answer_unreached`, along a short cast along the velocity (see [Resting contact](#resting-contact-skin), "Resolve") |
| Not | No push, no contact (`touching_*`), no settle, no floor snap: it is gone after this step. A survivor with no `.vel`, `STATIC`, or out of play: nothing. Position-only pairs: nothing. `only=`: the entry joins the sweep's gate (judged and marked on the removed collider), so a one-way platform a body jumps up through keeps its speed. An act change drops the list |

Why this is right for `bounce=0`: `velocity_split` changes only an approaching velocity. A hero landing on a floor that crumbles in `@collide` stops falling that frame at the slop above it, as a live floor would hold it, and falls from rest next frame; a hero jumping along a wall a handler removes keeps its jump. A handler that already reflected `.vel` (`me.vel.y = -abs(me.vel.y)`, `info.bounce_apart()`) leaves a separating velocity, so the stop answers nothing: no double bounce. Breaking in the handler, a frame later, or never gives the same path and velocity (E8, 0.00 DU apart in 40 random shots × 3 rates). Guards: `tests/test_collision.py` (`TestBounceOffAPartnerAHandlerRemoved`), `tests/test_joint_response.py` (`TestGhostWalls`, canary `_GHOST_WALLS = False`: the velocity-only response).

## Specs by body kind

- **Shape** — geometry prims from the active model.
- **Concave** — one convex `POLY` prim per piece (`_concave_prims` ← `Concave._world_pieces`): a fan of triangles under the curve from the far corner of the scoop's box, plus at most two rim strips; chords within 0.25 DU of the drawn arc. The proxy is the box. [Shapes Design — Concave](Shapes%20Design.md#concave).
- **Circle** — one `CIRCLE` prim when clamped `spread` is a full turn (omitted or `>= 360 − 1e-6`), including `radius == 0` (a point). A shorter positive opening is the filled arc: `query_sector` wedges when `use_center` (the default), or one convex chord segment when `use_center=False`. `spread` of `0` emits no prims. The broad-phase proxy stays the circumdisk. Pointer `contains_point` follows the same filled arc.
- **Sprite** — see **Sprite colliders** below.
- **Hitbox part** — `Hitbox._collision_specs()` (body locals placed by the paint transform); proxy is the body's extent box (`_hitbox_extents_for_pose`) placed by the same paint transform and padded by `hypot(offset)` (`Hitbox._proxy_aabb`), so a rebake does not build prims until something overlaps. The pose key is built in one pass (`Hitbox._pose_key`, special-cased in `_collision_pose_key`). See [Hitbox parts](#hitbox-parts).
- **SpatialFx** — domain specs (`PointDomainFx` / `PadDomainFx` / `BeamDomainFx`); `_domain_aabb` is the broad-phase proxy. Pose key includes frame size/orientation so stretch/rotate rebuilds instead of sliding a stale hull.

Every prim carries a world AABB, so non-rect geometry is AABB-filtered before detailed tests.

### Sprite colliders

A Sprite's collider is a property of the **object**, not of the current animation cell
(unless the author opts in). Fitters, mask cache, and union math live in
[Sprite Design.md — Auto hitbox](Sprite%20Design.md#auto-hitbox-shapeauto). Collision
sees the baked locals through `_collision_specs()` and a turned-extent proxy (**Proxy** below).

| Knob | Collision effect |
|------|------------------|
| `hitbox_shape=` | Which prims are baked: `"auto"` (utility) / `"rect"` (silhouette AABB) / `"ellipse"` / `"circle"` / `"hull"`. Naming a shape means cover the art (recall-first); `"auto"` is precision-first. `"rect"` is **not** an inscribed `greedy_rects` box. |
| `hitbox_source=` | Which art is baked. Default: **construct frame**. One frame = that frame; several = union of hole-filled masks, each placed where the blit draws it (clip display box), stored in the reference cell, fitted once. `"all"` = registered clips (else the construct frame). `"clip"` = the playing clip, rebake on switch only; with nothing playing the key is the construct frame, so a still `frame=` write does not rebake. `"each"` = re-fit every playhead tick, emitted through the playing clip's display box. A tuple of clip names unions just those. A catalog that no longer contains the spec falls back to the construct frame (one warning) instead of raising inside `step()`. |
| `hitbox_anchor=` | Scale-about and pin. Pin target is the alpha AABB of **this bake's frames** (`source`), not the whole sheet. Authored boxes on the reference frame replace that mask AABB. `"center"` does not translate. Presets or a finite `(ax, ay)` (y-up, not clamped; `nan` / `inf` raise). Also the `.tilt` pivot. With `"bottom"` (or `(0, -1)`) a bottom contact seats the paint along `normal`; it is not slid onto a support vertex. |
| `hitbox_scale=` | Scalar or `(sx, sy)`; getter always a pair; folded into baked locals (not emit). |

#### Axis-aligned hulls

A hull whose four vertices are exactly the corners of its bounding box (an opaque
tile, unrotated; flips, scale and quarter turns keep it so) is emitted as an
**`AABB` prim**, as an unrotated `Rect` is (`_prims_from_collision_specs`,
`_is_axis_rect`, tolerance 1e-9 of the coordinate scale). Any other angle keeps
the `POLY`. Same geometry: contacts agree with the `POLY` within 1e-4 (normal,
depth, points), and a sweep takes the closed-form `_toi_fast` instead of GJK
conservative advancement, which stops up to ~0.04 DU earlier: the AABB answer is
the exact one. Level tiles are image Sprites, so every walker-vs-tile sweep went
to GJK before this (ninja: work 8.3 → 5.7 ms, [games.md](../scripts/bench/games.md),
D2). `_HULL_AABB = False` keeps the `POLY` (oracle; prims are cached, so A/B it per
process: `game_bench.py --set scena.collision:_HULL_AABB=False`). Tests:
`tests/test_hull_aabb.py` (prim kinds equal within tolerance against every kind,
sprite kinds per pose, walkers on tiles agree frame by frame, a wrong box is
caught). The spec stays `"poly"`: only the prim kind changes.

**Freeze.** Bake on collision enroll. `_sync_auto_hitbox_frame` rebakes for
`hitbox_source="each"` (every cell) and `"clip"` (when the clip changes, not every
tick). Other `play()` / playhead ticks do not rebake and do not change the emitted
prim sizes. `"auto"` plus `"each"` / `"clip"` runs the utility competition once
per reference set, then refits that kind only. A locked `"boxes"` refit still
prefers that cell's authored boxes over the greedy fitter. Explicit
`"circle"` / `"ellipse"` / `"hull"` / `"rect"` ignore authored boxes.

**Hurtbox.** Keep the walker rect on the sprite (the body). A per-frame
silhouette is a hitbox part: `hero.add_hitbox(group="hurt")`, then
`@collide("bullet", "hurt")`. Resolve stays on the body; `show_colliders`
draws the part cyan. See [Hitbox parts](#hitbox-parts).

### Main hitbox switch

Every Graphic's collider is its **main hitbox** (`g.hitbox`, a `Hitbox` view —
[Sprite Design.md — Hitboxes: one type](Sprite%20Design.md#hitboxes-one-type)).
`g.hitbox.active = False` sets `_main_hitbox_off` on the host and bumps its
collision epoch. The engine reads the flag in exactly two places:
`_snapshot_shape_uncached` returns `[]` and `_proxy_aabb_for_shape` returns
`None`, so `_update_proxy` finds no prims and marks the proxy invalid. Every
consumer already skips an invalid proxy — broad phase (exits fire), unnamed
queries, `resolve` sweep / settle / snap (no prims), `touching_*` (no
contacts), `floor_below` (no prims → `None`). Parts are separate colliders and
keep detecting. `hitbox.box` measures with `include_off=True`. Do not add a
third check elsewhere: an invalid proxy is the one mechanism.
Tests: `tests/test_hitbox_model.py` (`TestMainActive`).

### Hitbox parts

Author contract: [Sprite Design.md — Hitbox parts](Sprite%20Design.md#hitbox-parts).
Engine shape: a part's collider is `Collider([hitbox], _identity_shape=host,
_bind=False)` with `_part` set (`_ensure_part_collider`). Identity is the host,
so handlers and `CollisionInfo.a` / `.b` report the Sprite; `_oriented_info`
fills `a_hitbox` / `b_hitbox`. The `Hitbox` quacks like a shape
(`node_id`, `layer`, `group` = its claims, `_collision_opt_out`,
`_collision_epoch` = host + own, `_collision_pose_extra` with tilt / seat), so
proxy, snapshot, and prune paths need no special case beyond the specs branch.

| Rule | Where |
|------|-------|
| A claimed tag enrolls the part, not the body | `_tag_item` in `_try_enroll_item` (every enroll path funnels there) and `notify_group_remove`; body `group_tags()` subtracts claims |
| Naming the Sprite / `ANYTHING` / `on_collide*` = body | `_collider_on_side` (part: only its tags and its `Hitbox`), `_resolve_target_to_colliders(ANYTHING)` bodies only, broad-phase ANYTHING skips parts, `_dispatch` collider-level callbacks skip part partners |
| A sprite never pairs with its own parts | `_declared_broad_pairs` owner check (only when a part is registered) |
| Parts never resolve | `_refuse_part_resolve_side` (a `Hitbox` side in `resolve()`, `add_resolve_pair`, `resolve_now`); `CollisionInfo._refuse_part_resolution`; `_collider_on_resolve_side` is False for parts |
| `resolve` on a claimed group moves bodies | `_claimed_bodies[tag]` / `_claimed_body_index[tag]` hold host bodies when a part answers a **resolve-side** tag (`_enroll_claimed_body` from `_try_enroll_item`; cleaned by `notify_group_remove`, `_forget_collider_tags`, `remove_resolve_pair`, refresh). Every resolve path reads `_resolve_side_colliders` / `_collider_on_resolve_side` / `_resolve_pair_matches` (auto-resolve bodies, partners, bounce token, `_in_resolve`, broad-phase resolve pairs, pair-target pruning, ANYTHING interest); `resolve_now` reads `_resolve_now_colliders` (part → host body even off resolve sides). Fast path: a tag with no claimed bodies returns `_tag_colliders[tag]` unchanged |
| `touching_*` stays the body's | `_update_touching_state` skips part colliders (same identity would wipe it) |
| Lifetime | `forget_destroyed_item` fires exits for parts, then drops them; `collidable = False` / park → `Sprite._retire_hitbox_parts`; a registering part also registers the body. Dropping an object-literal / `@collide_with` / `resolve` pair on destroy also strips the dead identity from every survivor's `_pair_targets` (`_forget_pair_target`) — otherwise `@collide_with("wall")` bullets pile up on the wall forever (system-test finding S6: leak + a broad phase that grows) |
| No-group queries = bodies | `_refresh_live_colliders(bodies_only=True)` via `_candidates_for_group(None)` / `ANYTHING`. A **named** `group=` walks that group's members (a claimed tag routes to the part) and does not enroll. A Graphic origin is the caster and is skipped (its parts too). `ignore=` adds a body, a tag, or a live group; a tag matches the host, so its parts drop too |
| Linked `active` (`hb["active"] @= fn`) | A polled link, not a graph edge. `step()` calls `hitbox._refresh_linked_parts()` right after `_prune_dead()`, before the proxies, so collision sees the value after `update` / `on_update` / `play()`. Every query polls the links first (`_candidates_for_group` calls `_refresh_linked_parts()` when `_LINKED_PARTS` is not empty): a query in `update()` after the formula changed used to hit a hitbox it had turned off when the tag was declared, for `ANYTHING`, and always for the main hitbox (review 2026-10-09 W-G2). The index is the module-level WeakSet `hitbox._LINKED_PARTS` (it survives `reset_collision_system()`); dead parts leave it in `forget_destroyed_item` and in the refresh loop. Skipped while the host is parked or opted out. Changes go through `Hitbox._apply_active` (enter / exit as a write). No links: one empty-set check per step ([Sprite Design — round 2](Sprite%20Design.md#pixel-shapes-and-linked-active-round-2)) |
| `px_rect` / `px_circle` parts | Baked per cell geometry (`src_w`, `src_h`, pivot) against the pivot-applied cell; the part epoch bumps only when that geometry changes, so a clip of same-size cells keeps the pose cache. Emit, proxy and paint placement are the art path's |

Cost with parts (`scripts/bench/perf_hitbox_parts.py`, 2026-09-27, this machine): about **11–12 µs per part per `step()`** — the upkeep of a second collider per sprite (pose key with tilt / seat, frame sync, proxy). 100 animated walkers each with a `"each"` silhouette part: body-only 0.78 ms → with parts 1.94 ms per step (+1.16 ms here, ~4.6 ms on the target ×4); 20 walkers: +0.26 ms (~1 ms target). The cheap proxy cut prim builds from ~21.6 to ~2.2 per step (100 walkers at 12 fps) but not much time: the cost is per-collider upkeep, not bakes. A further cut would share the host body's per-step pose work with its parts (not done).

Cost when no part exists: one `any(c._part …)` per `step()` in the broad
phase; `_hitbox_claims` / `_hitbox_parts` are Entity class defaults so probes
on Shapes never fall into `Entity.__getattr__` (that miss raised per item and
showed up in `perf_collision_shooter.py` refresh).

**World mapping.** Locals are fractions of the reference cell. Specs and the proxy
multiply by `_hitbox_pose_wh()` (that cell's size-intent box × pose `scale`), **not**
the current blit `width`×`height`. `play()` may retarget the drawn sprite when clip
cells differ in aspect; the collider stays put. `"each"` rebakes and refreshes the
ref, so it tracks the current cell. A source circle (`nr = r / src_w`) stays a
circle when the design box matches the cell aspect. `width=` and `height=`
stretch turns it into an ellipse aligned with that box (near-equal axes, ratio
≤ 1.08, stay a circle). A rotated ellipse's local AABB uses that pose aspect.
An empty bake (`hitbox_shape="circle"`) emits an inscribed circle of the design box;
`hull` / `auto` / `rect` keep the design-box AABB.

**Proxy.** Per-axis local extents `(ex, ey)` (fractions of the hitbox pose box),
turned by `_draw_angle()`: the proxy is the AABB of the box `(ex·w, ey·h)` rotated to
the heading, plus `hypot(offset)`. It is closed-form under spin (no prim rebuild) and
never tighter than the exact prim union. Each extent holds what `_collision_specs`
emits **and** that prim's own AABB: a circle contributes `nr` on x and
`nr · src_w / src_h` on y; a near-square pair that emits as a circle uses the mean
radius `ellipse_as_circle` returns (wider than the short axis); an ellipse uses the
AABB of its turned box, the same box its prim AABB carries. Those bounds depend on the
pose aspect, so extents remember the pose box they were built for and rebuild when it
changes. The turned box is never wider than the old `hypot(ex·w, ey·h)` disk (equal
only for square extents at 45°); a thin bolt axis-aligned is its own box.
`TestProxyAabbConservative` is the gate: kind × anchor × scale, and rotation × flip ×
offset × scale over a mixed bake, plus the near-circle and pose-aspect cases. Do not
change `hitbox_shape="auto"` to “always circle” to win a bench. Auto is precision on
contact, and the prim kind is rarely the cost: forcing circles on every Graphic
(2026-09, M4) left a rotating 180-body mix unchanged (2.7 ms collision, all of it
pose keys) and took 0.43 ms off a cross-tag `@collide_stay` mix whose 5.5 ms were
mostly the Python broad phase.

Unswept recovery does not use the proxy. The box past the hitbox is not a
floor, a ceiling, or a wall. See [Unswept bounds](#unswept-bounds).

**Walkers.** Teach `hitbox_shape="rect"` — an ellipse or hull is a poor standing bottom
(one contact point, slanted SAT faces feeding `slope_angle`). Taught recipe:

```python
Sprite(..., hitbox_shape="rect", hitbox_source="all", hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0))
```

Lean the art with `sprite.tilt = "ground"` (or the explicit `tilt = 0` + `tilt = c` loop — see **Ramps**), not `.angle`. Do not Y-scale the hitbox from tilt.

`hitbox_source="each"` (and a `"clip"` rebake) can still change the box between steps. If that box crosses into a previously clear partner, [Unswept bounds](#unswept-bounds) puts it back on the face it crossed. That does not stop `"bottom"` from flickering as cells change, and it does not make `"each"` the walker solid. The recipe above stays `hitbox_source="all"`.

`"auto"` stays the beginner default for space-game art. `clone()` copies all four knobs.
`Svg` accepts them (`"all"` / `"each"` / `"clip"` are degenerate).

## Parallax invariant

Layers with a non-neutral camera response are decoration only. Collidable / interactive content must not land on them (`ParallaxLayerError`). Hit-testing and collision operate in world space under the global camera. See [Canvas Design.md](Canvas%20Design.md).

# Resolve hot path

How standing `resolve()` stays cheap when tens of bodies share a tag (`resolve("ball", "ball")`, volleys). **Behaviour is the same** as [Resolution](#resolution); this is partner/cull bookkeeping, not a different solver. Author API unchanged. Current numbers: [scripts/bench/resolve.md](../scripts/bench/resolve.md) (`run_resolve.py` pulse).

Why it exists: 40 balls under `resolve("ball", "wall")` + `resolve("ball", "ball")` cost 13.2 ms of collision per frame on an M4 (2026-09-04; target machines are ~4× slower), 82% of it resolve, growing ~O(n²). Settle ran an exact test against every partner (hundreds of times more tests than real overlaps), partners came from an n×n walk, and every test rebuilt a pose key even on a cache hit. The rules below brought it to 1.5 ms (50 platformer shots: 39.8 → 4.9 ms). Beginners write mutual pools; the engine absorbs the cost instead of asking authors to drop `ball×ball`.

`@collide`-only scenes (Galaga) still skip `_apply_auto_resolve` entirely.

## Partners

`_resolve_partners` walks **declared sides**, not `self._colliders`.

| Side | Partners of a body on that side |
| --- | --- |
| String tag / live `group["name"]` | `_resolve_side_colliders(tag)`: `_tag_colliders[tag]` (the incremental enroll index), with a claiming part swapped for its host body (`_claimed_bodies`) |
| Self-paired tag (`resolve("ball", "ball")`) | the other members of that list (skip self) |
| `ANYTHING` | every enrolled **body** collider (hitbox parts excluded) |
| Object / `Collider` literal | that identity (a Sprite means its body) |

Formula groups (`group["name"] @=`) are **not** a collision tag: `_pair_tag_of` keys on
`_group_id`, so they fall through like snapshots (decoration-time membership). Prefer
the source tag strings in `@collide` / `resolve`.

`_collider_on_side` / `_pair_matches` is tag-index membership (`id` in `_tag_index[tag]`) for string sides — not `set(_resolve_target_to_colliders(tag))` per pair. List/tuple OR is still expanded at `resolve()` into separate registrations; first matching registration wins the bounce token (same as before).

The partner **list** for a ball in a 40-ball pool is the other 39 balls plus walls named in `resolve("ball", "wall")`. It is **not** pre-filtered to overlapping AABBs — floor snap must still see a floor that is 16 DU below the body. Overlap culling is per operation:

| Pass | Cull |
| --- | --- |
| Sweep / TOI | swept proxy AABB vs partner (start ∪ end when the partner moved), compared inline — no per-partner box tuples |
| Settle | **current** proxy AABB; skip the body when nothing overlaps |
| Unswept bounds | **current** proxy AABB, then the stored boxes (`_resolved_aabb`, must have been clear), then current **prim** AABBs, then the prims themselves. The proxy is only a reject: prims sit inside it, so a disjoint proxy pair cannot pass the prim test. The decision is never made on the proxy or on a rotated body's bounding box alone |
| Floor snap | no current-overlap cull (snap volume is the search) |

Partner **identities** `(collider, bounce_token)` are cached across frames in `_partner_ident_cache` (and, with the same lifetime, the `only=` map in `_partner_only_cache` — never in the partner tuple; see [One-way pairs](#one-way-pairs-only)). Each `_resolve_partners` call reuses that list and only refreshes `(motion_dx, motion_dy)`. The cache is not cleared every `step()`. It is cleared **only by an event that can change some list** (`_PARTNER_CACHE_SELECTIVE`; False clears it on every enroll and tag change, the old rule): a member joining or leaving a tag that is a side of some `resolve()` pair (`_tag_add` / `_tag_remove` / claimed bodies → `_partner_cache_touched_by_tag`), or any tag while a side is a formula group (`group["x"] @= …` reads other groups' tags: a retag moves a body in or out of it with no enroll; the selective rule missed it, review 2026-10-12); an enroll or leave while some side expands by identity (`ANYTHING`, an object, a part, a snapshot group: `_invalidate_partner_cache_for_enroll`); and every pair edit (`resolve` / `unresolve`, act pair drops). A leaving collider's own entry is always dropped (`_forget_partner_entry`: a reused `id()` must not inherit it). A bullet whose tags are only in `@collide` pairs enrolls and leaves without touching any list. Before, every such enroll made every body of a mutual pool rebuild its O(n) list next frame (horda, [games.md](../scripts/bench/games.md) D4: resolve −12 %). The step's `ANYTHING` / object expansions (`_resolve_cache`) are cleared on enroll as well as on leave: a list rebuilt from a stale expansion outlives the frame (PF1 in [Testing Design](Testing%20Design.md#pf--performance-campaign-2026-10-12)). Guard: `tests/test_partner_cache.py` (random joins, leaves, retags and pair edits on every side kind; cached lists equal a fresh build, in order).

`_apply_auto_resolve` builds its movable-body list from declared resolve sides (`_handler_colliders` on each registration), not a scan of every enrolled collider. Static-mass members still seed `grounded_at_start` but are not swept.

Do not feed settle’s current-overlap set into floor snap. Do not scan every enrolled collider to discover partners.

Every pass above walks the **whole** partner list — 53 partners per shot in the 50-shot platformer. A pass must reject on stored numbers (proxy, `_resolved_aabb`) before it builds anything per partner: world prims, prim bounds, or a fresh box tuple. Unswept recovery computes the body's own prim bounds once per call and recomputes them only after a pull moves it. Building prim bounds for every partner is what took the platformer from 3.0 to 8.6 ms `coll_ms` (2026-09-24, [resolve.md](../scripts/bench/resolve.md)).

## Floor snap early-out

`_record_solve_contact` maintains per-pair contact sides and a per-body **bottom refcount** (`_solve_bottom_count`). When sweep or settle already recorded a `"bottom"` contact for a body, `_floor_snap` returns in O(1) instead of scanning `_solve_contacts` (which grew O(N) per grounded body in a resting pile). Cleared each `step()` with the contact map. Semantics unchanged: snap still runs when the body was grounded at frame start and has no bottom contact yet this frame.

## Broad phase

`_declared_broad_pairs` still crosses `@collide` + `resolve` + `ANYTHING` only (no all-collider matrix).

- Swept proxy boxes (start-of-frame ∪ end) are built **once** per `step()` into a numpy array; pair tests read that array. Rows are widened for resolve bodies and for this frame's fast colliders ([Swept detection](#swept-detection-fast-bodies)); every other row is the end-pose proxy.
- Self-paired tags iterate `i < j` once (not n×n with a `seen` set).
- Pools of 8+ (and `ANYTHING` vs many) use a vectorized AABB test on that array; small pools stay in Python. Cross-tag pools of 8+ on both sides use the same numpy AABB as self-paired tags.
- Duplicate declarations (`@collide` and `resolve` on the same tags) still canonicalise `(lo, hi)`.

Detection narrow-phase is unchanged: world prims only for those overlapping pairs.

## World prims / pose keys

`_world_prims` still rebuilds from live pose for detection, queries, and `test_collision` (so a write in `update()` is visible before the next `step()`).

**Pose keys are built from Defining inputs.** A kind's `_collision_pose_extra`
must cover every input its prims read, via cold helpers (`_oriented_frame`,
`_radius_value`, `_segment_xy`, vertex offsets). The generic extra reads slot
values from `__dict__`, which are stale for cold Derivates: a key that relies
on warm Derivates bumping `_collision_epoch` is wrong the moment the shape stays
cold (R7 in [Testing Design](Testing%20Design.md#bug-catalogue)). Never trim an
extra "because rotation already bumps the epoch": a Defining slot write often does
not bump it.

**Pose revision.** A body whose pose did not change keeps its proxy without a
pose key (`_POSE_REV_SKIP`). Every write that can change what a trusted body's
key bumps its root's revision (`state.bump_pose_rev`; read with
`state.pose_rev`). The revision is a one-element list in the root's `__dict__`
(`_pose_cell`), and every part caches a reference to it, so a bump is one dict
get and an increment. The three hottest funnels inline it. Measured write tax
(M4, interleaved against the previous tree): `move_by` +50 ns (+4 %), a slot
write (`width =`) +40 ns (+3 %), `center =` +1–3 %. No frame-level change in
horda, where every body moves every frame.

The bumps sit in these funnels:
- `Container._write_field` (both stores; not author ink);
- `Container._takein`, and the overrides that store without it:
  `Point._takein_impl` and `Vec2._takein_impl` on a part (`center =`, `<<`,
  `rect.vec =`, part writes);
- `_takein_xy_float` (the A1 float moves);
- the link-pull store (`ScalarAnchor`);
- `_bump_collision_epoch` (rotation, scale, the Sprite size / frame / offset /
  art-angle / hitbox setters, the main hitbox's setters through its host);
- the flip stores and `_clone_pose_from`;
- the Sprite's lazy auto-bake (`_ensure_auto_baked`: the hitbox reference size
  the key reads, the hull the tilt pivot reads), `tilt =` and `shield_scale =`
  (draw-box inputs: the cull cache shares the revision);
- link, anchor and pull-owner changes (`_invalidate_bare_reads`,
  `_ensure_scalar_anchor`, `_drop_scalar_anchor`).

Trusted (`_pose_rev_of`):
- **Kinds**: plain Sprites, Rect / Square, Circle and Ellipse, and their
  subclasses that keep the kind's pose hooks (`_pose_rev_kind`, cached on the
  class).
- **State**: no link, anchor or pull owner on the body or its Defining parts
  (a linked value changes on a pull, with no write), and no
  `hitbox_source="each"`. Cached per revision, because links and anchors bump
  when they come or go.

Everything else builds its key every time, as before: Text, Track, SpatialFx,
hitbox parts, Polygons, Lines.

`_update_proxy` stores the shapes' revisions next to the key (`_proxy_revs`).
A solver nudge shifts the stored key and may keep the new revisions only if
the stored key was the pose just before the move. A shape two bodies share
(a piece of a compound body) may have been moved by the other body's nudge.
If it was, the shifted key is not the pose and the next refresh builds it.
The first draft missed this; the verify mode below caught it.

**Verify mode.** `SCENA_VERIFY_POSE_REV=1` (`_POSE_REV_VERIFY`) makes every
skip also build the key and raise when they disagree. `tests/run_tiers.py`
turns it on for every tier, so a pose writer that forgets the bump fails any
test that moves that kind of body.
- Its first run found three gaps: `Point` overrides `_takein` (center writes
  bypassed the funnel), the nudge rule above, and slot-only `Hitbox` objects
  (the bump forwards to the host).
- It only sees what a test exercises. The 2026-10-12 review found two more
  writers no test reached: `Vec2._takein` (a `Rect(p1=, vec=)` resized by
  `vec =` kept its hull) and the lazy bake (enrolled on a later clip). An
  override of `_takein` / `_takein_impl` that stores a pose input bumps.
- Kinds and fast keys are cached on the class (`_pose_rev_kind`,
  `_sprite_pose_fast_class`): a pose hook patched onto a class after its first
  key is not seen.
- `SCENA_VERIFY_POSE_REV=0` measures the real skip.

Measured (in-process A/B, `game_bench.py --ab scena.collision:_POSE_REV_SKIP`):
- ninja 5.2 → 4.5 ms;
- mundo 103 → 63 ms (`floor_below` 65 → 28 ms);
- corrida 3.1 → 2.6 ms;
- horda unchanged.

Tests: `tests/test_pose_rev.py`:
- random public pose operations on every trusted kind: a revision that did
  not move means a key that did not move;
- trust is refused for links, Text and `each`;
- a still body builds no key;
- canaries: the A1 funnel without its bump is caught (and so is a disabled
  bump in state or entity).

A new pose writer bumps, or the kind leaves the trusted list.

**Moved set and vectorized candidates.** A query between two steps needs
fresh proxies for its candidates. Refreshing every candidate was O(group)
Python per call (mundo: ~35,000 `_update_proxy` a frame from 21
`floor_below`). Now:
- **Moved set.** A revision cell is `[rev, dirty, weakref(root)]`. The first
  bump since the last drain appends it to `state.DIRTY_POSE_CELLS` (one branch
  on the write path). `_drain_pose_cells` turns those into `_stale` colliders,
  the root's body and its hitbox parts. `step()` drains just before its
  snapshot, after the prune and the linked hitbox refresh: an exit handler the
  prune fires and a linked `active` write poses too, and drained at the top
  their bodies were seen a step late (review 2026-10-12). The list is bounded
  by the roots that moved in a frame; a program that never steps keeps one
  cell per moved root.
- **Fresh proxies.** `_fresh_proxies` refreshes only `_stale`, `_untrusted`
  (bodies whose last refresh found no trusted revision: links, Text, parts,
  Polygons, an invalid proxy), `_timed` (a `"clip"` hitbox: time alone can end
  a clip and rebake it, with no write), `_unbound` and compound bodies. Every
  other registered proxy already matches its pose (the B1 invariant).
- **Unbound colliders.** The drain reaches a body through `root._collider`.
  `Collider([shape])` on a shape already enrolled takes its `_collider` and
  leaves the implicit collider registered (both answer): that one is in
  `_unbound`, refreshed by every query and step. Missing it, an `@collide`
  of the shape's tag never fired after a move (review 2026-10-12).
- **Scoped to the query.** A query passes its members' ids (the group's,
  cached with its rows, or the resolve pool's). Only those are refreshed;
  other moved bodies stay in `_stale` for the query that reads them, and
  `step()` refreshes every proxy anyway. In mundo the 500 tweened coins
  were refreshed by the first `floor_below` of every frame: `_fresh_proxies`
  2.1 → 0.4 ms, `floor_below` 5.1 → 3.3 ms
  (`test_query_vector.TestScopedRefresh`).
- **Box mirror.** `_box_array` is a numpy `(n, 10)` column-major mirror,
  row = `_colliders` index (`_mirror_row`):
  - the proxy;
  - this frame's motion;
  - the box over the frame (start and end proxy), built with the same
    arithmetic as `_earliest_toi`'s partner reject.

  It is rebuilt when the collider list changes (`_struct_version`).
  Otherwise the rows of `_row_dirty` colliders are synced before use: a
  proxy translated, rebuilt or nudged, or a motion changed
  (`_commit_pending_motion`). An invalid proxy is an infinite box: always a
  candidate. `_rows_meeting` masks whole columns for a large pool and copies
  rows for a small one.
- **Group rows.** `_group_rows(group)` gives a group's candidates (the same
  list, in the same order, as `_candidates_for_group`) and their row indices,
  cached per `(_struct_version, _tag_version)`. Only for groups made of
  declared pair tags with no group formula; any other group walks as before.
- **Query.** `_candidates_in_box` masks the group's rows against the query box
  in numpy. A Python loop costs 37 ns per row; numpy costs ~3 µs plus 1.6 ns per
  row, so it wins above ~100 rows.

Used by `floor_below(group=)` (`_floor_pool_near`, the march envelope as the
box). When the group has ground but none is near, the march still runs with no
partners, as the walk did (its debug end pose). `_QUERY_VECTOR = False` is the
walk (oracle).

Verify mode also re-walks the group and raises if the index missed a near
body.

**Resolve pools.** A body's resolve partners are scanned several times a
frame: each sweep slide's casts, the unswept-bounds recovery, up to four
settle passes, the floor snap, and `floor_below()` without `group=`. Each
scan was O(pool) Python: 21 walkers × 1500 tiles in mundo, 150 × 180 in
horda's mutual crowd.

- **The pool.** With at least `_POOL_VECTOR_MIN` (128) partners,
  `_resolve_pool` returns a `_PartnerPool`: the cached identity list, its
  mirror rows (cached per list and `_struct_version`), and 4-tuples built
  only for the rows a scan keeps. Below that, Python is as fast and the
  plain list is used.
- **Each scan prefilters with its own test, then runs that test.**
  - `_earliest_toi` uses `near_swept` (columns 6–9, the box over the frame).
  - The recovery and settle passes use `_iter_near`, `near_box` against the
    body's proxy, in partner order. When the body moves under the pass (the
    recovery nudges it), `_iter_near` asks again for later positions only.
  - The sweep's idle test reads the motion columns (`moves`). The seam
    step's motionless casts use `as_still`.
- **Why the prefilter cannot drop a partner.** During one body's passes
  only that body and the partner being handled are nudged, and both mark
  their rows.
- **`floor_below()` without `group=`** runs `_fresh_proxies`, then keeps
  the pool's rows that meet the march envelope (`_floor_pool_from_partners`).
  It no longer refreshes every partner. `floor_below(group=)` fills the
  `only=` cache through `_resolve_partner_idents`, without building the
  1500 tuples.

`_RESOLVE_VECTOR = False` is the Python scan (oracle). Verify mode checks
every prefilter against the Python test over the whole pool.

Measured (in-process A/B, M4):

| Game | Resolve (ms) | Work (ms) |
|---|---|---|
| mundo | 11.3 → 4.0 | 38.5 → 30.6 |
| horda | 10.5 → 7.0 | 16.8 → 13.2 |
| ninja (pools under 128) | unchanged | unchanged |

Tests: `tests/test_resolve_vector.py`:
- walkers on static tiles with one-way platforms and a moving lift, and a
  mutual crowd with walls and spawn churn, run frame by frame both ways and
  agree exactly;
- a canary keeps the mirror stale, and it is caught.

**Shared partner lists (2026-10-12; `_SHARED_PARTNERS`).** In a crowd under
`resolve("e", "e")`, every enemy has the same partners but for itself. Each
enemy that spawned or died dropped every body's list (a join to a resolve
tag), and every body rebuilt its own: O(n) per body, O(n²) a frame, half of
horda's resolve. The mirror rows of each list were rebuilt every frame too:
bullets change the collider list.

- **One list per signature.** The resolve pass reads one list per signature
  (`_partner_signature`: the body's on-side flags per registration, cached
  per body), built once per invalidation (`_shared_partners`). It is shared
  with every body of that signature and holds them all. `_PartnerPool.owner`
  is the reading body's position, and every view skips it, so a view is the
  per-body list in the same order.
- **Rows, members and the `only=` map** belong to the shared list
  (`_resolve_only_map`).
- **`only=` conflicts** are recorded per partner while building and raised
  by the body that reads the list, about any partner but itself, as the
  per-body build raised them.
- **Per-body lists remain** (`_resolve_partner_idents`) for `floor_below`
  and the API (`_resolve_partners`). Both caches drop together
  (`_invalidate_partner_cache`).

**One query per turn (2026-10-12; `_LOCAL_PREFILTER`).** A body's resolve turn
asked numpy three or four times: each sweep cast, the unswept recovery, each
settle pass, and the idle test. Each call cost ~4 µs whatever the pool size.
`_PartnerPool.localize` asks once, at the start of the turn: the partners
whose frame box meets the body's frame box padded by `_LOCAL_PAD` (8 DU).
- **Later queries** whose box fits inside read that list. One that does not
  (a long slide, a seam step) asks numpy as before.
- **The idle test (`moves`)** reads the local list. A far mover changes
  nothing the idle sweep would find, since the body's prims sit inside the
  local box.
- **Exact:** during the turn only the body and the partner being handled
  move, and that partner already passed a test, so it is in the list. Every
  pass still runs its own exact test, and verify mode checks each prefilter
  against the whole pool.

Measured on horda (in-process A/B, M4, resolve / work ms):

| Step | n=150 | n=400 |
|---|---|---|
| Shared lists | 7.9 → 6.4 / 13.9 → 12.0 | 87 → 20 / 126 → 36 |
| One query per turn | 6.1 → 3.9 / 11.6 → 9.3 | 40 → 26 |

Tests:
- `tests/test_partner_cache.py`: every body's shared view (as a pool and as
  a list) and `only=` map equal a fresh per-body build, in order, over
  random joins, leaves, retags and pair edits. A canary keeps shared lists
  past a change.
- `tests/test_resolve_vector.py`: `SameFramesShared` and `SameFramesLocal`
  run the worlds both ways and agree bit for bit.

The broad-phase fence holds: these are per-pool prefilters of the declared
pairs, not a spatial index.

Measured (in-process A/B):
- mundo: `floor_below` 28 → 6.9 ms, frame 63 → 39 ms;
- corrida: 0.47 → 0.29 ms;
- ninja (91 tiles): unchanged, since the march's casts dominate there.

Tests: `tests/test_query_vector.py`:
- random worlds of declared-tag ground (Sprites, Rects, Circles, Polygons,
  linked Rects) are mutated between queries (moves, placement, resize, links,
  enroll, destroy, retag), and the index answers like the walk, end pose
  included;
- the index is queried first, because the walk refreshes what it touches and
  would hide a lost move;
- a canary drops the moved set, and it is caught.

**Step cost: still bodies are skipped (2026-10-12).** Three per-collider
walks in `step()` now visit only the colliders whose answer can have changed.
`_STEP_SKIP_STILL = False` restores the full walks (oracle, A/B).

- **Snapshot** (`_snapshot_moved`). The visit set is:
  - moved (`_stale`);
  - motion to commit or to reset (`_snap_hot`: filled by
    `note_collider_motion` / `note_collider_path`, and by any commit that
    leaves motion, a path or a swept start);
  - `_untrusted` (which now also takes a collider whose nudge was refused,
    so its revisions were cleared);
  - `_timed` (a `"clip"` hitbox source rebakes when time ends a clip);
  - `_unbound` (registered, no revision cell reaches it);
  - compound bodies.

  Visits run in collider order. `live` is every valid proxy. Every other
  collider matches its pose (the revision invariant) and has nothing to
  commit. Verify mode refreshes the skipped ones too and raises if one
  changed.
- **Stored bounds** (`_store_resolved_aabbs`). A resolve collider keeps
  `_resolved_aabb` while `_proxy_key` is the same object (`_resolved_key`):
  every pose change and every nudge assigns a new key.
- **Touching publish** (`_update_touching_state`). It writes only bodies
  that touch now, plus those that touched at the last publish
  (`_touching_live`), in collider order. Every other body already reads
  empty, and writing empty again changes nothing.

A leaving collider is dropped from every one of these sets
(`_forget_step_sets`): the holders guard (`test_sys_holders`) found
`_touching_live` still holding a body after an act change.

Measured (in-process A/B, M4):

| Game | Work (ms) | Detail |
|---|---|---|
| mundo | 29.4 → 24.1 | snapshot 3.5 → 2.0 (the 500 tweened coins still move); bounds 1.6 → 0.2 |
| ninja | 3.04 → 2.82 | |
| corrida | 2.19 → 1.93 | |
| horda | 14.0 → 13.6 | |

Tests: `tests/test_step_skip.py`:
- random scenes run frame by frame both ways and agree (positions, sides,
  contacts, stored bounds, the order of `touching_sides` changes);
- per-step invariants: stored bounds equal fresh ones, and an unvisited body
  reads no contact;
- canaries keep bounds past a move, or forget a toucher.

Suite-wide, verify mode covers the snapshot.

**Sprite fast key.** A Sprite whose class keeps Sprite's own pose hooks
(`_SPRITE_POSE_HOOKS`; checked once per class, cached on the class as
`_scena_pose_key_fast`) builds its key from its fields (`_sprite_pose_key_fast`).
It does this only where each field read would return the stored value anyway
(`_raw_bare_scalar`: no anchor on the owner, no link, the field already
classified bare, a plain number). In every other state it answers None and the
generic key runs: a linked `width`, `center` or `angle`, `hitbox_source="each"`
while playing, any anchor on the sprite. **The tuple is identical** to the
generic one; that equality is the test (`tests/test_sprite_pose_key_fast.py`:
random poses, flips, offsets, clips with each `hitbox_source`, linked fields;
dropped-input mutations are caught). It is about 2× faster (1.85 → 0.94 µs on
the M4), and an unchanged `_update_proxy` 2.3 → 1.4 µs. Measured: ninja work
−10 %, mundo −26 %, corrida −14 % ([games.md](../scripts/bench/games.md), D1 /
D3). Adding an input to Sprite's key means adding it here too: the equality
test fails until both agree. `_SPRITE_POSE_KEY_FAST = False` is the generic key.

**Freeform vs regular polygons.** A freeform `Polygon`'s vertices are Defining, and a
vertex write does not bump the epoch, so its extra packs every vertex relative to the
vertex-average centroid (plus rotation / scale): stable under `move_by`, changed by a
vertex drag. World-space vertices would rebuild the hull on every translate.
`RegularPolygon` / `Triangle` override it with an extra of their Defining
slots (`angle` / `radius` / `side`) and never walk vertices: there the vertices are
Derivates, and reading them (`shape.points`) would warm them for good (~10× slower;
[Reactive Design](Reactive%20Design.md)). Tests:
`test_collision.test_regular_polygon_does_not_inherit_vertex_pose_extra`,
`test_collision.test_irregular_polygon_vertex_move_rebuilds_cached_poly`.

**Prims are mutable; caches must not share them.** The translate fast path
(`_translate_prims`, used by `snapshot_shape` and `_world_prims`) shifts Prim objects
**in place**. Any cache that keeps Prims (`_poly_cache`) must store and return clones
(`_clone_prims`); handing out its own objects lets a later translate move the cached
entry while its key still names the old vertices (D2 in [Testing Design](Testing%20Design.md#bug-catalogue)).

**Translated prims equal a rebuild within float tolerance, in no set order.**
Translation drifts by ulps, and prim order within a snapshot is not part of the
contract. Compare two prim lists as a multiset within tolerance
(`diff_support.assert_same_prims`), never by sorting raw floats: an ulp reorders
prims that tie on the first sort field (two arc wedges sharing their split vertex),
and a sorted compare then pairs different prims (D10 in [Testing Design](Testing%20Design.md#bug-catalogue)).

During the detection narrow loop and `_apply_auto_resolve`, `_trust_proxy_world` lets a collider whose `_world_key` already matches `_proxy_key` return the cached hull **without** walking `_collision_pose_key` / Sprite extras. Solver nudges (`_nudge_collider`) translate that hull and **shift** the `(epoch, x, y, *extra)` key bundle by `(dx, dy)` instead of recomputing extras.

In the narrow loop that is safe because `_update_proxy` refreshed every live `_proxy_key` a moment earlier and no user code runs before dispatch; it turns k pose-key walks for a collider in k pairs into one. The end-of-step `_store_resolved_aabbs` runs in the same window: nothing runs between resolve and the store, so proxies still match the solver's nudges. Do not trust that cache outside those three passes — `test_collision` after `center=` and before `step()` must see the new pose.

## What not to add

Do not Cython/Numba the narrow phase: it measured 0.03–0.6 ms when resolve was
11–35 ms; the inner cost is pose keys and set membership. No spatial hash or
sweep-and-prune: declared-pair AABB is the right broad phase, it only needed to be
vectorized. No sleeping islands / crate stacking (Scena is not a physics engine). No
closed-form circle–OBB TOI: removing the spinning bar left the cost unchanged. Do not
ask authors to omit `resolve("ball", "ball")` (beginners write mutual pools). Do not
share settle’s overlapping set with floor snap (snap needs floors not yet touched).
Do not feed settle a frame-start candidate set (sequential nudges create same-frame
overlaps the snapshot misses).

No `.solid` / `.is_sensor` / `mass=0` as sensor — `@collide` vs `resolve()` already
splits detect vs push, so each flag would be a second spelling. A blanket "everyone
in this group pushes everyone" is `resolve(tag, tag)`, one line per group instead of
a flag per object. A sensor (coin, pickup, damage zone) is `collidable` and never
named in `resolve()` — the default state of everything. `mass=0` would divide by
zero in the mass split, and the only thing it could mean ("does not interact") is
already "not named in `resolve()`"; so `mass <= 0` raises.

## Runtime cost (mass-sprite related)

Incremental `@collide` enroll, lazy world hulls, and collider swap-remove live with the mass-sprite hot path in [Sprite Design.md — Mass sprite hot path](Sprite%20Design.md#mass-sprite-hot-path). Proxy AABB under rotation: closed-form extents (circumradius for a RegularPolygon, cached local extents for a Sprite) instead of rebuilding prims to union them, because rotation bumps the epoch and misses the translate fast path every frame — collision −31% on a rotating 180-body arena (2026-08, M4); see **Sprite colliders** / Proxy. Mutual `resolve()` pools: this section. `@collide`-only scenes pay nothing extra: resolved bounds follow `resolve()` membership, so a spinner that overlaps nothing never builds a hull. Swept detection costs one multiply and one compare per moving collider when nothing is fast ([Swept detection — Cost](#swept-detection-fast-bodies)). `last_stats["ms_bounds"]` times that store apart from `ms_resolve`.

## Design note (pipeline invariant)

- **Collision** is one shared system for Shape, Sprite, and SpatialFx: each frame **update proxy AABBs** → **declared-pair broad phase** (`_declared_broad_pairs`: `@collide` + `resolve` + `ANYTHING`; self-paired tags `i < j`) → **lazy world prims** only for overlapping pairs → prim AABB reject → narrow (circle/AABB fast paths or SAT) → swept pass for this frame's fast colliders ([Swept detection](#swept-detection-fast-bodies)) → standing `resolve()` on **tag-indexed** partners (sweep AABB-reject, settle current-proxy cull). `@collide` / `resolve` string tags enroll on construct / group change, not a full group walk each `step()`. Details: [Sprite Design.md — Mass sprite hot path](Sprite%20Design.md#mass-sprite-hot-path); mutual pools: [Resolve hot path](#resolve-hot-path). Every prim carries a world AABB (circle → bounding square, Line/ellipse/Track → OBB AABB, polygon → verts AABB), so non-rect geometry is AABB-filtered before detailed tests — not sprite-only. Snapshots: Shape geometry (**Track** = polyline of Line-like thin OBBs along the bake — closed = ring, interior empty; proxy = samples + half `line_width`; `begin`/`end` trim the stroked window); Sprite via `_collision_specs()` (reference-set bake, frozen unless `hitbox_source="each"`, mapped through `_hitbox_pose_wh` — [Sprite colliders](#sprite-colliders); fitters in [Sprite Design.md — Auto hitbox](Sprite%20Design.md#auto-hitbox-shapeauto)); SpatialFx domains — `PointDomainFx` publishes `_collision_specs()` (main-paint circle for disc emitters; emission OBB for Plume/Tongues/Embers — deliberately tighter than `_domain_aabb()` cull pads), `PadDomainFx`→AABB/OBB via `_pad_frame()`, `BeamDomainFx`→thin OBB via `_beam_frame()`. Pose key includes those frames’ size/orientation (`_point_frame` = radius, or width/length/angle for directed Fire) so slider writes rebuild instead of sliding a stale hull; `_domain_aabb` is the broad-phase proxy. Same `@collide` / `collidable` surface on all.


## Not in this doc

- Auto hitbox fitters / utility pick / corpus results → [Sprite Design.md](Sprite%20Design.md#auto-hitbox-shapeauto)
- Sprite freeze / mapping / proxy contract → **Sprite colliders** above
- Author API catalog (examples, `@collide_stay`, `resolve`, …) → [Guia da API — Colisão](../docs/pt/guide/index.html#colisao)
- Off-field cleanup (`@leave_playfield`, not colliders) → [Guia da API](../docs/pt/guide/index.html#reagir-bounds)
- Method decorators on classes → [Actors Design.md](Actors%20Design.md)
- **Outline crossings** (`intersections` / `intersection` / `closest_point`) → [`scena/geom.py`](../scena/geom.py); design notes in [Shapes Design.md — Geometry queries](Shapes%20Design.md#geometry-queries). Collision answers filled-body overlap (`CollisionInfo.points` is a contact, not an outline crossing list).
- Not taken: sprite proxy tighter than the turned extent box (see **Sprite colliders** / Proxy).
- Current numbers for mutual `resolve()` pools → [scripts/bench/resolve.md](../scripts/bench/resolve.md) (pulse); algorithms: **Resolve hot path** above
