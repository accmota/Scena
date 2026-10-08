"""Shared registry model for the state machines (not a test module).

``RegistryModel`` records what the registry should say about the objects a
machine created: which layer each one is on (painter order per layer), which
groups it joined (join order per group), whether it is alive. Machines update
it from their rules and call the ``check_*`` methods from invariants.

Used by ``test_hyp_canvas.RegistryMachine`` (exact model: the machine performs
every destroy itself) and ``test_sys_hyp_world.WorldMachine`` (destroys also
happen inside callbacks during frames, so it calls ``forget_dead`` before each
check instead of predicting them). See ``design/Testing Design.md``.

The model holds strong references to the objects it tracks: a machine must
call ``clear()`` before a leak check.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional


class Model:
    """What the registry should say about one object."""

    __slots__ = ("kind", "alive", "layer", "groups", "visible", "parked",
                 "saved_visible", "destroy_calls", "spawn_on_destroy")

    def __init__(self, kind, layer, groups):
        self.kind = kind
        self.alive = True
        self.layer = layer
        self.groups = list(groups)  # insertion order irrelevant here; order lives per group
        self.visible = True
        self.parked = False
        self.saved_visible = None
        self.destroy_calls = 0
        self.spawn_on_destroy = False


class RegistryModel:
    """Placement and membership of tracked objects."""

    def __init__(self, group_pool: Iterable[str]):
        self.info: Dict[Any, Model] = {}           # obj -> Model
        self.order: Dict[Any, List[Any]] = {}      # layer key -> [obj] painter order
        self.members: Dict[str, List[Any]] = {g: [] for g in group_pool}  # join order
        self.pending_spawns: Dict[Any, Any] = {}   # dying obj -> child its on_destroy spawned

    # -- queries --------------------------------------------------------------
    def __contains__(self, obj) -> bool:
        return obj in self.info

    def __getitem__(self, obj) -> Model:
        return self.info[obj]

    def live(self) -> List[Any]:
        return [o for o, m in self.info.items() if m.alive]

    # -- updates --------------------------------------------------------------
    def track(self, obj, kind, layer, groups) -> Model:
        m = Model(kind, None, [])
        self.info[obj] = m
        self.place(obj, layer)
        for g in groups:
            self.join(obj, g)
        return m

    def place(self, obj, layer) -> None:
        self.info[obj].layer = layer
        if layer is not None:
            self.order.setdefault(layer, []).append(obj)

    def unplace(self, obj) -> None:
        layer = self.info[obj].layer
        if layer is not None and obj in self.order.get(layer, []):
            self.order[layer].remove(obj)
        self.info[obj].layer = None

    def move(self, obj, layer) -> None:
        """``obj.layer = layer``: to the end of the destination (no-op when same)."""
        if layer != self.info[obj].layer:
            self.unplace(obj)
            self.place(obj, layer)

    def restack(self, obj, front: bool) -> None:
        lst = self.order[self.info[obj].layer]
        lst.remove(obj)
        if front:
            lst.append(obj)
        else:
            lst.insert(0, obj)

    def join(self, obj, g) -> None:
        m = self.info[obj]
        if g not in m.groups:
            m.groups.append(g)
            self.members.setdefault(g, []).append(obj)

    def leave(self, obj, g) -> None:
        m = self.info[obj]
        if g in m.groups:
            m.groups.remove(g)
            self.members[g].remove(obj)

    def destroy(self, obj) -> Optional[Any]:
        """Model side of a successful ``destroy()``. Returns the child an
        ``on_destroy`` spawned (if the object was armed), else ``None``."""
        m = self.info[obj]
        if not m.alive:
            return None
        spawned = None
        if m.spawn_on_destroy:
            spawned = self.pending_spawns.pop(obj, None)
        m.alive = False
        self.unplace(obj)
        for g in list(m.groups):
            self.leave(obj, g)
        return spawned

    def drain(self, name, on_it) -> None:
        """Destroy everything on layer ``name`` to a fixed point (spawns included)."""
        queue = list(on_it)
        while queue:
            obj = queue.pop(0)
            spawned = self.destroy(obj)
            if spawned is not None and self.info[spawned].layer == name:
                queue.append(spawned)

    def forget_dead(self, is_dead: Callable[[Any], bool]) -> None:
        """Apply destroys the machine did not perform itself (callbacks, frames)."""
        for obj, m in list(self.info.items()):
            if m.alive and is_dead(obj):
                self.destroy(obj)

    def clear(self) -> None:
        self.info.clear()
        self.order.clear()
        for lst in self.members.values():
            lst.clear()
        self.pending_spawns.clear()

    # -- checks ---------------------------------------------------------------
    def check_draw_lists(self, sc) -> None:
        """Every tracked object on exactly its layer, once, in model painter
        order; no destroyed object on any layer."""
        seen = {}
        for key in list(sc.layers):
            layer = sc.layers.get(key)
            layer._compact()
            tracked = [o for o in layer._objects if o in self.info]
            assert len(tracked) == len(set(map(id, tracked))), \
                f"layer {key!r} lists an object twice"
            for o in tracked:
                assert o._layer == key, f"{o!r} on layer {key!r} reports {o._layer!r}"
                assert o not in seen, f"{o!r} on layers {seen[o]!r} and {key!r}"
                seen[o] = key
                assert self.info[o].alive, \
                    f"destroyed {self.info[o].kind} {o!r} is back on layer {key!r}"
            want = self.order.get(key, [])
            assert tracked == want, \
                f"layer {key!r} painter order {tracked} != model {want}"
        for key in self.order:
            if self.order[key]:
                assert key in sc.layers, f"model has objects on vanished layer {key!r}"

    def check_groups(self, group_pool: Iterable[str], group_of) -> None:
        """``group[g]`` walks the tracked members in join order, all alive."""
        for g in group_pool:
            walked = [o for o in group_of(g) if o in self.info]
            want = self.members.get(g, [])
            assert walked == want, \
                f"group[{g!r}] walks {walked}, model join order {want}"
            for o in walked:
                assert self.info[o].alive, f"destroyed {o!r} still in group[{g!r}]"
            tracked_count = sum(1 for m in self.info.values() if m.alive and g in m.groups)
            assert tracked_count == len(want)
