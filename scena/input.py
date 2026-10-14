import glfw
import math
import time
from .state import Container, KeyNameMismatch
from . import state as _state
from .validate import expect_bool as _expect_flag
from .closed import ClosedSurface


# Modifier families: either-side query name → physical keys stored on press.
_MOD_FAMILIES = {
    "SHIFT": ("LEFT_SHIFT", "RIGHT_SHIFT"),
    "CTRL": ("LEFT_CTRL", "RIGHT_CTRL"),
    "ALT": ("LEFT_ALT", "RIGHT_ALT"),
    "CMD": ("LEFT_CMD", "RIGHT_CMD"),
}
_SPECIFIC_TO_FAMILY = {
    physical: family
    for family, physicals in _MOD_FAMILIES.items()
    for physical in physicals
}
# Other platforms' modifier words. Not accepted — they raise with the Scena name.
_MOD_SPELLINGS = {
    "CONTROL": "CTRL",
    "COMMAND": "CMD",
    "SUPER": "CMD",
    "WIN": "CMD",
    "WINDOWS": "CMD",
    "META": "CMD",
    "OPTION": "ALT",
}
# press("SHIFT") stores the left physical key (family name is query-only).
_PRESS_CANON = {
    "SHIFT": "LEFT_SHIFT",
    "CTRL": "LEFT_CTRL",
    "ALT": "LEFT_ALT",
    "CMD": "LEFT_CMD",
}


# Named GLFW keys (not A–Z / 0–9). Shared by get_glfw_key_name and the
# one-shot held-key seed at window open.
_GLFW_NAMED_KEYS = {
    glfw.KEY_UP: "UP",
    glfw.KEY_DOWN: "DOWN",
    glfw.KEY_LEFT: "LEFT",
    glfw.KEY_RIGHT: "RIGHT",
    glfw.KEY_SPACE: "SPACE",
    glfw.KEY_F1: "F1",
    glfw.KEY_F2: "F2",
    glfw.KEY_F3: "F3",
    glfw.KEY_F4: "F4",
    glfw.KEY_F5: "F5",
    glfw.KEY_F6: "F6",
    glfw.KEY_F7: "F7",
    glfw.KEY_F8: "F8",
    glfw.KEY_F9: "F9",
    glfw.KEY_F10: "F10",
    glfw.KEY_F11: "F11",
    glfw.KEY_F12: "F12",
    glfw.KEY_ENTER: "ENTER",
    glfw.KEY_BACKSPACE: "BACKSPACE",
    glfw.KEY_DELETE: "DEL",
    glfw.KEY_HOME: "HOME",
    glfw.KEY_END: "END",
    glfw.KEY_PAGE_UP: "PAGEUP",
    glfw.KEY_PAGE_DOWN: "PAGEDOWN",
    glfw.KEY_INSERT: "INS",
    glfw.KEY_TAB: "TAB",
    glfw.KEY_LEFT_ALT: "LEFT_ALT",
    glfw.KEY_RIGHT_ALT: "RIGHT_ALT",
    glfw.KEY_LEFT_CONTROL: "LEFT_CTRL",
    glfw.KEY_RIGHT_CONTROL: "RIGHT_CTRL",
    glfw.KEY_LEFT_SHIFT: "LEFT_SHIFT",
    glfw.KEY_RIGHT_SHIFT: "RIGHT_SHIFT",
    glfw.KEY_LEFT_SUPER: "LEFT_CMD",
    glfw.KEY_RIGHT_SUPER: "RIGHT_CMD",
    glfw.KEY_ESCAPE: "ESC",
    **{code: name for name, codes in (
        # Punctuation is positional: K1 is the key left of 1 on any layout,
        # whatever its cap says. Numbered in reading order (US cap in the
        # comment). The glyph is not the name — it differs per layout.
        ("K1", (glfw.KEY_GRAVE_ACCENT,)),       # `  left of 1
        ("K2", (glfw.KEY_MINUS,)),              # -  right of 0
        ("K3", (glfw.KEY_EQUAL,)),              # =
        ("K4", (glfw.KEY_LEFT_BRACKET,)),       # [  right of P
        ("K5", (glfw.KEY_RIGHT_BRACKET,)),      # ]
        ("K6", (glfw.KEY_BACKSLASH,)),          # \  above Enter (ANSI) / left of Enter (ISO)
        ("K7", (glfw.KEY_SEMICOLON,)),          # ;  right of L
        ("K8", (glfw.KEY_APOSTROPHE,)),         # '
        # ISO key left of Z: GLFW says WORLD_1 on macOS / X11, WORLD_2 on Windows.
        ("K9", (glfw.KEY_WORLD_1, glfw.KEY_WORLD_2)),
        ("K10", (glfw.KEY_COMMA,)),             # ,  right of M
        ("K11", (glfw.KEY_PERIOD,)),            # .
        ("K12", (glfw.KEY_SLASH,)),             # /
    ) for code in codes},
}
# Punctuation names K1…K12 (positional; the Guia table maps each to its US cap).
_PUNCT_KEYS = tuple(f"K{n}" for n in range(1, 13))


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


def get_glfw_key_name(key):
    """Scena name for a GLFW key code, or ``None`` when Scena has no name for it.

    ``None`` keys (numpad, Caps Lock, GLFW_KEY_UNKNOWN …) never reach ``keyp``
    or ``on_key``: a raw code such as ``"46"`` is not a name an author can query.
    """
    # Common letter keys
    if glfw.KEY_A <= key <= glfw.KEY_Z:
        return chr(key)

    # Numbers
    if glfw.KEY_0 <= key <= glfw.KEY_9:
        return chr(key)

    return _GLFW_NAMED_KEYS.get(key)


def known_glfw_keys():
    """GLFW key codes Scena can name — used to seed held keys at window open."""
    yield from range(glfw.KEY_A, glfw.KEY_Z + 1)
    yield from range(glfw.KEY_0, glfw.KEY_9 + 1)
    yield from _GLFW_NAMED_KEYS.keys()


def _canon_part(part: str) -> str:
    return part.strip().upper()


def _split_spec(spec: str) -> list:
    if not isinstance(spec, str) or not spec.strip():
        return []
    return [_canon_part(p) for p in spec.split("+") if p.strip()]


_KEY_WORDS = (
    frozenset(_GLFW_NAMED_KEYS.values())
    | frozenset(_MOD_FAMILIES)
    | frozenset(_SPECIFIC_TO_FAMILY)
)
# Common spellings from other engines → the Scena key name.
_KEY_SPELLINGS = {
    "ESCAPE": "ESC", "RETURN": "ENTER", "DELETE": "DEL", "INSERT": "INS",
    "PAGE_UP": "PAGEUP", "PAGE_DOWN": "PAGEDOWN", "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN", "PGDOWN": "PAGEDOWN", "PG_UP": "PAGEUP",
    "PG_DOWN": "PAGEDOWN", "BKSP": "BACKSPACE", "ARROWUP": "UP", "ARROWDOWN": "DOWN",
    "ARROWLEFT": "LEFT", "ARROWRIGHT": "RIGHT", "UP_ARROW": "UP",
    "DOWN_ARROW": "DOWN", "LEFT_ARROW": "LEFT", "RIGHT_ARROW": "RIGHT",
    "LSHIFT": "LEFT_SHIFT", "RSHIFT": "RIGHT_SHIFT", "LCTRL": "LEFT_CTRL",
    "RCTRL": "RIGHT_CTRL", "LALT": "LEFT_ALT", "RALT": "RIGHT_ALT",
    "LCMD": "LEFT_CMD", "RCMD": "RIGHT_CMD", "SPACEBAR": "SPACE", " ": "SPACE",
    # Punctuation: the US cap and the usual word both point at the K number.
    **{spelling: fix for fix, spellings in (
        ("K1", ("`", "GRAVE", "GRAVE_ACCENT", "BACKQUOTE", "BACKTICK", "TILDE")),
        ("K2", ("-", "MINUS", "DASH", "HYPHEN")),
        ("K3", ("=", "EQUAL", "EQUALS")),
        ("K4", ("[", "LEFT_BRACKET", "LBRACKET", "BRACKETLEFT")),
        ("K5", ("]", "RIGHT_BRACKET", "RBRACKET", "BRACKETRIGHT")),
        ("K6", ("\\", "BACKSLASH")),
        ("K7", (";", "SEMICOLON")),
        ("K8", ("'", "APOSTROPHE", "QUOTE")),
        ("K9", ("WORLD_1", "WORLD_2", "INTLBACKSLASH")),
        ("K10", (",", "COMMA")),
        ("K11", (".", "PERIOD", "DOT")),
        ("K12", ("/", "SLASH")),
    ) for spelling in spellings},
    **_MOD_SPELLINGS,
    **{
        f"{side}_{word}": f"{side}_{family}"
        for word, family in _MOD_SPELLINGS.items()
        for side in ("LEFT", "RIGHT")
    },
}
_CHECKED_SPECS: set = set()
_WORD_KEYS = sorted(set(_GLFW_NAMED_KEYS.values()) - set(_PUNCT_KEYS))

# Names ``on_key_*`` can deliver: play keys and modifier families, not the
# physical side (``LEFT_SHIFT`` arrives as ``SHIFT``) and not a chord.
_DELIVERED_KEYS = frozenset(
    (set(_GLFW_NAMED_KEYS.values()) - set(_SPECIFIC_TO_FAMILY))
    | set(_MOD_FAMILIES)
)
_DELIVERED_CANDIDATES = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + sorted(_DELIVERED_KEYS)
)


def _is_delivered_name(name: str) -> bool:
    if len(name) == 1 and (name.isdigit() or (name.isalpha() and name.isupper())):
        return True
    return name in _DELIVERED_KEYS


def _reject_undeliverable_key(other: str) -> None:
    """Raise when ``on_key_*`` can never deliver ``other``.

    Called only after the compared string failed plain equality, so the name
    actually delivered still compares equal to itself.
    """
    if _is_delivered_name(other):
        return
    if "+" in other:
        raise KeyNameMismatch(
            f"{other!r} is not one key. on_key receives one key at a time; "
            f"chords are keyp(\"CTRL+S\")."
        )
    canon = other.strip().upper()
    spelled = _KEY_SPELLINGS.get(canon, canon)
    # A side spelling (``LSHIFT``, ``LEFT_OPTION``) arrives as its family.
    family = _SPECIFIC_TO_FAMILY.get(spelled)
    if family is not None:
        raise KeyNameMismatch(
            f"on_key receives {family!r}, not {other!r}. "
            f"keyp({spelled!r}) still queries that side."
        )
    if spelled != canon:
        raise KeyNameMismatch(
            f"on_key receives {spelled!r}, not {other!r}. Scena calls it {spelled!r}."
        )
    if _is_delivered_name(canon):
        raise KeyNameMismatch(f"on_key receives {canon!r}, not {other!r}.")
    from .validate import did_you_mean
    hint = did_you_mean(canon or other, _DELIVERED_CANDIDATES)
    raise KeyNameMismatch(f"on_key({other!r}): unknown key.{hint}")


class KeyName(str):
    """Key delivered to script ``on_key_*``. A ``str``, plus a loud compare.

    ``==`` / ``!=`` match ``str`` for every name the handler can deliver.
    A string it can never deliver raises ``ValueError`` (spelling, case,
    family, or chord) instead of comparing false forever. Not a public
    constructor — the engine wraps the script key.
    """

    __slots__ = ()
    __hash__ = str.__hash__

    def __eq__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        if not str.__eq__(self, other):
            _reject_undeliverable_key(other)
        return str.__eq__(self, other)

    def __ne__(self, other):
        # ``str.__ne__`` does not call this class's ``__eq__``.
        eq = KeyName.__eq__(self, other)
        if eq is NotImplemented:
            return NotImplemented
        return not eq


_state._KEY_NAME = KeyName


def _is_key_word(part: str) -> bool:
    return (len(part) == 1 and (part.isalpha() or part.isdigit())) or part in _KEY_WORDS


def check_key_spec(spec, call: str = "keyp") -> None:
    """Raise for a key name no press can ever produce (``keyp("ESCAPE")`` was silently False).

    Cached per spec string, so polling every frame costs one set lookup.
    """
    try:
        if spec in _CHECKED_SPECS:
            return
    except TypeError:
        pass  # unhashable (list, dict): not a key name — the type check below says so
    if not isinstance(spec, str):
        raise TypeError(
            f"{call}() takes a key name string, got {type(spec).__name__} {spec!r}. "
            f"Write {call}(\"SPACE\"), {call}(\"A\") or {call}(\"CTRL+S\")."
        )
    raw_parts = [p for p in spec.split("+")]
    if not spec.strip() or any(not p.strip() for p in raw_parts):
        raise ValueError(
            f"{call}({spec!r}) is not a key name. Write {call}(\"SPACE\") or a chord "
            f"such as {call}(\"CTRL+S\") (the + key itself cannot be named)."
        )
    for raw in raw_parts:
        part = _canon_part(raw)
        if _is_key_word(part):
            continue
        fix = _KEY_SPELLINGS.get(part)
        if fix is not None:
            hint = f" Scena calls it {fix!r}."
        else:
            from .validate import did_you_mean
            hint = did_you_mean(part, sorted(_KEY_WORDS))
        raise ValueError(
            f"{call}({spec!r}): unknown key {raw.strip()!r}.{hint} Keys are letters "
            f"A–Z, digits 0–9, {', '.join(_WORD_KEYS)}; punctuation K1–K12 "
            f"(by position — see the Guia table); modifiers SHIFT / CTRL / ALT / CMD."
        )
    _CHECKED_SPECS.add(spec)


def _reject_key_subscript(key, call: str) -> None:
    """``keyp["A"]`` is not a query. Unknown names still fail as queries do."""
    check_key_spec(key, call)
    raise TypeError(
        f'{call}["{key}"] is not a key query. '
        f'Write {call}("{key}") while held, or {call}.once("{key}") for the press edge.'
    )


def _is_mod_part(part: str) -> bool:
    return part in _MOD_FAMILIES or part in _SPECIFIC_TO_FAMILY


class _HeldView(ClosedSurface):
    """Physical-key filter: modifiers do not hide a play key. ``.once`` is the edge."""

    _closed_who = "keyp.held"

    def __init__(self, owner: "KeyPressed"):
        self._owner = owner

    def __call__(self, key) -> bool:
        check_key_spec(key, "keyp.held")
        if self._owner._input_masked:
            return False
        return self._owner._matches(key, held=True)

    def once(self, key) -> bool:
        check_key_spec(key, "keyp.held.once")
        if self._owner._input_masked:
            return False
        return self._owner._once(key, held=True)

    def __contains__(self, key) -> bool:
        check_key_spec(key, "keyp.held")
        if self._owner._input_masked:
            return False
        return self._owner._matches(key, held=True)

    def __getitem__(self, key):
        _reject_key_subscript(key, "keyp.held")


class KeyPressed(ClosedSurface, Container):
    """The keyboard, as the global ``keyp``: level queries, not events.

    ``keyp("SPACE")`` is ``True`` while the key is down and no Ctrl / Alt /
    Cmd is (Shift does not hide it); ``keyp.held("A")`` ignores modifiers;
    ``keyp.once("SPACE")`` is ``True`` once per press; chords are ``keyp("CTRL+S")``. Unknown key names raise with the closest
    name. For one callback per press, define ``on_key_down(key)`` in the script.
    """

    _closed_who = "keyp"

    def __init__(self):
        super().__init__()

        self._pressed_keys = {}  # physical names currently down
        self._once_fired = set()  # query tokens already delivered this true-run
        # Unconsumed rising edges (even if already up): physical name → the
        # keys that were down at that press. A chord read later must have been
        # down together at some press, never pieced from separate taps.
        self._pending_edges = {}
        self._input_masked = False  # modal HUD: reads are False; presses still track
        self.held = _HeldView(self)

    def _update_impl(self) -> None:
        pass

    def _physical_name(self, key: str) -> str:
        k = _canon_part(key)
        return _PRESS_CANON.get(k, k)

    def _seed_held(self, names) -> None:
        """Install currently-down keys as level state, not as press edges.

        Used when the OS window first exists: keys already held must show in
        ``keyp(...)`` without firing ``once``. Does not go through ``press()``.
        """
        new_keys = {}
        for name in names:
            if not isinstance(name, str) or not name.strip():
                continue
            new_keys[self._physical_name(name)] = True
        if new_keys == self._pressed_keys:
            return
        self._pressed_keys = new_keys
        for physical in new_keys:
            self._once_fired.add(self._token(physical, False))
            self._once_fired.add(self._token(physical, True))
            family = _SPECIFIC_TO_FAMILY.get(physical)
            if family is not None:
                self._once_fired.add(self._token(family, False))
                self._once_fired.add(self._token(family, True))
        self.update()

    def _press(self, key):
        """Register a key as being pressed (physical name)."""
        if not isinstance(key, str):
            return
        physical = self._physical_name(key)
        was_down = physical in self._pressed_keys
        self._pressed_keys[physical] = True
        if not was_down:
            self._pending_edges[physical] = frozenset(self._pressed_keys)
        if physical in _SPECIFIC_TO_FAMILY:
            if _SPECIFIC_TO_FAMILY[physical] != "SHIFT":
                # Modifier down: this hold of any already-down play key is not
                # a new unmodified press (lifting the modifier must not fire
                # once). A play key whose own press is still pending (same
                # poll, never read) keeps its unmodified edge: it was pressed
                # alone, and on_key_down already reported it so (review
                # 2026-10-09 S3-9). Shift does not hide a bare key (PD6).
                pending = self._pending_edges
                for name in self._pressed_keys:
                    if name not in _SPECIFIC_TO_FAMILY and name not in pending:
                        self._once_fired.add(self._token(name, False))
        elif self._active_families() - {"SHIFT"}:
            self._once_fired.add(self._token(physical, False))
        self.update()

    def _set_input_masked(self, masked: bool) -> None:
        """Modal HUD: ``keyp`` / ``once`` / ``held`` read False. Presses still track.

        Lifting the mask swallows edges that rose while it was on, and marks
        keys still held as already reported (same idea as ``_seed_held``).
        """
        want = bool(masked)
        if want == self._input_masked:
            return
        self._input_masked = want
        if not want:
            self._swallow_edges()
        self.update()

    def _swallow_edges(self) -> None:
        """Forget unread rising edges; keys still held count as already reported.

        An edge nobody read with ``once`` stays pending, even after the key
        went up. Lifting a modal mask and an act change both drop them: a
        press from before must not fire ``once`` in what comes next (a SPACE
        held to shoot in one act would skip the next act's prompt). The
        key must be released and pressed again.
        """
        self._pending_edges.clear()
        for physical in self._pressed_keys:
            self._once_fired.add(self._token(physical, False))
            self._once_fired.add(self._token(physical, True))
            family = _SPECIFIC_TO_FAMILY.get(physical)
            if family is not None:
                self._once_fired.add(self._token(family, False))
                self._once_fired.add(self._token(family, True))

    def _expire_edges(self) -> None:
        """Frame boundary: unread rising edges are gone (bug PM3).

        ``once`` is True only in the frame its press arrived in (Guia,
        keyp.once). The frame body calls this last (``_simulate_frame``,
        after the pre-draw ticks), so an edge lives for every reader of one
        frame (update, processes, handlers, flush, ``on_done``) and no longer:
        a press nobody read never fires a later ``if ready and
        keyp.once("SPACE")``. A press that arrives between frames is read in
        the next one. ``_once`` also needs a pending edge while the keys are
        held, so expiring edges is enough here.
        """
        if self._pending_edges:
            self._pending_edges.clear()

    def _release(self, key):
        """Register a key as being released (engine input feed)."""
        if not isinstance(key, str):
            return
        self._pressed_keys.pop(self._physical_name(key), None)
        # `_pending_edges` stays — a same-poll press+release must still be
        # visible to `.once()` after the key is already up.
        stale = [
            token for token in self._once_fired
            if not self._token_physically_down(token)
        ]
        for token in stale:
            self._once_fired.discard(token)
        self.update()

    def _family_down(self, family: str, keys=None) -> bool:
        source = self._pressed_keys if keys is None else keys
        return any(name in source for name in _MOD_FAMILIES[family])

    def _part_down(self, part: str, keys=None) -> bool:
        source = self._pressed_keys if keys is None else keys
        if part in _MOD_FAMILIES:
            return self._family_down(part, keys=source)
        return part in source

    def _active_families(self, keys=None) -> set:
        source = self._pressed_keys if keys is None else keys
        return {
            family
            for family, names in _MOD_FAMILIES.items()
            if any(n in source for n in names)
        }

    def _parse_listed(self, spec) -> tuple:
        """Return (parts, listed_families) or None if the spec is empty/invalid."""
        parts = _split_spec(spec)
        if not parts:
            return None
        listed = set()
        for part in parts:
            if part in _MOD_FAMILIES:
                listed.add(part)
            elif part in _SPECIFIC_TO_FAMILY:
                listed.add(_SPECIFIC_TO_FAMILY[part])
        return parts, listed

    def _matches(self, spec, *, held: bool, keys=None) -> bool:
        parsed = self._parse_listed(spec)
        if parsed is None:
            return False
        parts, listed_families = parsed
        source = self._pressed_keys if keys is None else keys
        if not all(self._part_down(p, keys=source) for p in parts):
            return False
        if held:
            return True
        # Bare play key / exact chord: unlisted modifier families must be up.
        # A lone modifier query (``keyp("SHIFT")``) is presence — extra keys OK.
        play_parts = [p for p in parts if not _is_mod_part(p)]
        if not play_parts:
            return True
        extra = self._active_families(keys=source) - listed_families
        if not listed_families:
            # A bare play key ignores Shift: "hold Shift to run" keeps
            # ``keyp("RIGHT")`` and the jump (bug PD6). Ctrl / Alt / Cmd still
            # hide it (they make shortcuts); a chord stays exact, so
            # ``keyp("CMD+Z")`` is not Cmd+Shift+Z.
            extra.discard("SHIFT")
        return not extra

    def _physicals_for(self, spec) -> set:
        """Physical names a spec refers to (pending-edge consume)."""
        parsed = self._parse_listed(spec)
        if parsed is None:
            return set()
        parts, _listed = parsed
        out = set()
        for part in parts:
            if part in _MOD_FAMILIES:
                family = _MOD_FAMILIES[part]
                chosen = {
                    name for name in family
                    if name in self._pending_edges or name in self._pressed_keys
                }
                if not chosen:
                    return set()
                out.update(chosen)
            else:
                out.add(self._physical_name(part))
        return out

    def _token(self, spec, held: bool) -> str:
        parts = sorted(_split_spec(spec))
        prefix = "held:" if held else ""
        return prefix + "+".join(parts)

    def _token_physically_down(self, token: str) -> bool:
        held = token.startswith("held:")
        spec = token[5:] if held else token
        return self._matches(spec, held=True)

    def _once(self, spec, *, held: bool) -> bool:
        if _SOLVER_READING:
            refuse_if_solver_reading('keyp.once()')
        if not isinstance(spec, str):
            return False
        token = self._token(spec, held)
        matches = self._matches(spec, held=held)
        if not matches:
            if self._matches(spec, held=True):
                # Keys still down but filter fails (e.g. R with Ctrl) — consume
                # so we do not fire later when modifiers lift.
                self._once_fired.add(token)
                return False
            if token in self._once_fired:
                return False
            snapshots = self._pending_rises(spec, held=held)
            if snapshots:
                # Same-poll press+release: the rising edge is still pending
                # even though the live filter is already False. It counts only
                # if the chord was down together at that press (the keys down
                # then), so a CMD tap and a later O tap are not CMD+O. Do not
                # latch `_once_fired` — the true-run is over; latching would
                # suppress the next real press. A second `.once()` this query
                # is False because the pending edges are consumed — every
                # press that completed the chord, not just the first (Cmd-L
                # and Cmd-R tapped under a held O are one read, as two taps
                # of Cmd-L are).
                for snapshot in snapshots:
                    self._consume_edges(self._spec_names_in(spec, snapshot))
                return True
            self._once_fired.discard(token)
            return False
        if token in self._once_fired:
            return False
        if not self._pending_rises(spec, held=held):
            # Down now, but the press that completed the spec was in an earlier
            # frame (its edge expired) or never an edge (seeded at window
            # open): not a press this frame. Latch so it stays False until
            # the keys are released (PM3).
            self._once_fired.add(token)
            return False
        self._consume_edges(self._physicals_for(spec))
        self._once_fired.add(token)
        return True

    def _spec_names_in(self, spec, keys) -> set:
        """Physical names in ``keys`` that a part of ``spec`` refers to."""
        parsed = self._parse_listed(spec)
        if parsed is None:
            return set()
        parts, _listed = parsed
        out = set()
        for part in parts:
            if part in _MOD_FAMILIES:
                out.update(name for name in _MOD_FAMILIES[part] if name in keys)
            else:
                name = self._physical_name(part)
                if name in keys:
                    out.add(name)
        return out

    def _pending_rises(self, spec, *, held: bool) -> list:
        """Keys down at each pending press that completed ``spec`` (may be empty).

        The press must be one of the spec's own keys, and the spec must match
        the keys that were down at that press — not keys pressed at other
        times (bug catalogue IN1).
        """
        out = []
        for name, snapshot in self._pending_edges.items():
            down = dict.fromkeys(snapshot, True)
            if name in self._spec_names_in(spec, down) and self._matches(
                spec, held=held, keys=down
            ):
                out.append(snapshot)
        return out

    def _consume_edges(self, names) -> None:
        for name in names:
            self._pending_edges.pop(name, None)

    def __str__(self):
        """Return a string representation of currently pressed keys"""
        return f"KeyPressed({', '.join(self._pressed_keys.keys())})"

    def __repr__(self):
        """Return a detailed string representation"""
        return f"KeyPressed(pressed_keys={list(self._pressed_keys.keys())})"

    def __bool__(self):
        """Return True if any key is pressed"""
        if self._input_masked:
            return False
        return bool(self._pressed_keys)

    def __contains__(self, key):
        """Same filter as ``keyp(key)`` (bare play key / presence / chord)."""
        check_key_spec(key)
        if self._input_masked:
            return False
        return self._matches(key, held=False)

    def __getitem__(self, key):
        """Subscript is not a key query (``keyp["A"]`` → ``keyp("A")``)."""
        _reject_key_subscript(key, "keyp")

    def __call__(self, key):
        """Bare play key, modifier presence, or explicit ``+`` chord."""
        check_key_spec(key)
        if self._input_masked:
            return False
        return self._matches(key, held=False)

    def once(self, key):
        """Edge of ``keyp(key)``: True once per true-run, then False until release.

        Remembers a rising edge that was already released in the same poll
        (press then release before any ``once`` check).
        """
        check_key_spec(key, "keyp.once")
        if self._input_masked:
            return False
        return self._once(key, held=False)

    def only(self, key):
        """``keyp(key)`` is True and no extra physical keys are down."""
        check_key_spec(key, "keyp.only")
        if self._input_masked or not self._matches(key, held=False):
            return False
        parsed = self._parse_listed(key)
        if parsed is None:
            return False
        parts, _listed = parsed
        allowed = set()
        for part in parts:
            if part in _MOD_FAMILIES:
                allowed.update(_MOD_FAMILIES[part])
            else:
                allowed.add(part)
        return set(self._pressed_keys).issubset(allowed)

    def _script_key_name(self, physical: str) -> str:
        """Name delivered to ``on_key_*`` (family name for modifiers)."""
        if not isinstance(physical, str):
            return physical
        p = self._physical_name(physical)
        return _SPECIFIC_TO_FAMILY.get(p, p)

    def _delivers_script_key(self, physical: str) -> bool:
        """Whether a play-key press/repeat should reach script ``on_key_*``.

        Same filter as ``keyp(name)``: modifiers always deliver; a play key
        delivers only without Ctrl / Alt / Cmd (Shift does not block, PD6).
        """
        if not isinstance(physical, str):
            return False
        name = self._script_key_name(physical)
        if name in _MOD_FAMILIES:
            return True
        return self._matches(name, held=False) 

def _check_button(button, call: str) -> None:
    """Buttons are ``Mouse.BTN_*`` ints 0–7; a name like ``"left"`` was silently False."""
    if isinstance(button, int) and not isinstance(button, bool) and 0 <= button <= 7:
        return
    names = {"LEFT": "BTN_LEFT", "RIGHT": "BTN_RIGHT", "MIDDLE": "BTN_MIDDLE"}
    fix = names.get(button.strip().upper()) if isinstance(button, str) else None
    hint = f"Write {call}(Mouse.{fix})." if fix else (
        f"Write {call}(Mouse.BTN_LEFT) (also BTN_RIGHT, BTN_MIDDLE, BTN_1 … BTN_8)."
    )
    raise TypeError(
        f"{call}() takes a Mouse.BTN_* button, got {type(button).__name__} {button!r}. {hint}"
    )


class Mouse(ClosedSurface, Container):
    """Pointer state in design-space coordinates (same as ScenaCanvas / widgets).

    A Container so ``@=`` formulas that read ``mouse.x`` / ``mouse.y`` /
    ``mouse.press(...)`` register the mouse as a graph source — same pattern as
    ``Clock`` and ``KeyPressed``. Fields stay plain properties (not Attributes).
    Unused: A2 skips ``mark_dirty`` until something links to this instance.
    """

    _closed_who = "mouse"
    # Constants
    BTN_LEFT = 0
    BTN_RIGHT = 1
    BTN_MIDDLE = 2
    BTN_1 = 0
    BTN_2 = 1
    BTN_3 = 2
    BTN_4 = 3
    BTN_5 = 4
    BTN_6 = 5
    BTN_7 = 6
    BTN_8 = 7

    def __init__(self):
        super().__init__()
        self._x = 0
        self._y = 0
        # This frame's pointer motion (the hand, in world units): the sum of
        # the motion callbacks since the frame began. Reset at the end of
        # every frame (``_end_frame``), so a still mouse reads 0 and several
        # callbacks in one poll add up (review 2026-10-09 S1-1 / S3-1).
        self._acc_dx = 0.0
        self._acc_dy = 0.0
        self._pressed_buttons = {}     # Stores currently pressed buttons
        self._last1_click_pos  = {}     # Stores (x,y) of last click for each button
        self._last1_click_time = {}    # Stores time of last click for each button
        self._last2_click_pos  = {}
        self._last2_click_time = {}
        self._input_masked = False
        # Buttons that were down when a modal mask lifted. They stay hidden
        # from ``press`` / ``click_pos`` until that button goes up, so the
        # click that closed a menu does not also fire in the game.
        self._mask_latch_buttons = set()

    @property
    def x(self):
        """Pointer x in world coordinates (camera applied). Read-only."""
        return self._x

    @property
    def y(self):
        """Pointer y in world coordinates (y-up, camera applied). Read-only."""
        return self._y

    @property
    def dx(self):
        """How far the pointer moved in x since the previous frame (world units).

        The hand's motion: every motion event of this frame adds up, a still
        mouse reads 0, and a camera move under a still cursor does not count.
        """
        return self._acc_dx

    @property
    def dy(self):
        """How far the pointer moved in y since the previous frame (world units, y-up)."""
        return self._acc_dy

    def _update_position(self, x, y):
        """Pointer moved: add the step to this frame's ``dx`` / ``dy``."""
        self._acc_dx += x - self._x
        self._acc_dy += y - self._y
        self._x = x
        self._y = y
        self.update()

    def _end_frame(self) -> None:
        """Frame boundary: this frame's motion is spent (``dx`` / ``dy`` read 0
        next frame unless the pointer moves). Notifies only on a change (A2)."""
        if self._acc_dx or self._acc_dy:
            self._acc_dx = 0.0
            self._acc_dy = 0.0
            self.update()

    def _sync_position(self, x, y) -> bool:
        """Write world position as current level, not as a motion.

        First sample after the window opens, and per-frame remap when the
        camera moves under a still cursor. ``dx`` / ``dy`` stay 0. No-op (and
        no ``update()``) when ``(x, y)`` already matches — A2.
        """
        if x == self._x and y == self._y:
            return False
        self._x = x
        self._y = y
        self.update()
        return True

    def _set_input_masked(self, masked: bool) -> None:
        """Modal HUD: ``press`` / ``click_pos`` read empty. Motion (``.x``) stays.

        A button still down when the mask lifts stays hidden until it goes up.
        """
        want = bool(masked)
        if want == self._input_masked:
            return
        if not want:
            self._mask_latch_buttons = set(self._pressed_buttons)
        self._input_masked = want
        self.update()

    def _button_hidden(self, button) -> bool:
        return self._input_masked or button in self._mask_latch_buttons

    def press(self, button=None):
        """Check if any/specific button is pressed"""
        if button is None:
            if self._input_masked:
                return False
            return any(b not in self._mask_latch_buttons for b in self._pressed_buttons)
        _check_button(button, "mouse.press")
        if self._button_hidden(button):
            return False
        return button in self._pressed_buttons

    def _button_down(self, button, x, y):
        """Register button press"""
        self._pressed_buttons[button] = True
        if self._input_masked:
            # A click the game never got (a modal took it) is not the game's
            # last click: ``click_pos`` after the menu closes must not report
            # it (review 2026-10-09 S3-11).
            self.update()
            return
        # Transfer last1 state to last2 if it exists
        if button in self._last1_click_pos:
            self._last2_click_pos[button] = self._last1_click_pos[button]
            self._last2_click_time[button] = self._last1_click_time[button]
        # Update last1 state
        self._last1_click_pos[button] = (x, y)
        self._last1_click_time[button] = time.time()
        self.update()

    def _button_up(self, button):
        """Register button release"""
        self._pressed_buttons.pop(button, None)
        self._mask_latch_buttons.discard(button)
        self.update()

    def click_pos(self, button=None):
        """Get (x,y) tuple of last click for specific/any button"""
        if button is not None:
            _check_button(button, "mouse.click_pos")    # a list hashed raw (A1 class)
        if self._input_masked:
            return None
        if button is None:
            for btn in self._pressed_buttons:
                if btn in self._mask_latch_buttons:
                    continue
                return self._last1_click_pos[btn]
            return None
        if button in self._mask_latch_buttons:
            return None
        return self._last1_click_pos.get(button)

    def _update_impl(self) -> None:
        pass

    def _takein_impl(self, new_value):
        raise TypeError(
            "mouse is input state — cannot takein; read .x/.y/.press() or link "
            "from formulas with lambda: mouse.x"
        )


def get_glfw_mouse_button(button):
    """
    Convert GLFW mouse button enum to button number (0-7).
    Returns: 0 for left button, 1 for right button, 2 for middle button, 3-7 for additional buttons
    """
    button_map = {
        glfw.MOUSE_BUTTON_LEFT: Mouse.BTN_LEFT,
        glfw.MOUSE_BUTTON_RIGHT: Mouse.BTN_RIGHT,
        glfw.MOUSE_BUTTON_MIDDLE: Mouse.BTN_MIDDLE,
        glfw.MOUSE_BUTTON_1: Mouse.BTN_1,
        glfw.MOUSE_BUTTON_2: Mouse.BTN_2,
        glfw.MOUSE_BUTTON_3: Mouse.BTN_3,
        glfw.MOUSE_BUTTON_4: Mouse.BTN_4,
        glfw.MOUSE_BUTTON_5: Mouse.BTN_5,
        glfw.MOUSE_BUTTON_6: Mouse.BTN_6,
        glfw.MOUSE_BUTTON_7: Mouse.BTN_7,
        glfw.MOUSE_BUTTON_8: Mouse.BTN_8
    }
    return button_map.get(button)


# Longest wall-clock step one frame may feed the world (seconds). A hitch —
# breakpoint, window drag / resize stall, GC pause — must not teleport tweens
# to their end or let fast bodies tunnel through colliders.
MAX_FRAME_DT = 0.25


class Clock(ClosedSurface, Container):
    """
    Clock class that tracks time, frame count, and FPS.
    Inherits from Container to provide container functionality.
    """

    _closed_who = "clock"
    
    def __init__(self):
        super().__init__()
        
        # Internal tracking variables
        self._last_time = time.perf_counter()
        self._start_time = time.perf_counter()
        self._fps_count = 0
        self._fps_update_time = time.perf_counter()
        self._fps_update_interval = 1.0  # Update FPS about once per second
        
        # Clock state attributes (read-only via getters except scale / paused)
        self._dt = 0.0
        self._time = 0.0
        self._real_dt = 0.0
        self._real_time = 0.0
        # Presentation time: the unscaled frame step, capped like the world's
        # (MAX_FRAME_DT). Pause and slow motion do not stop it; a hitch does
        # not jump it. The fade cover runs on it (Scena Design, "Clocks").
        self._ui_time = 0.0
        self._frame = 0
        self._fps = 0.0
        self._scale = 1.0
        self._paused = False
        self._scale_before_pause = 1.0

    @property
    def dt(self) -> float:
        """World step, already scaled. What ``update`` and processes use.

        ``min(real_dt, MAX_FRAME_DT) * scale`` in the run loop: after a hitch
        the world advances at most ``MAX_FRAME_DT`` (so ``time`` falls behind
        wall time; ``real_dt`` / ``real_time`` stay raw).
        """
        return self._dt

    @property
    def time(self) -> float:
        """World time since the clock started, scaled (pauses when ``scale`` is 0)."""
        return self._time

    @property
    def real_dt(self) -> float:
        """Wall time elapsed between frames (not scaled)."""
        return self._real_dt

    @property
    def real_time(self) -> float:
        """Wall time since the clock was created (not scaled)."""
        return self._real_time

    @property
    def scale(self) -> float:
        """World rate. ``1`` normal, ``0`` pause, ``0.5`` slow-mo."""
        return self._scale

    @scale.setter
    def scale(self, value) -> None:
        from .validate import number
        v = number(value, "clock.scale")
        if v < 0.0:
            raise ValueError(f"clock.scale must be >= 0, got {v}")
        self._scale = v
        if v > 0.0:
            self._paused = False
            self._scale_before_pause = v
        else:
            self._paused = True

    @property
    def paused(self) -> bool:
        """Sugar: True when world scale is 0. Restores the previous scale on False."""
        return self._paused or self._scale == 0.0

    @paused.setter
    def paused(self, value) -> None:
        want = _expect_flag(value, 'paused')
        if want:
            if not self._paused:
                if self._scale > 0.0:
                    self._scale_before_pause = self._scale
                self._scale = 0.0
                self._paused = True
        else:
            if self._paused or self._scale == 0.0:
                restore = self._scale_before_pause if self._scale_before_pause > 0.0 else 1.0
                self._scale = restore
                self._paused = False

    @property
    def frame(self) -> int:
        """Get the current frame number."""
        return self._frame

    @property
    def fps(self) -> float:
        """Get the current frames per second (updated about once per second)."""
        return self._fps

    def _tick(self, current_time, smooth=None):
        """
        Update clock state for a new frame.

        Args:
            current_time: Current time from time.perf_counter()
            smooth: optional ``real_dt -> step`` (the run loop passes
                ``FramePacer.smooth_dt``: an interval close to k vblank
                periods becomes exactly k periods). ``real_dt`` stays raw.
        """
        # Environment timing: clamp, don't crash. A backward step (mocked /
        # injected clock) is 0; a hitch feeds at most MAX_FRAME_DT to the world.
        real_dt = max(0.0, current_time - self._last_time)
        self._last_time = current_time

        self._real_dt = real_dt
        self._real_time = current_time - self._start_time
        step = real_dt if smooth is None else max(0.0, smooth(real_dt))
        capped = min(step, MAX_FRAME_DT)
        self._dt = capped * self._scale
        self._time += self._dt
        self._ui_time += capped
        self._frame += 1

        # FPS is wall-based (not scaled).
        self._fps_count += 1
        elapsed = current_time - self._fps_update_time
        if elapsed >= self._fps_update_interval:
            self._fps = self._fps_count / elapsed if elapsed > 0 else 0.0
            self._fps_count = 0
            self._fps_update_time = current_time

        self.update()

    def _mark_play_start(self) -> None:
        """Origin wall time at the start of ``run()``, after ``setup()``.

        First ``tick`` then measures a real frame, not construct / ``setup`` /
        window-open elapsed. Does not advance ``time`` / ``frame`` and does
        not ``update()`` the graph.
        """
        now = time.perf_counter()
        self._last_time = now
        self._start_time = now
        self._fps_update_time = now

    def advance(self, real_dt: float) -> None:
        """Advance one frame as if ``real_dt`` seconds of wall time elapsed.

        Applies ``scale`` to world ``dt`` / ``time``. Does **not** tick processes;
        tests should call ``tick_processes()`` after this (the run loop does both).
        Not capped by ``MAX_FRAME_DT``: an explicit step is taken as given
        (only the wall-clock ``tick`` is clamped).
        """
        from .validate import number
        real_dt = number(real_dt, "clock.advance dt")
        if real_dt < 0.0:
            real_dt = 0.0
        self._real_dt = real_dt
        self._real_time += real_dt
        self._ui_time += real_dt
        self._dt = real_dt * self._scale
        self._time += self._dt
        self._frame += 1
        self.update()

    def _update_impl(self) -> None:
        pass


