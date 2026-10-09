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
| One-way / jump-through (`only=`) | [One-way pairs: `only=`](#one-way-pairs-only) |
| Mutual `resolve()` pools / cost | [Resolve hot path](#resolve-hot-path) |
| Instant set vs travel | [Motion vs placement](#motion-vs-placement) |
| Orbit / `rotate_by(about=)` sweep, spin not swept | [Orbit chord](#orbit-chord) |
| Spinning hazards / rotating obstacles tunnel | [Spin (not swept)](#spin-not-swept) |
| Relative-frame sweep / glue | [Relative-frame sweep](#relative-frame-sweep) |
| Floor snap / grounded flicker | [Floor snap / grounded flicker](#floor-snap--grounded-flicker) |
| Ledge / "will I fall?" (`floor_below`) | [Floor ahead: `floor_below`](#floor-ahead-floor_below) |
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
| `floor_below` | `collision.py` (`CollisionSystem.floor_below`, `_QueryOnlyGate`, `_note_floor_probe`) | `entity.py` (`Graphic.floor_below`), `tests/test_floor_below.py` |
| `only=` read-only guard | `purity_check.py` (`check_read_only`, `_READING`) | `formula_check.py` (locator, context) |
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

**Compound body (`Collider`).** `Collider([torso, head])` is author API (in `scena.__all__`, since the Guia's only import is `from scena import *`): several shapes collide as one identity, and handlers see the Collider. Its author surface is `Collider(shapes)`, `.shapes` and the three `on_collide*` callbacks; everything the engine needs is underscored (`_pair_targets`, `_add_pair_target` / `_remove_pair_target`, `_sync_anything_interest`, `_wants`, `_group_tags`, `_identity`, `_unregister`, and the constructor keywords `_identity_shape` / `_register` / `_bind`, hidden by the published `__init__.__signature__`). Every piece must be an `Entity` (shape, sprite, SpatialFx) or a `Hitbox` part, checked for every path (registered body or query probe) before any mutation: anything else raises `TypeError: Collider pieces must be shapes or sprites; got function. Write Collider([torso, head]).` (the value shown only for `None` / numbers, as for Pair sides). Before that check, any weak-referenceable object (a function) registered a body with no geometry that nothing could unregister: a `Collider` has no `destroy` (A33). Tests: `tests/test_collision.py` `TestCompoundCollider.test_collider_comes_with_the_star_import`, `TestCompoundCollider.test_non_shape_pieces_are_refused_before_registration`.

A destroyed body never re-enters the index: `ensure_collider` raises `DestroyedError` for it, so every path that enrolls on demand (`resolve_now`, pair enrollment) refuses a dead actor (A6 in [Testing Design](Testing%20Design.md#a--api-surface)).

## ANYTHING interest lifecycle

`ANYTHING` in `_pair_targets` means **this body tests against every other enrolled participant** in broad phase. It is kept only while a live declaration needs it:

| Source | Adds `ANYTHING` | Removed when |
| --- | --- | --- |
| `on_collide` / `on_collide_stay` / `on_collide_exit` ≠ `None` | yes | all three callbacks are `None` |
| `@collide(x, ANYTHING)` / `@collide_with(ANYTHING)` | yes (on the named side) | handler dropped (destroy / act change / module unload) |
| `resolve(x, ANYTHING)` | yes | `unresolve(x, ANYTHING)` / act change |

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
5. **Handlers** — `@collide` / stay / exit run in the same `flush` window as `@when` / `@on_change` (see [Scena Design.md — Datapath](Scena%20Design.md#datapath)). Handlers may start processes; first tick next frame is fine. This frame's contacts are committed **before** handlers run, so a handler that destroys a partner — even in the frame the pair entered — finds the pair and fires its exit, and a raising handler cannot leave stale contacts that re-fire `enter`. Destroying one partner fires `@collide_exit` for the survivor (and the dying body, while it still exists) before its handlers are dropped, and that pair is not entered again. Every other way out of the system does the same: `collidable = False` fires exit for its current pairs and drops those contact keys (so a later collider reusing the same `id()` cannot inherit them); a collider pruned for having no shapes drops its keys silently (no identity left to report). Enter and stay are skipped when either side is already out of play, so one bullet cannot damage a second enemy in the same dispatch — also **within** one dispatch: after each handler that ran, a dispatch epoch (bumped when a collider leaves or a pair handler is removed) is compared, and a dead side ends that enter / stay, and a handler an act change dropped does not run (review 2026-10-09 S8-2, S4-1). An exit goes only to a pair whose enter ran: a body destroyed during this step's enter dispatch drops its not-yet-entered pairs silently, and a pair that separated this step gets its exit at the destroy, while the body still exists, not later from the step's exit loop (S8-3, X-life-2). The dying body is out of its groups before any exit runs, so a survivor's exit counting `group["enemy"]` sees it gone (S9-2). Park leaves collision after the actor reads parked: its exit handlers see `active` False, and their flag writes go to the stash (X-life-1).
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

**Pair sides.** One rule for `@collide` / `@collide_stay` / `@collide_exit` / `resolve` / `unresolve` (`_check_pair_sides`, `collision.py`): a side is one atom or a list / tuple of atoms, and an atom is an actor (`Entity`), a group tag string, `group["tag"]`, `ANYTHING`, a `Collider`, or a `Hitbox` part. Anything else (`5`, `None`, `True`, a dict / set, a post effect, a function) raises `TypeError` at the call, naming the call, the type and the spelling to write (`resolve(player, "walls")`); the value is shown only for `None` / numbers (no object reprs). The check runs before anything is registered or removed, and before `only=` is read, so a bad side is always the first error. Before it, `resolve` / `unresolve` registered a junk atom silently: a pair nothing could ever match. Later, more specific refusals still apply on top (a hitbox part is a valid atom, but `resolve()` refuses it: parts only detect). An empty side keeps its own "must not be empty" message. A shape's Point part (`c.center`, `line.p2`) is an `Entity` but not a body: the same check refuses it first, naming the owner and `@collide(owner)` + `info.point` / `contains_point` / a follower `Point` ([Actors — A part is not an actor](Actors%20Design.md#a-part-is-not-an-actor)); `collidable = True` / `on_collide*` on a part and a registered `Collider([part])` refuse the same way, `ensure_collider` is the backstop, and queries (`test_collision`, `collides_with`) still take a part through an unregistered probe. Tests: `tests/test_pair_sides.py`, `tests/test_part_lifecycle.py`.

Each `step()` after enter/stay/exit dispatch, for each resolve-enrolled body in `_collider_index` order:

1. Rewind the frame's **motion-channel** translation (`move_by` / `_by` / `time=` ticks), not every pose-key jump. Instant `*_to` / `=` / `@=` / `tween(center)` are **placement** and do not produce a swept segment. Rotation, resize, and hitbox rebake are not sweepable — those overlaps go to settle, and a bounds change that crosses into a previously clear body separates across that face ([Unswept bounds](#unswept-bounds)). See [Motion vs placement](#motion-vs-placement).
2. Sweep against **tag-indexed** declared partners (not a scan of every enrolled collider) to the earliest time of impact, in the pair's **relative** frame (`d_self − d_other`), so a rising elevator generates a TOI against its rider. Closed-form for AABB/circle; **conservative advancement** (about 32 support rounds, then a thickness-capped bisect) for rotated, ellipse, and polygonal prims. If the body did not move but a partner did, one relative sweep still runs. If the body already overlaps at `t = 0`, there is nothing to sweep — that is settle.
3. Stop at the contact, back off by `_RESOLVE_SLOP` (~0.08 DU skin), respond to velocity there if `bounce=` is a number, project leftover motion along the surface, repeat up to 4 slides. A relative-frame TOI is against the partner's start-of-frame pose, so the body inherits the partner's leftover displacement (`d_other × (1 − t)`) to convert the contact back to world space — **every** contact side, not only a standing rider (see **Relative-frame sweep**). After a floor contact, leftover motion is discarded only when this frame had no horizontal intent (`abs(dx) < 1e-3` on the motion channel, before sliding) — **stop-on-slope**, internal, no author knob. A walk keeps its slide. An idle body on a slope does not creep. Run speed stays horizontal, not along the surface (`floor_constant_speed` off, no v1 knob). A partner with no `.vel` is infinite mass in that impulse, same as `STATIC`.
4. A **bounded settle** recovers overlaps the body's own motion did not cause (spawned inside a wall, a platform moved into it, a pair that was already overlapping). Correction is `clamp(0.5 × (depth − slop), 0, 8 DU)` per iteration, along the **persistent** contact normal (last TOI normal cached per pair, so a settling body does not oscillate between SAT axes). Containment depth is the distance to the nearer face, so a sunk box can correct more per iteration than a partial overlap; the 8 DU cap stays. That capped path never writes `.vel`. Exact overlap tests run only for partners whose **current** proxy AABBs overlap; a body with no overlapping proxy skips settle. When the pair's last resolved **prim** bounds were clear, the current prims overlap, and this frame's box is not that box shifted by the motion channel, separate across the crossed face by the **prim-support** gap along the entry normal (not the fat prim AABB) — see [Unswept bounds](#unswept-bounds). See [Resolve hot path](#resolve-hot-path).
5. If the body was grounded at frame start and is not *leaving* the candidate floor, **floor snap** pulls it back onto a floor within `max(16 DU, |this frame's downward motion| + 8 DU)` so walking downhill, climbing a ramp, and short-frame resting contact against a rising platform do not hop. Snap keeps the **full** partner list (a floor 16 DU below does not overlap the current proxy). If sweep/settle already recorded a `"bottom"` contact for this body, snap returns immediately (O(1) bottom refcount — see [Resolve hot path](#resolve-hot-path)). “Leaving” is bounce-aware along the contact normal — see **Floor snap / grounded flicker**.

Push direction and stopping distance both come from **this frame's motion**, not from end-of-frame minimum-overlap SAT. SAT itself is reused: at the moment of touching the overlap is ≈ 0, so the minimum-overlap axis *is* the true contact normal. Do not add SAT-axis heuristics, a `bounce=0` “platformer stop”, or approach-bias normal flips — those exist only to paper over deep-overlap SAT and were measured to trade one broken case for another.

A side impact at a ledge is a wall; a jump into a ramp end face is not a floor. Small-extent bodies no longer tunnel through thin slabs at realistic speeds (any speed against non-rotating geometry). Sweeping is the default for `resolve()` pairs; there is no `continuous=True` flag. Detection-only pairs sweep too, gated by speed, again with no flag ([Swept detection](#swept-detection-fast-bodies)). Resolve cost is zero for scenes with no `resolve()` pairs (Galaga-style `@collide` only). Mutual pools (`resolve("ball", "ball")`) stay cheap via the [Resolve hot path](#resolve-hot-path) — not by asking the author to drop the pair.

`side` stays `"top"` / `"bottom"` / `"left"` / `"right"`. Given Scena's fixed y-up world, floor ≡ bottom, ceiling ≡ top, wall ≡ left or right. An exact 45° normal (`abs(nx) == abs(ny)`) is top or bottom, so a 45° ramp is a floor. A per-body `up` (wall-walking, gravity flip) is deferred.

`touching_*` is published from the sweep/settle contacts, not from the pre-correction detection snapshot. `@collide` handlers still see that detection snapshot, plus the resting skin for resolve pairs ([Resting contact (skin)](#resting-contact-skin)) and a fast body's path ([Swept detection](#swept-detection-fast-bodies)). `@collide`-only scenes skip the per-Graphic `touching_*` walk until a previously published set must clear (e.g. `unresolve()`).

Debug outlines (`show_colliders`): gold = enrolled in a `resolve()` pair; cyan = hitbox part; green = other detection-only colliders (`_debug_color_for`).

Manual `info.resolve()` / `push_apart()` apply MTV via `move_by` (same `_ensure_writable` contract as other one-shot transforms). Standing `resolve()` nudges through `_nudge_collider` → `_move_by` after an **eager** enroll-time / link-time check: a linked `center` on either side raises `LinkedAttributeError` at `resolve(...)` (or when `@=` lands on an already-enrolled center), not on first overlap. `resolve()` checks every member of every side before registering any pair (all-or-nothing, like the hitbox-part side check), and the message names the group that pulled the member in; a late group join names the group being joined. A **motion in flight is not a conflict**, in either order: timed `move_*` / `move_along` / `tween` started before `resolve()` compose with it exactly as when started after (push motion is swept; a part tween is placement). Pointer drag under standing `resolve()` is placement — not swept, and floor snap pulls a grounded held body back; see [Shapes Design.md — Persistent drivers](Shapes%20Design.md#persistent-drivers-vs-linked-pose) (pointer hold). See [Shapes Design.md — Persistent drivers vs linked pose](Shapes%20Design.md#persistent-drivers-vs-linked-pose). Escape: `unresolve()` / explicit `.unlink()` — there is no `force=` on the standing registration.

`collision.resolve_enabled` (bool, default `True`) is an advanced hatch next to `show_colliders`. When `False`, skip standing `_apply_auto_resolve` (sweep / settle / floor snap) but keep enroll, proxy, narrow phase, `@collide` / stay / exit, queries, and raycast. `touching_*` clears while off. On `True` again, the next `step()` settles residual overlaps. Not the taught reset path — use placement (`center =` / instant `move_to`) instead.

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

Taught reset / respawn: `center = spawn` or instant `move_to`. Do not suspend `resolve_enabled` for that. Do not treat `@=` as motion. Keep `move_to(..., time=)` on the taught surface; its ticks go through the motion channel.

Author catalog: [Guia da API — Mover](../docs/pt/guide/index.html#mover) and [Colisão](../docs/pt/guide/index.html#colisao). Tracks: [Tracks Design.md](Tracks%20Design.md).

### Orbit chord

`rotate_by(..., about=p)` with `p` off the pose anchor (`_collision_pose_xy`) carries the anchor along an arc. The **outermost** `rotate_by` measures the anchor before and after and notes the difference with `note_collider_motion`, so an orbiting body is swept along the chord between its two poses, like a `move_by`. Timed `rotate_by` / `rotate_to(..., time=)` tick through `rotate_by`, so their orbit is motion too. Hitbox parts get the host's chord (their anchor is the host's `center`).

| Rule | Detail |
| --- | --- |
| Where | `entity._rotate_as_motion`: the instant path of the `_install_timed_pose` wrapper (every Shape subclass override) and the shared `Shape.rotate_by` (Sprite, Text). Only when `about` is given and the shape is enrolled; `about=None`, the per-frame spin path, pays one `None` check |
| Once | A depth counter: an override that calls `super().rotate_by` (Track, Text) notes once, from the outermost call |
| Placement turns | Instant `rotate_to(..., about=)`, and the face snap (`_face_to_heading`, settle-only) run under `entity._rotate_as_placement`: the `rotate_by` they call notes nothing. `angle =` has no pivot, so it never orbits |
| Error | Chord vs arc: the sagitta `r·(1 − cos(Δθ/2))`, under 1 % of `r` below 16° per frame. The swept prims keep the end orientation (spin is not swept) |
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

Sweep rewinds the **new** prims by this frame's motion channel only. A resize, an offset, a hitbox rebake, or a `center` write does not enter `_motion_dx` / `_motion_dy`, so the sweep never sees the face that box crossed. At the apex under a thin slab, gravity (or `bounce=0` on an earlier hit) has already turned `.vel` downward while the box grew upward. Capped settle then orients its exit by that velocity and can spend its 32 DU budget out the **far** side.

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

That relative TOI is not yet a world-space placement. After stopping at time `t`, the body must inherit the partner's leftover displacement `d_other × (1 − t)` so it sits on the contact **where the partner ends the frame**, not where the partner began it. This is a coordinate conversion, not a rider carry.

Two operations share the same loop and must **not** share a gate:

| Operation | What it is | When |
| --- | --- | --- |
| Leftover inheritance `ox += odx×(1−t)` | Relative-frame → world-space conversion | Any contact against a moving partner |
| Stop-on-slope | Discard a tiny horizontal remainder so gravity does not creep downhill | `side == "bottom"` only |

`side` classifies the contact normal (`"top"` / `"bottom"` / `"left"` / `"right"`). It is not a permission bit for solver mechanics that come from how the sweep is framed. Gating leftover inheritance to `"bottom"` was the standing-rider special case from the redesign draft; it is the wrong axis. A head-bonk (`"top"`), a wall shove (`"left"`/`"right"`), and a floor ride need the same conversion whenever the partner translated this frame.

`bounce=` is a separate step: it writes `.vel` along the normal. Position conversion does not write `.vel`. A body can have a correct (even diverging) velocity and a glued pose.

### Already-overlapping TOI

Closed-form AABB TOI (`_aabb_toi`) has a `currently overlapping` branch: if the bodies already overlap at `t = 0`, it returns `t = 0` and a SAT-style axis, independent of approach/separation. Design step 2 still applies: overlap at `t = 0` is settle, not a sweep blocker.

Resolver invariant: when TOI returns `t = 0`, keep the hit **only** if this slide's relative motion is approaching along that normal (`dot(relative_motion, normal) > 0`). If motion is separating or tangential, drop the sweep hit and let settle handle any residual depth.

Settle cannot substitute for that placement. It is bounded (`clamp(0.5 × (depth − slop), 0, 8 DU)` per iteration, four iterations), never writes `.vel`, and a moving partner can recreate more overlap than settle removes.

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
| Hero on an elevator moves too far | Author `move_by(platform.vel)` **and** `bounce=0` matching `.vel` | Position-only vs velocity in **Velocity** below |
| Elevator top turnaround loses `"bottom"` for ~0.3 s | Real detach (platform velocity sign-flips; rider keeps old `+vy`) | Correct physics — not a snap bug; ease the reversal in author code if unwanted |

### What not to add

Do not gate leftover inheritance on `side`, approach direction, or “is this a platform.” Do not add an already-overlapping leave test inside `_aabb_toi` to paper over residual overlap — that branch exists because overlap at `t = 0` is settle. Do not grow settle's gain so it can chase a moving partner; the capped path stays `clamp(0.5 × (depth − slop), 0, 8 DU)`. The full-gap pull in [Unswept bounds](#unswept-bounds) is a separate rule for a face crossed from a clear pose, not a higher cap on spawn or on a moving partner. Do not special-case elevators or `hitbox_source="each"` in a game. Do not tighten the sprite proxy, and do not add a side gate, to stop a false contact from a fat box — recovery compares prim bounds and requires the prims to overlap.

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

### `floor_below` fences

- No `@at_ledge` / `@leave_floor` event, no `facing=` knob, no auto-turn: the query stays a read the author polls; direction is the sign of `dx`. Revisit: a taught script needs an edge event that polling `floor_below` in `update()` cannot express.
- No side-sensor helper (two hitbox parts beside the feet, read through `touching_sides`). `touching_*` is resolve-scoped and parts cannot resolve; a sensor hard-codes `dx` / `depth` as box sizes, is Sprite-only, placed in image pixels, and answers "ground under this spot", not "will I fall". Authors can still build one (a hidden `Rect` linked with `@=` + `collides_with(group=)`; `scripts/smoke/ledge_probe.py` shows both). Revisit: same bar as above.
- No `has_floor` / bool twin and no `collision.floor_below(body)` spelling: one method on `Graphic` (sibling of `touching_sides`). A returned body is truthy while alive.
- Do not let `floor_below` bypass the resolver's floor definition (its own angle, its own reach). If the solver's floor rule or snap reach changes, this changes with it.

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

**Known limits.** Sides are world buckets: a one-way slope steeper than 45° needs a function comparing `c.normal` with the platform's rotation. A row of one-way tiles relies on the resting skin (`_RESOLVE_SLOP`) keeping the walker above the next tile's side face; `TestTileSeams` pins 30 / 60 / 240 fps.

### One-way fences

- Do not put the filter in the `(cb, token, odx, ody)` partner tuple or test it per partner visit — that is thousands of checks per frame for a feature most scenes never use. Dispatch per body; read the gate after a hit.
- No second keyword (`unless=` / `except_=` / `pass_through=` / `sides=`): `except` is reserved, and a negative form would be a second spelling of the same filter. Revisit: a taught game that `only=` cannot express.
- No shape-level `one_way` / `.solid` flag — the pair decides push (see the `.solid` fence), and a shape flag cannot say "the hero passes, the crate does not".
- Do not mark a pass on a rejected hit that an accepted hit precedes: the next slide would then ignore a platform the body lands on (`TestTileSeams` fails).
- No S2 "was above" rule inside the engine; express it in a function if a game wants it.
- No solver-lock check on pose / slot / `Vec2` write paths or `Entity.__setattr__` — hot for every scene. The static pass refuses those writes; the runtime lock stays on cold choke points. Revisit: a taught game that writes pose through unreadable code inside `only=`.
- Do not put a lock check behind a `try/except Exception` (the registry's collision notify): the refusal is swallowed after the change already happened.

## Resting contact (skin)

**A standing `resolve()` pair within `_CONTACT_SKIN` of each other is a contact for `@collide` / stay / exit.** (F1 in [Testing Design](Testing%20Design.md#f--contact-flicker-2026-09-29).)

Why: `@collide` reads the detection snapshot, taken *before* resolve. The sweep stops a body `_RESOLVE_SLOP` (0.08 DU) short of its partner, so a resting body is a small gap. Without a skin it only overlapped when that frame's fall (g·dt²) was deeper than the slop: steady at 60 Hz, "not touching" at 200 Hz, enter / exit every other frame with 5 / 28 ms pacing.

| Rule | Detail |
| --- | --- |
| Which pairs | Both colliders on a standing `resolve()` registration that matches this pair (`_resolve_bounce_for`), and `collision.resolve_enabled` is on. Sensors (`@collide` only), `resolve_now`, and queries (`test_collision`, `collides_with`, `query_*`) stay strict overlap (a sensor also sees a fast body's path — [Swept detection](#swept-detection-fast-bodies); queries never sweep) |
| Skin | `_CONTACT_SKIN = 2 × _RESOLVE_SLOP` (0.16 DU): margin over the slop for the gap settle / snap actually leave |
| Gap | True prim distance (`_prim_gap`: closed form for AABB / circle pairs, `_gjk_distance` otherwise), not the AABB: a circle near a rotated box's AABB corner is not a contact |
| Payload | `depth = 0.0`; `normal` A → B from GJK; `point` from the prim-support witness (same fill as enter / stay) |
| Cost | Only for resolve broad pairs that did not overlap and whose prim AABBs are within the skin. 30 walkers on 100 tiles at 5 / 28 ms pacing: within noise (GJK alone for boxes cost ~8 %, hence the closed forms); a 200-ball `resolve("ball", "ball")` pile: ~6 %. `last_stats["skin"]` counts skin contacts |
| Resolve | Unchanged: the solver does not read the detection dict, so a zero-depth skin contact never pushes |

Accepted limitation (F2, by design): a **curved** body (circle, rounded hitbox) walking over tile seams with **uneven** frame times can enter and exit the *next* tile for a few frames near the seam. The pre-resolve pose sinks by g·dt² (0.6 DU on a 28 ms frame, none on a 5 ms one), so its gap to the tile's corner swings across any fixed skin. It needs all four: a curved body, a seam between separate pieces, uneven pacing, and per-tile `@collide` enter / exit. The tile it stands on stays in contact; grounding and motion are unaffected; steady 60 / 144 / 200 Hz and flat-bottomed bodies are clean. "Which tile am I on" is `touching_contacts` (resolved pose, steady at any pacing) — the Guia teaches that ([Tocando](../docs/pt/guide/index.html#colisao-touching)).

Fence: do not move resolved-pair `@collide` to the resolved pose (dispatch after resolve, or a post-resolve membership test) to cure F2. It splits the [Frame order](#frame-order) rule ("handlers see this frame's detection, then resolve runs"), drops the impact `depth` on enter, and breaks same-frame policy in `@collide_stay` — more cost to teach than the artifact. Reopen only with a real game that shows it. Guard: `tests/test_sys_resting_contact.py` (F2 kept as an `expectedFailure` tripwire: if the behaviour changes, the unexpected success says so).

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

All three spellings rotate about the anchor on the baked hitbox **as drawn** (mirrored under `flip_x` / `flip_y`, the same point the emitted collider uses), not a point on the PNG and not a support vertex. None of them move `center`. The seat is along the contact normal only: a hull's toe and the upright box's resting corner do not drag the art sideways. `"center"` and `"top"` are not dropped onto the floor. Teach `hitbox_anchor="bottom"` for walkers so the pivot is the feet and the lean sits on the ramp. Do **not** auto Y-scale the hitbox from `tilt` — the upright collider is the gameplay geometry; a taller yellow debug box than the leaned silhouette is expected, not a cue to shrink `hitbox_scale.y` each frame.

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
- **`collision.query_shape(shape, group=)`** — `group=` as above. The probe is not a hit against itself or its own parts.
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

## Specs by body kind

- **Shape** — geometry prims from the active model.
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
| Linked `active` (`hb["active"] @= fn`) | A polled link, not a graph edge. `step()` calls `hitbox._refresh_linked_parts()` right after `_prune_dead()`, before the proxies, so collision sees the value after `update` / `on_update` / `play()`. A named query refreshes the part it reaches (`_refresh_part_link` in `_query_collider`, before `_tag_item`). The index is the module-level WeakSet `hitbox._LINKED_PARTS` (it survives `reset_collision_system()`); dead parts leave it in `forget_destroyed_item` and in the refresh loop. Skipped while the host is parked or opted out. Changes go through `Hitbox._apply_active` (enter / exit as a write). No links: one empty-set check per step ([Sprite Design — round 2](Sprite%20Design.md#pixel-shapes-and-linked-active-round-2)) |
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

Partner **identities** `(collider, bounce_token)` are cached across frames in `_partner_ident_cache` (and, with the same lifetime, the `only=` map in `_partner_only_cache` — never in the partner tuple; see [One-way pairs](#one-way-pairs-only)). Each `_resolve_partners` call reuses that list and only refreshes `(motion_dx, motion_dy)`. The cache clears on enroll / unenroll, `resolve` / `unresolve`, register / unregister, and pair-graph rebuilds — not every `step()`.

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

**Freeform vs regular polygons.** A freeform `Polygon`'s vertices are Defining, and a
vertex write does not bump the epoch, so its extra packs every vertex relative to the
vertex-average centroid (plus rotation / scale): stable under `move_by`, changed by a
vertex drag. World-space vertices would rebuild the hull on every translate.
`RegularPolygon` / `EquilateralTriangle` override it with an extra of their Defining
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
