import glfw
import skia
from OpenGL import GL
import time
import math
from enum import Enum
import builtins
import inspect
from collections import namedtuple
from typing import Optional, Tuple

from .leak_detector import LeakSampler
from .canvas import ScenaCanvas, Canvas, GroupOperator
from .entity import _drawn
from .registry import Registry
from .input import (
    KeyName, KeyPressed, Mouse, Clock, get_glfw_key_name, get_glfw_mouse_button,
    known_glfw_keys, _SPECIFIC_TO_FAMILY,
)
from .uiwidget import WidgetTheme, ui
from .state import State, get_scena_system
from .process import ReadyManager, RememberedManager, tick_processes, _run_with_watchdog, _Watchdog, WATCHDOG_RESUME_S
from .validate import call_truncated
from .bounds import get_bounds_system
from .transients import tick_all_transients
from .history import tick_all_histories
from .cover import tick_cover, is_cover_active, draw_cover
from .spatial_fx import tick_all_spatial_fx
from .pacing import FramePacer, PaceMode, locked_interval
from .gc_policy import freeze_world, thaw_world
import warnings
import traceback
import weakref
import gc

global mouse, keyp, obj, group, canvas, st, ready, clock

MousePressEvent = namedtuple('MousePressEvent', ['x', 'y', 'time', 'widget', 'button'], defaults=(None,))

# Bytecode of the framework's placeholder callbacks (``lambda ...: None``).
_NOOP_CODE = (lambda: None).__code__.co_code


def _is_noop_callback(callback) -> bool:
    """True for a placeholder ``lambda ...: None`` (or an empty author body)."""
    code = getattr(callback, "__code__", None)
    return code is not None and code.co_code == _NOOP_CODE


def callback_if_exists(instance, callback_name, *args):
    """Call ``instance.<callback_name>`` if it is set and not a placeholder.

    Arity-truncated like every other author hook (``call_truncated``): bound
    methods, ``functools.partial`` and callable objects are legal. Errors
    raised by the callback body propagate.
    """
    callback = getattr(instance, callback_name, None)
    if callback is None or _is_noop_callback(callback):
        return
    call_truncated(callback, *args)

# Press record for a press on a disabled widget: the up is consumed too.
_SWALLOWED_PRESS = object()

# Physical modifier keys (Scena names). Never claimed by a focused widget.
_MODIFIER_KEYS = frozenset(_SPECIFIC_TO_FAMILY)


class WidgetManager:
    def __init__(self, pixel_ratio=1.0):
        self.widgets = []
        self.mouse_over_widget = None  # mouse is over this widget
        self.pressed_widget = None     # widget pressed (button down) by mouse left button
        self.focused_widget = None     # widget has focus
        self.mouse_down_widget_by_button = {}  # Dictionary, to match each mouse_up with the respective mouse_press
        self.modal_widget = None  # live modal widget, or None
        self._open_modal_menu = None
        self._open_nonmodal_menu = None
        self.last_click = None
        # GLFW modifier bits of the key event being dispatched (Shift / Ctrl /
        # Alt / Super). Set by ScenaFramework._handle_key before any widget
        # hook runs; TextInput reads it for Shift-select, clipboard, word moves.
        self._key_mods = 0
        # Keys whose press a widget claimed: their release goes to the widget.
        self._claimed_down = set()

        # Define double click parameters
        self.double_click_time_threshold = 0.5  # Maximum time between clicks (in seconds)
        self.double_click_distance_threshold = 5  # Maximum distance between clicks (in framework points)

        # Create default widget theme (layout stays in framework points; pixel_ratio is informational)
        self.widget_theme = WidgetTheme(pixel_ratio)

        # Construct-time HUD column (view space). Stores a box, not a live object.
        # HUD ``Text`` and UIWidgets share it; world ``Text`` and ``stack=False`` do not.
        self.reset_hud_stack()


    def reset_hud_stack(self):
        """Next omitted-y HUD item uses the default top-left origin."""
        self._origin_x = 20.0
        self._origin_top = None  # design_h - 40 when first slot is taken
        self._stack_x = None
        self._stack_bottom = None
        self._stack_extra_gap = 0.0
        self._column_right = None
        self._column_top = None
        self._column_participants = []
        self._column_origin_x = None
        self._end_label_column()

    def set_hud_stack_origin(self, x, y):
        """Next omitted-y HUD item's visual top is ``(x, y)`` (no gap before it)."""
        self._origin_x = float(x)
        self._origin_top = float(y)
        self._stack_x = None
        self._stack_bottom = None
        self._stack_extra_gap = 0.0
        self._column_right = None
        self._column_top = float(y)
        self._column_participants = []
        self._column_origin_x = None
        self._end_label_column()

    def adopt_hud_box(self, x1, y1, *, clear_extra: bool = False):
        """Continue the column below this lower-left (theme gap applies)."""
        self._stack_x = float(x1)
        self._stack_bottom = float(y1)
        if clear_extra:
            self._stack_extra_gap = 0.0
            self._end_label_column()

    def _next_hud_slot(self):
        design_h = ScenaFramework.get_instance().design_height
        self.widget_theme._ensure()
        extra = self._stack_extra_gap
        if self._stack_bottom is not None:
            next_top = (
                self._stack_bottom
                - self.widget_theme.stack_gap
                - extra
            )
            self._stack_extra_gap = 0.0
            next_x = self._origin_x if self._stack_x is None else self._stack_x
        else:
            next_x = self._origin_x
            next_top = (
                self._origin_top if self._origin_top is not None
                else design_h - 40.0
            )
        return next_x, next_top

    def add_widget(self, widget, *, top_left=None):
        # Y-up: stack from the visual top of design space downward (decreasing y).
        # ``_auto_layout_top`` is the visual top edge; ``finish_auto_layout`` converts
        # provisional y1/y2 once the widget knows its height, then advances the column.
        self.begin_hud_item(widget, top_left=top_left)
        self.widgets.append(widget)
        widget.width = self.widget_theme.default_width

    def begin_hud_item(self, item, *, top_left=None):
        """Place ``item``'s visual top-left: the next column slot, or ``top_left``.

        Returns that ``(x, top)``. Sets the provisional box ``_x1`` / ``_y1``
        (``_y1`` holds the top until :meth:`finish_auto_layout` knows the
        height) and ``_stack_auto`` (True only for a column slot — the Slider
        label-column run joins on it). Does not enroll in the widget hit/draw
        lists — callers that need that use :meth:`add_widget`.
        """
        self.widget_theme._ensure()
        # A constructor that raises after this puts the cursor back exactly
        # (``restore_hud_cursor``); the "last participant leaves" rewind alone
        # missed it when the column held other live items. Dropped on success
        # (``entity._wrap_actor_init``).
        item.__dict__.setdefault("_hud_cursor_before", (self, self._cursor_state()))
        if top_left is None:
            x, top = self._next_hud_slot()
        else:
            x, top = float(top_left[0]), float(top_left[1])
        item._x1 = x
        item._y1 = top  # provisional top until finish_auto_layout
        item._auto_layout_top = top
        item._stack_auto = top_left is None
        return (x, top)

    def _cursor_state(self):
        """Everything construction moves in the HUD column (see ``restore_hud_cursor``)."""
        return (self._origin_x, self._origin_top, self._stack_x, self._stack_bottom,
                self._stack_extra_gap, self._column_right, self._column_top,
                list(self._column_participants), self._column_origin_x,
                list(self._label_column))

    def _restore_cursor_state(self, state):
        (self._origin_x, self._origin_top, self._stack_x, self._stack_bottom,
         self._stack_extra_gap, self._column_right, self._column_top,
         self._column_participants, self._column_origin_x,
         self._label_column) = state

    def peek_hud_slot(self):
        """The next column slot ``(x, top)`` without taking it (``stack=False``)."""
        saved = self._stack_extra_gap
        try:
            return self._next_hud_slot()
        finally:
            self._stack_extra_gap = saved

    def finish_auto_layout(self, item, *, participate=True):
        """Convert provisional top→bottom if needed, then advance the HUD column."""
        top = getattr(item, '_auto_layout_top', None)
        if top is not None:
            h = item._y2 - item._y1
            item._y2 = top
            item._y1 = top - h
            item._auto_layout_top = None
        if participate:
            self.adopt_hud_box(item._x1, item._y1)
            self._note_column_extent(item)
            self._remember_column_participant(item)
            if not getattr(item, '_joins_label_column', False):
                self._end_label_column()

    def _note_column_extent(self, item):
        """Remember this column's max x2 and freeze the return-y on first item."""
        x2 = getattr(item, '_x2', None)
        y2 = getattr(item, '_y2', None)
        if x2 is not None:
            x2 = float(x2)
            if self._column_right is None:
                self._column_right = x2
            else:
                self._column_right = max(self._column_right, x2)
        if self._column_top is None and y2 is not None:
            self._column_top = float(y2)

    def _remember_column_participant(self, item) -> None:
        """Current column only. A stack move starts a fresh list."""
        import weakref
        if not getattr(self, "_column_participants", None):
            self._column_participants = []
            x1 = getattr(item, "_x1", None)
            self._column_origin_x = None if x1 is None else float(x1)
        self._column_participants.append(weakref.ref(item))

    def _forget_column_item(self, item) -> None:
        """If this was the last live item in the current column, rewind the cursor.

        Next omitted-y HUD item starts at this column's visual top and x.
        A pending ``ui.gap()`` is dropped. Items from an older column (after
        ``stack_column`` / ``stack_origin`` / ``stack_reset``) are not tracked.
        """
        parts = getattr(self, "_column_participants", None)
        if not parts:
            return
        live = []
        found = False
        for ref in parts:
            obj = ref()
            if obj is None or obj is item:
                if obj is item:
                    found = True
                continue
            if getattr(obj, "is_alive", True):
                live.append(ref)
            else:
                found = True
        if not found:
            return
        self._column_participants = live
        if live:
            return
        self._stack_extra_gap = 0.0
        self._end_label_column()
        top = self._column_top
        origin_x = self._column_origin_x
        if top is None or origin_x is None:
            return
        self.widget_theme._ensure()
        # _next_hud_slot: next_top = stack_bottom - stack_gap. Want next_top == top.
        self._stack_x = origin_x
        self._stack_bottom = float(top) + self.widget_theme.stack_gap
        self._column_right = None

    def advance_hud_column(self, gap=None):
        """Next omitted-y HUD item starts a new column: same visual top, x past this one."""
        self.widget_theme._ensure()
        col_gap = self.widget_theme.stack_gap if gap is None else float(gap)
        right = self._column_right
        if right is None:
            right = self._origin_x + self.widget_theme.default_width
        if self._column_top is not None:
            top = self._column_top
        elif self._origin_top is not None:
            top = self._origin_top
        else:
            top = ScenaFramework.get_instance().design_height - 40.0
        self.set_hud_stack_origin(right + col_gap, top)

    def add_space_separator(self):
        self.widget_theme._ensure()
        self._stack_extra_gap += self.widget_theme.stack_gap
        self._end_label_column()

    def _end_label_column(self):
        """Stop sharing label width. Already-applied ``_label_space`` stays."""
        self._label_column = []

    def join_label_column(self, widget):
        """Share one label-column width across a consecutive HUD run.

        Construction-order only: omitted-y labeled Sliders (and future
        opt-in widgets) at the same ``x1``. A later member can raise the
        shared width; earlier members are relayouted. Closing the run
        (gap, other widget, stack move) does not reset applied widths.
        """
        needed = getattr(widget, '_needed_label_space', None)
        if needed is None:
            return
        if self._label_column and widget._x1 != self._label_column[0]._x1:
            self._end_label_column()
        self._label_column.append(widget)
        space = max(w._needed_label_space for w in self._label_column)
        for w in self._label_column:
            w._update_track_layout(space)

    def _is_live(self, widget) -> bool:
        """Drawn and hit-tested: alive, not parked, and visible."""
        if widget is None:
            return False
        if not getattr(widget, "is_alive", True):
            return False
        if not getattr(widget, "active", True):
            return False
        if not getattr(widget, "visible", True):
            return False
        return True

    def remove_widget(self, widget):
        if widget in self.widgets:
            self.widgets.remove(widget)
        if widget in self._label_column:
            self._label_column.remove(widget)
        if self.focused_widget is widget:
            self.focused_widget = None
            widget._has_focus = False
        if self.pressed_widget is widget:
            widget._pressed = False
            self.pressed_widget = None
        if self.mouse_over_widget is widget:
            widget._is_mouse_over = False
            self.mouse_over_widget = None
        for button, ev in list(self.mouse_down_widget_by_button.items()):
            if ev.widget is widget:
                self.mouse_down_widget_by_button[button] = ev._replace(widget=None)
        if self.modal_widget is widget:
            self.release_modal(widget)

    def _modal_consumes(self) -> bool:
        modal = self.modal_widget
        return modal is not None and self._is_live(modal)

    def _set_input_masked(self, masked: bool) -> None:
        fw = ScenaFramework.get_instance()
        if fw.keys is not None:
            fw.keys._set_input_masked(masked)
        if fw.mouse is not None:
            fw.mouse._set_input_masked(masked)

    def push_modal(self, widget) -> None:
        """This widget takes every pointer event. ``keyp`` / ``mouse.press`` read False.

        A second live modal widget raises. Idempotent for the same widget.
        """
        if self.modal_widget is widget:
            return
        if self._modal_consumes():
            raise RuntimeError(
                f"A modal widget is already open ({self.modal_widget!r}). "
                f"Close it before opening another."
            )
        self.modal_widget = widget
        self._set_input_masked(True)
        # A shape press still held would outlive the mask: its release goes to
        # the modal, and after it closes the stale press would steal the next
        # release (a click on a shape the pointer merely crosses).
        shape_manager = getattr(ScenaFramework.get_instance(), "shape_manager", None)
        if shape_manager is not None:
            shape_manager._drop_press()
        for other in self.widgets:
            if other is widget or not other._is_mouse_over:
                continue
            other._is_mouse_over = False
            other._on_mouse_leave(0, 0)
        self.mouse_over_widget = None
        self.set_focus(widget)

    def release_modal(self, widget) -> None:
        """Drop the modal mask. The click that is still down stays hidden until release."""
        if self.modal_widget is not widget:
            return
        self.modal_widget = None
        self._set_input_masked(False)

    def note_menu_opened(self, menu) -> None:
        """One modal menu at a time. A new non-modal menu replaces the open one."""
        if menu.modal:
            current = self._open_modal_menu
            if (
                current is not None
                and current is not menu
                and getattr(current, "is_alive", False)
            ):
                title = getattr(current, "title", None) or "menu"
                raise RuntimeError(
                    f"A menu is already open ({title!r}). "
                    f"Close it before opening another."
                )
            self._open_modal_menu = menu
            self.push_modal(menu)
            return
        old = self._open_nonmodal_menu
        self._open_nonmodal_menu = menu
        if old is not None and old is not menu and getattr(old, "is_alive", False):
            old.destroy()

    def note_menu_closed(self, menu) -> None:
        if self._open_modal_menu is menu:
            self._open_modal_menu = None
            self.release_modal(menu)
        if self._open_nonmodal_menu is menu:
            self._open_nonmodal_menu = None

    def get_suggested_position(self):
        return self.next_suggested_position

    def no_focus(self):
        self.set_focus(None)

    def _takes_input(self, widget) -> bool:
        """Live and enabled: may be pressed, focused, scrolled."""
        return self._is_live(widget) and getattr(widget, "_enabled", True)

    def focus_next(self, current, *, backwards=False):
        """Tab: move focus to the next tab stop (TextInput) in creation order.

        Wraps around; hidden, parked, and disabled widgets are skipped. With no
        other stop, focus stays where it is.
        """
        stops = [w for w in self.widgets
                 if getattr(w, "_tab_stop", False) and self._takes_input(w)]
        if not stops or (len(stops) == 1 and stops[0] is current):
            return
        if current in stops:
            i = stops.index(current)
            nxt = stops[(i - 1) % len(stops)] if backwards else stops[(i + 1) % len(stops)]
        else:
            nxt = stops[-1] if backwards else stops[0]
        self.set_focus(nxt)

    def set_focus(self, widget):
        if self.focused_widget == widget:
            return

        # Old focus looses focus (if any)
        if self.focused_widget:
            self.focused_widget._has_focus = False
            self.focused_widget._is_mouse_over = False
            self.focused_widget._on_focus_lost()
        # New focus gains focus (if any)
        self.focused_widget = widget
        if self.focused_widget:
            self.focused_widget._has_focus = True
            self.focused_widget._on_focus_gained()
        else:
            # if no widget was set, set focus to default widget (canvas)
            pass # not implemented yet

    def get_widget_at(self, x, y):
        # A modal widget is the only hit target. Misses are swallowed by the handlers.
        if self._modal_consumes():
            modal = self.modal_widget
            if modal._captures_pointer and modal.contains_point(x, y):
                return modal
            return None

        # If there is a widget in action under mouse position, it has priority over the normal widget order
        if (
            self._is_live(self.focused_widget)
            and self.focused_widget._captures_pointer
            and self.focused_widget.contains_point(x, y)
        ):
            return self.focused_widget

        # Iterate in reverse order (last added first); skip non-capturing widgets
        # (e.g. decorative Labels) so shapes underneath can receive the event.
        for widget in reversed(self.widgets):
            if (
                self._is_live(widget)
                and widget._captures_pointer
                and widget.contains_point(x, y)
            ):
                return widget
        return None
        
    def draw(self, canvas):
        self.widget_theme._ensure()
        # A modal menu paints last: its backdrop covers HUD widgets, then the panel.
        modal = self._open_modal_menu
        if not self._is_live(modal):
            modal = None
        for widget in self.widgets:
            if widget is modal or not self._is_live(widget):
                continue
            if not getattr(widget, "_enabled", True):
                canvas.saveLayerAlpha(None, self.widget_theme.disabled_alpha)
                widget._draw_card(canvas)
                widget.draw(canvas)
                canvas.restore()
                continue
            widget._draw_card(canvas)
            widget.draw(canvas)

        for widget in self.widgets:
            if widget is modal or not self._is_live(widget):
                continue
            widget._draw_priority(canvas)

        if modal is not None:
            modal.draw(canvas)

    # Keyboard handling -----------------------------------------------------------------------
    # return True if the key event was handled by a widget, false otherwise

    def _keyboard_widget(self):
        """The focused widget that takes keys (TextInput), or None."""
        w = self.focused_widget
        if self._is_live(w) and w._handle_key:
            return w
        return None

    def claims_key(self, key_name, mods) -> bool:
        """True when the focused keyboard widget keeps this key from the game.

        Modifier keys alone are never claimed: they are held-down state, so
        ``keyp("CMD+S")`` still works while a TextInput has focus.
        """
        w = self._keyboard_widget()
        if w is None or key_name in _MODIFIER_KEYS:
            return False
        return bool(w._claims_key(key_name, mods))

    def key_leaves_widget(self, key_name) -> None:
        """A key the focused widget did not claim is about to reach the game.

        The widget commits pending edits first (keeping focus), so a shortcut
        such as Cmd+S reads the committed cell. A modifier alone does not commit.
        """
        w = self._keyboard_widget()
        if w is not None and key_name not in _MODIFIER_KEYS:
            w._before_key_leaves()

    def handle_char(self, char):
        if self._is_live(self.focused_widget) and self.focused_widget._handle_key:
            self.focused_widget._on_char(char)
            return True
        else:
            return False

    def handle_key(self, key_name):
        if self._is_live(self.focused_widget) and self.focused_widget._handle_key:
            self.focused_widget._on_key(key_name)
            return True
        else:
            return False

    def handle_key_down(self, key_name):
        if self._is_live(self.focused_widget) and self.focused_widget._handle_key:
            self.focused_widget._on_key_down(key_name)
            return True
        else:
            return False

    def handle_key_up(self, key_name):
        if self._is_live(self.focused_widget) and self.focused_widget._handle_key:
            self.focused_widget._on_key_up(key_name)
            return True
        else:
            return False


    # Mouse handling --------------------------------------------------------------------------
    # return True if the mouse_press event was handled by a widget, false otherwise

    def handle_mouse_down(self, x, y, button):
        widget_at_mouse = self.get_widget_at(x, y)
        if widget_at_mouse is not None and not getattr(widget_at_mouse, "_enabled", True):
            # Disabled: blocks the press (nothing underneath gets it), does nothing.
            self.set_focus(None)
            self.mouse_down_widget_by_button[button] = MousePressEvent(
                x, y, time.perf_counter(), _SWALLOWED_PRESS)
            return True

        # Focus change - only need to do something if widget at mouse is different from the current focused widget
        if self.focused_widget != widget_at_mouse:
            # New focus gains focus
            if widget_at_mouse:
                self.set_focus(widget_at_mouse)
            else:
                self.set_focus(None)

        self.mouse_down_widget_by_button[button] = MousePressEvent(x, y, time.perf_counter(), widget_at_mouse)
        if widget_at_mouse:
            if button == Mouse.BTN_LEFT:
                widget_at_mouse._pressed = True
                widget_at_mouse._press_over = True
                self.pressed_widget = widget_at_mouse
            widget_at_mouse._on_mouse_down(x, y, button)
            widget_at_mouse._on_mouse_drag(x, y)
            return True
        if self._modal_consumes():
            return True
        return False

    def handle_mouse_up(self, x, y, button):
        # Get the widget that mouse is over
        widget_at_mouse = self.get_widget_at(x, y)

        if button in self.mouse_down_widget_by_button:
            mouse_down_x = self.mouse_down_widget_by_button[button].x
            mouse_down_y = self.mouse_down_widget_by_button[button].y
            mouse_down_widget = self.mouse_down_widget_by_button[button].widget
            self.mouse_down_widget_by_button.pop(button)
        else:
            return False
        if mouse_down_widget is _SWALLOWED_PRESS:
            return True


        if self.pressed_widget and button == Mouse.BTN_LEFT:
            self.pressed_widget._pressed = False
            self.pressed_widget = None

        # Send the mouse_up event to the widget that was pressed, and not to the one that mouse is over
        if mouse_down_widget:
            # Send the mouse_up event to the widget that was pressed
            mouse_down_widget._on_mouse_up(x, y, button, mouse_down_x, mouse_down_y)
            # Handle mouse click: when mouse is released and the mouse is over the same widget that was pressed, for the same button
            if widget_at_mouse == mouse_down_widget:
                self.handle_mouse_click(x, y, button, widget_at_mouse)
            return True
        if self._modal_consumes():
            return True
        return False


    def handle_mouse_click(self, x, y, button, widget_at_mouse):
        # Record current click using named tuple
        current_click = MousePressEvent(x, y, time.perf_counter(), widget_at_mouse, button)

        # Handle single click
        widget_at_mouse._on_mouse_click(x, y, button)

        # Check for double click
        if (
            self.last_click
            and widget_at_mouse == self.last_click.widget
            and button == self.last_click.button
        ):
            time_diff = current_click.time - self.last_click.time
            distance = math.hypot(current_click.x - self.last_click.x, current_click.y - self.last_click.y)

            # If within thresholds, it's a double click
            if time_diff < self.double_click_time_threshold and distance <= self.double_click_distance_threshold:
                widget_at_mouse._on_mouse_double_click(x, y, button)
                self.last_click = None  # Reset last click
                return True

        # Store current click for future double-click detection
        self.last_click = current_click

        return True

    def handle_mouse_move(self, x, y):
        # Handle mouse drag
        if self.pressed_widget:
            pressed = self.pressed_widget
            pressed._press_over = bool(pressed.contains_point(x, y))
            pressed._on_mouse_drag(x, y)

        # Both the pressed and hovered widgets should receive the mouse_move event
        for record in self.mouse_down_widget_by_button.values():
            if record.widget and record.widget is not _SWALLOWED_PRESS:
                record.widget._on_mouse_move(x, y)

        # Get the widget that mouse is over
        widget = self.get_widget_at(x, y)

        # Set previous hovered widget is_mouse_over to False
        if self.mouse_over_widget and self.mouse_over_widget != widget:
            self.mouse_over_widget._is_mouse_over = False
            self.mouse_over_widget._on_mouse_leave(x, y)

        # Set new hovered widget, set its is_mouse_over to True and send mouse_move event
        if widget and not self.pressed_widget:
            self.mouse_over_widget = widget
            if not getattr(widget, "_enabled", True):
                # Still the hover target (on_hover fires), but no highlight.
                widget._is_mouse_over = False
                return True
            widget._is_mouse_over = True
            widget._on_mouse_move(x, y)
            return True
        self.mouse_over_widget = None
        if self._modal_consumes():
            return True
        return False

    def handle_mouse_scroll(self, xpos, ypos, xoffset, yoffset):
        # Mouse scroll is always handled by the widget that mouse is over
        # Get current mouse position from global mouse object
        widget = self.get_widget_at(xpos, ypos)
        if widget:
            if getattr(widget, "_enabled", True):
                widget._on_mouse_scroll(xoffset, yoffset)
            return True
        if self._modal_consumes():
            return True
        return False
    
    # Depois: implementar evento de mouse 'parado' sobre widget por mais de 1 segundo (sem sair dele)

class CanvasManager:
    def __init__(self):
        self.on_key_down = lambda key: None
        self.on_key_up = lambda key: None
        self.on_key = lambda key: None
        self.on_char = lambda char: None
        self.on_mouse_down = lambda x, y, button: None
        self.on_mouse_up = lambda x, y, button, click_x, click_y: None
        self.on_mouse_click = lambda x, y, button: None
        self.on_mouse_double_click = lambda x, y, button: None
        self.on_mouse_move = lambda x, y: None
        self.on_mouse_drag = lambda x, y, button: None
        self.on_mouse_scroll = lambda xoffset, yoffset: None
        # Presses the script owns (not taken by a widget / shape), by button:
        # (world_x, world_y, view_x, view_y, time). Drives click / double
        # click / drag and ``on_mouse_up``'s ``click_x, click_y``.
        self._presses = {}
        self._last_click = None  # (button, view_x, view_y, time)
        # Same thresholds as widget double click (view-space points, seconds).
        self.click_distance_threshold = 5
        self.double_click_time_threshold = 0.5

    # Keyboard handling -----------------------------------------------------------------------

    def handle_key_down(self, key_name):
        callback_if_exists(self, 'on_key_down', key_name)

    def handle_key_up(self, key_name):
        callback_if_exists(self, 'on_key_up', key_name)

    def handle_key(self, key_name):
        callback_if_exists(self, 'on_key', key_name)

    def handle_char(self, char):
        callback_if_exists(self, 'on_char', char)

    # Mouse handling --------------------------------------------------------------------------

    # World ``x, y`` go to the author. ``view`` (view-space point) only measures
    # "same place" for click / double click, so camera zoom does not change it.

    def handle_mouse_down(self, x, y, button, view=None):
        vx, vy = view if view is not None else (x, y)
        self._presses[button] = (x, y, vx, vy, time.perf_counter())
        callback_if_exists(self, 'on_mouse_down', x, y, button)

    def handle_mouse_up(self, x, y, button, view=None):
        press = self._presses.pop(button, None)
        click_x, click_y = (press[0], press[1]) if press is not None else (x, y)
        callback_if_exists(self, 'on_mouse_up', x, y, button, click_x, click_y)
        if press is None:
            return
        vx, vy = view if view is not None else (x, y)
        if math.hypot(vx - press[2], vy - press[3]) > self.click_distance_threshold:
            return
        self.handle_mouse_click(x, y, button, view=(vx, vy))

    def forget_press(self, button):
        """Drop a script press whose release went to a widget / shape."""
        self._presses.pop(button, None)

    def handle_mouse_click(self, x, y, button, view=None):
        vx, vy = view if view is not None else (x, y)
        now = time.perf_counter()
        callback_if_exists(self, 'on_mouse_click', x, y, button)
        last = self._last_click
        if (
            last is not None
            and last[0] == button
            and now - last[3] < self.double_click_time_threshold
            and math.hypot(vx - last[1], vy - last[2]) <= self.click_distance_threshold
        ):
            self._last_click = None  # a third click starts a new pair
            self.handle_mouse_double_click(x, y, button)
            return
        self._last_click = (button, vx, vy, now)

    def handle_mouse_double_click(self, x, y, button):
        callback_if_exists(self, 'on_mouse_double_click', x, y, button)

    def handle_mouse_move(self, x, y):
        callback_if_exists(self, 'on_mouse_move', x, y)
        for button in tuple(self._presses):
            self.handle_mouse_drag(x, y, button)

    def handle_mouse_drag(self, x, y, button):
        callback_if_exists(self, 'on_mouse_drag', x, y, button)

    def handle_mouse_scroll(self, xpos, ypos, xoffset, yoffset):
        callback_if_exists(self, 'on_mouse_scroll', xoffset, yoffset)


class ShapeInteractionManager:
    """Pointer hit-testing and click/drag for opt-in interactive Graphics.

    Hit order for pointer events (press / scroll): capturing UI widgets first,
    then interactive Graphics on layer ``ui`` (view space), then world Graphics
    (layer ``top`` before ``default``, reverse draw order within a layer), then
    script-level CanvasManager fallbacks.

    Decorative Labels set ``_captures_pointer=False`` so they do not block
    shapes. Only shapes in Registry interactive lists are ever hit-tested.

    Callbacks (all share from_shape, to_shape, pos where applicable):
      - on_click(shape) on press+release inside the same clickable shape
      - on_drag_to(from, to, pos) on the dragged shape at release
      - on_drag_over(from, to, pos) on the dragged shape during drag
      - on_drop_by(from, to, pos) on the droppable target at release

    Left button only for MVP; other buttons can follow WidgetManager later.

    Hover is a level resolved once per frame by :meth:`step_hover` (tiered:
    a full hit test only when the pointer, the pointer targets or the layer
    stack changed; otherwise an O(1) re-check of the current target). Mouse
    moves only record the pointer (:meth:`note_pointer`). See Shapes Design,
    Hover.
    """

    def __init__(self, registry: Registry):
        self.registry = registry
        self.drag_threshold = 5.0  # design units; matches WidgetManager double-click distance scale

        self._pressed_shape = None
        self._press_in_ui = False
        # A press on a shape that refuses presses (a disabled SpriteButton):
        # held so nothing underneath gets it, but no click, drag or press bit.
        self._press_swallowed = False
        # One hover target across widgets → ui → world (Graphic, widget or None).
        self._hover_target = None
        self._ptr_view = None
        self._ptr_world = None
        # Inputs of the last full hover hit test; None forces the next one.
        self._resolved_sig = None
        managers = getattr(registry, "_pointer_managers", None)
        if managers is None:
            managers = weakref.WeakSet()
            registry._pointer_managers = managers
        managers.add(self)
        self._press_x = 0.0
        self._press_y = 0.0
        self._grab_dx = 0.0
        self._grab_dy = 0.0
        self._dragging = False
        self._wheel_while_pressed = False

    def _set_pressed(self, shape, *, ui: bool = False, swallowed: bool = False) -> None:
        """The only writer of ``_pressed_shape``; keeps ``pointer_pressed`` in step.

        ``shape=None`` clears the press. A swallowed press holds the shape
        (nothing underneath gets the release) without its press bit.
        """
        old = self._pressed_shape
        self._pressed_shape = shape
        self._press_in_ui = bool(ui) if shape is not None else False
        self._press_swallowed = bool(swallowed) if shape is not None else False
        if old is not None and old is not shape:
            setter = getattr(old, "_set_pointer_pressed", None)
            if setter is not None:
                setter(False)
        if shape is not None:
            setter = getattr(shape, "_set_pointer_pressed", None)
            if setter is not None:
                setter(not swallowed)

    def _drop_press(self) -> None:
        """Abandon the current press/drag: no release callbacks, hold ended.

        Used when the pressed shape was destroyed, hidden, parked, stopped
        being pressable (or draggable mid-drag — ``draggable = False`` ends
        the hold, Canvas Design, drag), or a modal menu opened.
        """
        from .process import release_hold
        shape = self._pressed_shape
        self._set_pressed(None)
        self._dragging = False
        self._wheel_while_pressed = False
        if shape is not None:
            release_hold(shape)
        self._resolved_sig = None

    def forget_pointer_target(self, shape) -> None:
        """A pointer flag / visibility of ``shape`` changed: drop what it can no longer hold.

        Called from ``_sync_interactive_registry`` (inside setters), so it runs
        no author code: the press is dropped silently and the hover target is
        re-resolved (exit fired) by the next :meth:`step_hover`.
        """
        if self._pressed_shape is shape:
            pressable = shape.clickable or shape.draggable
            if (not _drawn(shape) or not pressable
                    or (self._dragging and not shape.draggable)):
                self._drop_press()
        if self._hover_target is shape:
            self._resolved_sig = None

    def _press_lost(self, shape) -> bool:
        """True when the held shape can no longer be held (dead, or undraggable mid-drag)."""
        if not shape.is_alive:
            return True
        return self._dragging and not shape.draggable

    _call = staticmethod(call_truncated)

    # --- hover (level, resolved once per frame) ------------------------------

    def note_pointer(self, view_xy=None, world_xy=None) -> None:
        """Record the pointer (view and/or world). No hit test: hover waits for :meth:`step_hover`."""
        if view_xy is not None:
            self._ptr_view = (float(view_xy[0]), float(view_xy[1]))
        if world_xy is not None:
            self._ptr_world = (float(world_xy[0]), float(world_xy[1]))

    @staticmethod
    def _hover_eligible(shape) -> bool:
        """Pressable, or carries a hover handler (hover-only shapes stay click-transparent)."""
        return bool(
            shape.clickable
            or shape.draggable
            or getattr(shape, "_on_hover", None) is not None
            or getattr(shape, "_on_hover_exit", None) is not None
        )

    def _still_hovered(self, shape) -> bool:
        """O(1) re-check of the current Graphic target under a still pointer."""
        if not getattr(shape, "is_alive", False) or not _drawn(shape):
            return False
        if not self._hover_eligible(shape):
            return False
        from .registry import layer_is_ui
        pt = self._ptr_view if layer_is_ui(getattr(shape, "_layer", None)) else self._ptr_world
        return pt is not None and shape.contains_point(pt[0], pt[1])

    def _resolve_hover_graphic(self):
        """Full hit test for hover: ``ui`` Graphics (view) before world Graphics."""
        if self._ptr_view is not None:
            hit = self.hit_test_ui(*self._ptr_view, hover=True)
            if hit is not None:
                return hit
        if self._ptr_world is not None:
            return self.hit_test(*self._ptr_world, hover=True)
        return None

    def step_hover(self, widget_over=None, modal: bool = False) -> None:
        """Resolve the single hover target for this frame and fire enter / exit.

        Order: modal (nothing) → pressed shape (keeps its affordance) → widget
        under the pointer → ``ui`` Graphic → world Graphic. Tiered cost: a
        full hit test runs only when the pointer, ``registry._pointer_epoch``
        or the layer stack changed, or the current target stopped being
        valid; otherwise one ``contains_point`` on the current target.
        Trade-off (documented): a *different* shape sliding under a still
        pointer is found when the pointer next moves.
        """
        pressed = self._pressed_shape
        if modal:
            new = None
        elif pressed is not None:
            new = pressed if getattr(pressed, "is_alive", False) else None
        elif widget_over is not None:
            new = widget_over
        else:
            reg = self.registry
            sig = (
                self._ptr_view,
                self._ptr_world,
                getattr(reg, "_pointer_epoch", None),
                reg.pointer_layers_signature(),
            )
            cur = self._hover_target
            if sig == self._resolved_sig and (
                cur is None
                or (not getattr(type(cur), "_scena_is_widget", False)
                    and self._still_hovered(cur))
            ):
                new = cur
            else:
                new = self._resolve_hover_graphic()
                self._resolved_sig = sig
        if modal or pressed is not None or widget_over is not None:
            # Leaving these states must re-resolve even with a still pointer.
            self._resolved_sig = None
        self._set_hover_target(new)

    def _set_hover_target(self, new) -> None:
        """Commit the hover target, then fire exit (old) and enter (new)."""
        old = self._hover_target
        if old is new:
            return
        self._hover_target = new
        if old is not None:
            setter = getattr(old, "_set_pointer_hover", None)
            if setter is not None:
                setter(False)
        if new is not None:
            setter = getattr(new, "_set_pointer_hover", None)
            if setter is not None:
                setter(True)
        try:
            if old is not None:
                self._call(getattr(old, "_on_hover_exit", None), old)
        finally:
            if new is not None and self._hover_target is new:
                self._call(getattr(new, "_on_hover", None), new)

    def forget_destroyed(self, obj) -> None:
        """Destroy path: drop its press, fire the exit now, while ``obj`` still exists."""
        if self._pressed_shape is obj:
            self._drop_press()
        if self._hover_target is obj:
            self._resolved_sig = None
            self._set_hover_target(None)

    def hit_test(self, x, y, exclude=None, *, pressable=False, droppable=False,
                 hover=False):
        """Return the topmost visible interactive *world* shape containing (x, y)."""
        return self._hit_test(
            self.registry.iter_interactive_hit_order(),
            x, y, exclude=exclude, pressable=pressable, droppable=droppable,
            hover=hover,
        )

    def hit_test_ui(self, x, y, exclude=None, *, pressable=False, droppable=False,
                    hover=False):
        """Return the topmost visible interactive *ui* shape containing (x, y)."""
        return self._hit_test(
            self.registry.iter_ui_interactive_hit_order(),
            x, y, exclude=exclude, pressable=pressable, droppable=droppable,
            hover=hover,
        )

    @classmethod
    def _hit_test(cls, iterable, x, y, exclude=None, *, pressable=False,
                  droppable=False, hover=False):
        for shape in iterable:
            if shape is exclude:
                continue
            if not _drawn(shape):
                continue
            if pressable and not (shape.clickable or shape.draggable):
                continue
            if droppable and not shape.droppable:
                continue
            if hover and not cls._hover_eligible(shape):
                continue
            if shape.contains_point(x, y):
                return shape
        return None

    def handle_mouse_down(self, x, y, button, *, ui: bool = False):
        from .input import Mouse
        if button != Mouse.BTN_LEFT:
            return False

        hit = self.hit_test_ui if ui else self.hit_test
        shape = hit(x, y, pressable=True)
        if shape is None:
            return False

        self._set_pressed(shape, ui=ui, swallowed=not shape._accepts_press())
        self._press_x = x
        self._press_y = y
        self._dragging = False
        self._wheel_while_pressed = False
        # step_hover keeps the pressed shape hovered (active affordance).

        from .shapes import get_xy
        cx, cy = get_xy(shape.center, bare=True)
        self._grab_dx = cx - x
        self._grab_dy = cy - y
        return True

    def handle_mouse_move(self, x, y, *, ui: bool = False):
        if ui:
            self.note_pointer(view_xy=(x, y))
        else:
            self.note_pointer(world_xy=(x, y))
        shape = self._pressed_shape
        if shape is None:
            # Idle: hover is coalesced into step_hover (once per frame).
            return False

        # Drag / press-hold: only the space that started the press.
        if bool(ui) != self._press_in_ui:
            return True

        if self._press_lost(shape):
            self._drop_press()
            return True

        if self._press_swallowed:
            return True

        if not self._dragging:
            # Held and over it: a release here would click.
            shape._set_pointer_pressed(
                shape._accepts_press() and shape.contains_point(x, y))
            if not shape.draggable:
                return True
            dist = abs(x - self._press_x) + abs(y - self._press_y)  # Manhattan, same as widgets
            if dist < self.drag_threshold:
                return True
            self._dragging = True
            shape._set_pointer_pressed(True)  # the shape follows the pointer
            # Grab offset from where the shape is *now*: a motion may have
            # carried it since the press; the press-time offset would snap it
            # back. From here the shape moves only by the pointer's travel.
            from .shapes import get_xy
            from .process import hold_claims_on
            cx, cy = get_xy(shape.center, bare=True)
            self._grab_dx = cx - self._press_x
            self._grab_dy = cy - self._press_y
            # The hold holds every motion on the parts drag writes.
            hold_claims_on(shape, shape._parts_written_by_drag())

        shape.move_to(x + self._grab_dx, y + self._grab_dy)
        hit_fn = self.hit_test_ui if self._press_in_ui else self.hit_test
        to_shape = hit_fn(x, y, exclude=shape, droppable=True)
        self._call(shape.on_drag_over, shape, to_shape, (x, y))
        return True

    def handle_mouse_up(self, x, y, button, *, ui: bool = False):
        from .input import Mouse
        if button != Mouse.BTN_LEFT:
            return False

        shape = self._pressed_shape
        if shape is None:
            return False
        if bool(ui) != self._press_in_ui:
            return False

        if self._press_lost(shape):
            # Destroyed, or draggable = False mid-drag: the drag ended there.
            self._drop_press()
            return True

        was_dragging = self._dragging
        used_wheel = self._wheel_while_pressed
        swallowed = self._press_swallowed
        self._set_pressed(None)
        self._dragging = False
        self._wheel_while_pressed = False
        self._resolved_sig = None
        # The hold ends before any release callback, so a snap-back
        # ``move_to(home, time=)`` in ``on_drag_to`` runs (and held motion resumes).
        from .process import release_hold
        release_hold(shape)

        if swallowed:
            # A disabled button: the press and its release end here.
            return True

        hit_fn = self.hit_test_ui if ui else self.hit_test
        if was_dragging:
            to_shape = hit_fn(x, y, exclude=shape, droppable=True)
            pos = (x, y)
            self._call(shape.on_drag_to, shape, to_shape, pos)
            if to_shape is not None:
                self._call(to_shape.on_drop_by, shape, to_shape, pos)
            return True

        # Click: press+release inside; wheel while held means rotate, not click.
        if (
            not used_wheel
            and shape.clickable
            and _drawn(shape)
            and shape._accepts_press()
            and shape.contains_point(x, y)
        ):
            shape._fire_click()
        return True

    def handle_mouse_scroll(self, x, y, xoffset, yoffset):
        """Rotate a ``wheel_rotate`` shape while the mouse button is held on it.

        Works in both pending-press and dragging: hold to aim the wheel, drag
        to move, wheel to rotate — no need to move first. Scroll-up (positive
        yoffset) rotates counter-clockwise. Returns True if consumed.
        """
        shape = self._pressed_shape
        if shape is None or self._press_swallowed or not shape.wheel_rotate:
            return False
        if not shape.is_alive:
            self._drop_press()
            return False
        # The hold now writes rotation too: hold motion on the wheel's parts
        # (a rotation tween would otherwise erase every wheel tick).
        from .process import hold_claims_on
        hold_claims_on(shape, shape._parts_written_by_wheel_rotate())
        shape.rotate_by(float(yoffset) * math.degrees(0.04))
        self._wheel_while_pressed = True
        return True

# ``canvas.framerate`` tokens (one spelling each; scena/pacing.py does the work):
#   "vsync60" — locked to the display, vblank divisor nearest 60 Hz (default,
#               FX Auto's 60 rungs): 60 Hz → every vblank, 120 → every 2nd,
#               144 → 72 Hz.
#   "vsync30" — twice that interval (FX Auto's survival rung).
#   "vsync"   — every vblank (full refresh: 120 on 120 Hz).
#   "max"     — uncapped (benchmarks).
#   a number  — fixed-rate timer at that fps (drift-free schedule). It does
#               not follow the display, so it can judder now and then; prefer
#               a "vsync…" token.
FRAMERATE_TOKENS = ("vsync60", "vsync30", "vsync", "max")
DEFAULT_FRAMERATE = "vsync60"

# Ctrl+Shift+4 cycle: full refresh → locked ~60 / ~30 → fixed caps → uncapped.
FRAMERATE_CYCLE = ("vsync", "vsync60", "vsync30", 60, 30, "max")


def coerce_framerate(value):
    """A ``canvas.framerate`` value: one of ``FRAMERATE_TOKENS`` or fps > 0.

    Raises before anything changes. Returns the token (lower case) or the
    number as given (``60`` stays an int, for read-back).
    """
    from .validate import as_payload, did_you_mean

    value = as_payload(value)
    shape = ("'vsync60' (default), 'vsync30', 'vsync', 'max', "
             "or a number of frames per second (60, 30, …)")
    if isinstance(value, str):
        token = value.strip().lower()
        if token in FRAMERATE_TOKENS:
            return token
        raise ValueError(
            f"canvas.framerate must be {shape}; got {value!r}."
            + did_you_mean(token, FRAMERATE_TOKENS)
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"canvas.framerate must be {shape}; got {type(value).__name__}."
        )
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"canvas.framerate must be finite and > 0; got {value!r}.")
    return value


def framerate_label(framerate, refresh_hz: float) -> str:
    """HUD wording with the real rate: ``VSync 60 (72 Hz)`` on a 144 Hz panel."""
    if framerate == "max":
        return "Max"
    if not isinstance(framerate, str):
        return f"Fixed {framerate:g}"
    n = _locked_interval_for(framerate, refresh_hz)
    name = {"vsync60": "VSync 60", "vsync30": "VSync 30", "vsync": "VSync"}[framerate]
    return f"{name} ({refresh_hz / n:.0f} Hz)"


def _locked_interval_for(framerate: str, refresh_hz: float) -> int:
    if framerate == "vsync":
        return 1
    return locked_interval(refresh_hz, 60.0 if framerate == "vsync60" else 30.0)


# Product defaults: system HUD (FPS / objs) off; FX Auto on (high @ 60).
DEFAULT_SHOW_SYSTEM_INFO = False
DEFAULT_FX_AUTO = True

DISPLAY_WINDOWED = "windowed"
DISPLAY_MAXIMIZED = "maximized"
DISPLAY_FULLSCREEN = "fullscreen"
DISPLAY_MODES = (DISPLAY_WINDOWED, DISPLAY_MAXIMIZED, DISPLAY_FULLSCREEN)
DEFAULT_WINDOW_SCALE = 0.8


def coerce_display_mode(value) -> str:
    """Accept only the three display tokens. Assignment is absolute, not a toggle."""
    if not isinstance(value, str):
        raise ValueError(
            "canvas.display must be 'windowed', 'maximized', or 'fullscreen'"
        )
    mode = value.strip().lower()
    if mode not in DISPLAY_MODES:
        raise ValueError(
            "canvas.display must be 'windowed', 'maximized', or 'fullscreen'"
        )
    return mode


def fit_windowed_geom(
    design_w,
    design_h,
    window_scale,
    work_x,
    work_y,
    work_w,
    work_h,
    left=0,
    top=0,
    right=0,
    bottom=0,
):
    """Largest design-aspect client that fits the work area, scaled and centered.

    ``window_scale`` is a fraction of that max client (1.0 = as large as the
    work area allows). Frame insets are OS chrome (title bar + borders).
    Returns ``(client_w, client_h, pos_x, pos_y)`` where pos is the **outer**
    frame origin so the decorated window is centered in the work area.
    """
    dw = float(design_w)
    dh = float(design_h)
    if dw <= 0.0 or dh <= 0.0:
        raise ValueError("design size must be positive")
    scale = float(window_scale)
    if scale <= 0.0:
        raise ValueError("window_scale must be > 0")
    if scale > 1.0:
        scale = 1.0

    left_i, top_i = float(left), float(top)
    right_i, bottom_i = float(right), float(bottom)
    work_x, work_y = float(work_x), float(work_y)
    work_w, work_h = float(work_w), float(work_h)

    usable_w = max(1.0, work_w - left_i - right_i)
    usable_h = max(1.0, work_h - top_i - bottom_i)
    aspect = dw / dh

    if usable_w / usable_h > aspect:
        max_h = usable_h
        max_w = max_h * aspect
    else:
        max_w = usable_w
        max_h = max_w / aspect

    client_w = max_w * scale
    client_h = max_h * scale

    cw = max(1, int(round(client_w)))
    ch = max(1, int(round(cw / aspect)))
    if ch > usable_h or cw > usable_w:
        ch = max(1, int(round(min(client_h, usable_h))))
        cw = max(1, int(round(ch * aspect)))
        if cw > usable_w:
            cw = max(1, int(round(min(client_w, usable_w))))
            ch = max(1, int(round(cw / aspect)))

    outer_w = cw + left_i + right_i
    outer_h = ch + top_i + bottom_i
    pos_x = int(round(work_x + (work_w - outer_w) / 2.0))
    pos_y = int(round(work_y + (work_h - outer_h) / 2.0))
    return cw, ch, pos_x, pos_y


def letterbox_view(win_w, win_h, design_w, design_h):
    """Uniform view_scale + window-space pads for a possibly non-design-aspect window.

    ``view_scale = min(win_w / design_w, win_h / design_h)``. Pads are the unused
    strips (black bands in maximized / fullscreen). Windowed with a locked
    aspect yields pads ≈ 0.
    """
    dw = float(design_w)
    dh = float(design_h)
    ww = float(win_w)
    wh = float(win_h)
    if dw <= 0.0 or dh <= 0.0 or ww <= 0.0 or wh <= 0.0:
        return 1.0, 0.0, 0.0
    vs = min(ww / dw, wh / dh)
    pad_x = (ww - dw * vs) / 2.0
    pad_y = (wh - dh * vs) / 2.0
    return vs, pad_x, pad_y


class ScenaFramework:
    _instance = None

    def __init__(self):
        if ScenaFramework._instance is not None:
            raise Exception("ScenaFramework is a singleton. Use ScenaFramework.get_instance()")
        
        self.initialized = False

        # Design space (stable authored coordinates). width/height alias design size.
        self.design_width = 2000
        self.design_height = 1200
        self.width = self.design_width
        self.height = self.design_height
        self.window_scale = DEFAULT_WINDOW_SCALE
        self.title = "Scena"

        # Unified background stack (base wallpaper + procedural fields).
        self._background_stack = None  # lazy BackgroundStack (canvas.background)

        # OS window (points) and view_scale: design → window (uniform, aspect-locked).
        self.window_width = self.design_width
        self.window_height = self.design_height
        self.view_scale = 1.0
        self._letterbox_pad_x = 0.0
        self._letterbox_pad_y = 0.0

        # Framebuffer (physical pixels). denser on Retina (e.g. 2x).
        self.pixel_ratio = 1.0
        self.fb_width = self.window_width
        self.fb_height = self.window_height
        
        # canvas.framerate: a FRAMERATE_TOKENS token or a fixed fps.
        self._framerate = DEFAULT_FRAMERATE
        self._pacer = FramePacer(
            set_swap_interval=self._set_swap_interval,
            display_link_factory=self._make_display_link,
        )
        self.frame_count = 0
        
        self._running = False
        self._windowed = False  # True once run() has opened a real OS window
        self._window = None
        self._context = None
        self._scena_draw = None
        self._canvas = None  # public Canvas facade wrapping _scena_draw
        self._raster_surface = None  # in-memory Skia surface used before a window exists
        self._drawing_surface = None
        self._drawing_canvas = None
        self.widget_manager = None
        self.canvas_manager = None
        self.shape_manager = None
        self.collision_system = None

        # Builtin bag is bound to ``st``; the label matches that binding.
        self.state_obj = State(name="st")

        # create keys and mouse objects and add them to builtins
        self.keys = KeyPressed()
        self.mouse = Mouse()
        self.clock = Clock()
        builtins.keyp = self.keys
        builtins.mouse = self.mouse
        builtins.st = self.state_obj
        builtins.clock = self.clock
        builtins.ui = ui
        from .audio import audio, install_audio
        install_audio()
        
        # Callback functions to be set by user
        # obs: mouse and keyboard callbacks are handled by the CanvasManager
        self.setup = lambda scena_canvas: None
        self.update = lambda dt, scena_canvas: None
        # After scene draw, before widgets — for canvas-wide post FX experiments.
        # Signature: post_draw(skia_canvas, scene_image) where scene_image is a
        # GPU texture snapshot of the scene (drawn into an offscreen RT).
        self.post_draw = lambda skia_canvas, scene_image=None: None
        # Private close veto for tools built on Scena (the level editor asks
        # about unsaved changes). Called on a window close request and on the
        # Ctrl+Shift+Z quit; returning False keeps the window open. Not author
        # API (Editor Design.md — Boundary).
        self._close_guard = None
        self._scene_surface = None  # full-res GPU RT when post_draw is live
        self._fx_surface = None     # optional lower-res RT for post FX
        self._fx_surface2 = None    # second low-res RT so snapshots stay live
        self._scene_image = None
        # True after a frame that used the scene-RT post path; cleared once
        # ``_recover_direct_fb_path`` runs so we don't purge every idle frame.
        self._was_using_post = False
        # Canvas-wide post FX resolution (overridden by fx_quality presets).
        self.post_fx_scale = 1.0
        # Shape fill/line ImageFilter resolution (1.0 = saveLayer at full res).
        self.shape_fx_scale = 1.0
        # From quality preset; batch on for shipping qualities, off at full.
        self.batch_shared_filters = True
        self._fx_quality = None  # set via canvas.fx_quality
        self._post_fx_stack = None  # lazy PostFxStack (canvas.effects)
        # Automatic fidelity + present ladder (on by default — high @ 60).
        self._fx_auto = False
        self._fx_auto_ctrl = None  # FxAutoController when Auto is on
        self._fx_auto_applying = False  # suppress manual-override disable
        self._monitor_refresh_hz = 60.0

        # Framework system HUD / debug toggles (Ctrl+Shift+1..4, 7/8, E/F/M/P/Z)
        # Label fields exist before set_fx_auto so a construct-time enable stays silent.
        self._system_label = None
        self._error_label = None
        # ``run(Titulo)``: the first act, built when the top level ends.
        self._first_act = None
        self._show_system_info = DEFAULT_SHOW_SYSTEM_INFO
        self._feedback_text = None
        self._feedback_until = 0.0
        self._feedback_duration = 2.5
        self._last_hud_info_time = None
        self._display_mode = DISPLAY_WINDOWED
        self._display_before_fullscreen = DISPLAY_WINDOWED
        self._windowed_geom = None  # (x, y, w, h) last windowed size
        self._applying_display = False
        self._pending_window_pos = None
        # Inspect overlays / debug zoom / time cycle (off by default).
        self._overlay_pack = False
        self._hud_before_overlay_pack = DEFAULT_SHOW_SYSTEM_INFO
        self._debug_zoom = 1.0
        self._debug_zoom_active = False  # mirror on ScenaCanvas for cull hot path
        self._debug_time_step = 0  # 0=run, 1=pause, 2=¼
        self._debug_time_saved_scale = 1.0
        # Periodic leak sampler (every K frames; off switch via set_leak_detector).
        self._leak_sampler = LeakSampler()

        from .fx_quality import DEFAULT_FX_QUALITY, profile_index_for_quality
        self._apply_fx_quality(DEFAULT_FX_QUALITY)
        self._render_profile_index = profile_index_for_quality(DEFAULT_FX_QUALITY)
        if DEFAULT_FX_AUTO:
            self.set_fx_auto(True)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ScenaFramework()
        return cls._instance

    def _init_glfw(self):
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
            
    def set_glfw_fps(self):
        """Hand the current rate choice to the pacer (it owns swap_interval).

        swap_interval needs an initialized GLFW + current GL context.
        Scripts often set canvas.framerate before run()/open_window(); the
        mode is stored on self and applied again from _create_glfw_window.
        """
        if self._window is None:
            return
        mode, interval, fps = self._pace_request()
        self._pacer.configure(
            mode=mode, interval=interval, fps=fps,
            refresh_hz=self._monitor_refresh_hz,
        )

    def _pace_request(self):
        """``(PaceMode, vblank interval, fixed fps)`` for ``self._framerate``."""
        fr = self._framerate
        if fr == "max":
            return PaceMode.UNCAPPED, 1, 60.0
        if isinstance(fr, str):
            return PaceMode.LOCKED, _locked_interval_for(fr, self._monitor_refresh_hz), 60.0
        return PaceMode.FIXED, 1, float(fr)

    # --- canvas.framerate ------------------------------------------------------

    @property
    def framerate(self):
        """``canvas.framerate``: the token (or fixed fps) pacing uses now."""
        return self._framerate

    @framerate.setter
    def framerate(self, value) -> None:
        # Validate first: a rejected value changes nothing (FX Auto stays).
        fr = coerce_framerate(value)
        self._disable_fx_auto_if_manual()
        self._framerate = fr
        self.set_glfw_fps()

    def _set_swap_interval(self, n: int) -> None:
        if self._window is not None:
            glfw.swap_interval(int(n))

    def _make_display_link(self):
        from ._display_link import DisplayLink
        return DisplayLink(window_center=self._window_center_screen)

    def _window_center_screen(self):
        """Window centre in global screen coordinates (display-link follow)."""
        if self._window is None:
            return None
        x, y = glfw.get_window_pos(self._window)
        w, h = glfw.get_window_size(self._window)
        return (x + w / 2.0, y + h / 2.0)

    def _window_size_overridden(self) -> bool:
        """True when a bench replaced :meth:`_compute_window_size` with a 2-tuple."""
        fn = getattr(self, "_compute_window_size", None)
        orig = ScenaFramework._compute_window_size
        return getattr(fn, "__func__", fn) is not orig

    def _workarea_and_insets(self):
        monitor = self._window_monitor()
        if monitor is None:
            return 0, 0, 1920, 1080, 0, 0, 0, 0
        work_x, work_y, work_w, work_h = glfw.get_monitor_workarea(monitor)
        if self._window is None:
            return work_x, work_y, work_w, work_h, 0, 0, 0, 0
        left, top, right, bottom = glfw.get_window_frame_size(self._window)
        return work_x, work_y, work_w, work_h, left, top, right, bottom

    def _compute_window_size(self, design_w, design_h, window_scale):
        """OS window client size in points from work-area fit.

        Benches may replace this with ``lambda dw, dh, wf: (int(dw), int(dh))``
        to skip work-area fit (design size == window size). Third argument is
        the scale (``window_scale``).
        """
        work_x, work_y, work_w, work_h, left, top, right, bottom = (
            self._workarea_and_insets()
        )
        cw, ch, pos_x, pos_y = fit_windowed_geom(
            design_w, design_h, window_scale,
            work_x, work_y, work_w, work_h,
            left, top, right, bottom,
        )
        self._pending_window_pos = (pos_x, pos_y)
        return cw, ch

    def _place_windowed_in_workarea(self) -> None:
        """Read real frame insets and center the windowed window in the work area.

        Do not ``poll_events`` here: on macOS that re-enters Cocoa while the
        window is still coming up and can SIGSEGV.
        """
        if self._window is None or self._window_size_overridden():
            return
        left, top, right, bottom = glfw.get_window_frame_size(self._window)
        work_x, work_y, work_w, work_h, *_rest = self._workarea_and_insets()
        cw, ch, pos_x, pos_y = fit_windowed_geom(
            self.design_width, self.design_height, self.window_scale,
            work_x, work_y, work_w, work_h,
            left, top, right, bottom,
        )
        glfw.set_window_size(self._window, int(cw), int(ch))
        glfw.set_window_pos(self._window, int(pos_x), int(pos_y))
        self.window_width, self.window_height = int(cw), int(ch)
        self._windowed_geom = (int(pos_x), int(pos_y), int(cw), int(ch))
        self._pending_window_pos = (int(pos_x), int(pos_y))

    def _create_glfw_window(self):
        # Request OpenGL 3.2 Core so Skia's shaders (e.g. gl_VertexID) compile.
        # macOS defaults to a legacy 2.1 / GLSL 1.10 context without these hints.
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 2)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.STENCIL_BITS, 8)
        if hasattr(glfw, "SCALE_TO_MONITOR"):
            glfw.window_hint(glfw.SCALE_TO_MONITOR, True)

        self._window = glfw.create_window(
            self.window_width, self.window_height, self.title, None, None
        )
        if not self._window:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")

        glfw.make_context_current(self._window)

        self._lock_aspect()
        self._place_windowed_in_workarea()

        self._sync_window_and_framebuffer_metrics()
        self._monitor_refresh_hz = self._read_monitor_refresh_hz()
        if self._fx_auto and self._fx_auto_ctrl is not None:
            # Ladder intervals depend on the refresh (144 Hz → every 2nd vblank).
            self._fx_auto_ctrl.set_refresh_hz(self._monitor_refresh_hz)
            self._apply_auto_rung(self._fx_auto_ctrl.current_rung())
        GL.glViewport(0, 0, self.fb_width, self.fb_height)

        # Set callbacks
        glfw.set_key_callback(self._window, self._handle_key)
        glfw.set_char_callback(self._window, self._handle_char)
        glfw.set_cursor_pos_callback(self._window, self._handle_mouse_move)
        glfw.set_mouse_button_callback(self._window, self._handle_mouse_button)
        glfw.set_scroll_callback(self._window, self._handle_mouse_scroll)
        glfw.set_framebuffer_size_callback(self._window, self._handle_framebuffer_resize)
        glfw.set_window_size_callback(self._window, self._handle_window_resize)
        glfw.set_window_pos_callback(self._window, self._handle_window_pos)
        glfw.set_window_maximize_callback(self._window, self._handle_window_maximize)
        glfw.set_window_close_callback(self._window, self._handle_window_close)

        self.set_glfw_fps()

    def _sync_window_and_framebuffer_metrics(self):
        """Refresh window size, framebuffer size, pixel_ratio, and view_scale.

        Does not change design size. pixel_ratio = fb / window (not content_scale).
        view_scale / letterbox pads: largest uniform fit of design inside the window.
        """
        win_w, win_h = glfw.get_window_size(self._window)
        self.window_width, self.window_height = win_w, win_h
        self.fb_width, self.fb_height = glfw.get_framebuffer_size(self._window)
        self.pixel_ratio = (self.fb_width / win_w) if win_w else 1.0
        vs, pad_x, pad_y = letterbox_view(
            win_w, win_h, self.design_width, self.design_height
        )
        self.view_scale = vs
        self._letterbox_pad_x = pad_x
        self._letterbox_pad_y = pad_y

    def _uses_letterbox(self) -> bool:
        return self._display_mode in (DISPLAY_MAXIMIZED, DISPLAY_FULLSCREEN)

    def _apply_view_transform(self, skia_canvas=None, *, camera=True):
        """Map y-up design coords → y-down window/framebuffer.

        Full world map: ``screen = T(pad) · view_scale · flipY · [inspector] · camera · world``
        where ``flipY = T(0, H) · S(1, -1)`` maps authoring y-up to Skia/GLFW y-down.
        ``pad`` is the letterbox offset in window points (0 in windowed mode).
        Inspector scale (debug zoom) is applied only when ``_debug_zoom_active``
        and ``camera=True`` — never for the widget pass.

        Pass ``camera=False`` for the widget pass: same design rectangle glued to
        the window, without pan/zoom/rotation (HUD stays fixed).
        """
        c = skia_canvas if skia_canvas is not None else self._drawing_canvas
        scale = self.pixel_ratio * self.view_scale
        pr = self.pixel_ratio
        H = self.design_height
        c.resetMatrix()
        c.translate(self._letterbox_pad_x * pr, self._letterbox_pad_y * pr)
        c.scale(scale, scale)
        c.translate(0, H)
        c.scale(1, -1)
        if camera:
            if self._debug_zoom_active:
                cx = self.design_width * 0.5
                cy = self.design_height * 0.5
                z = self._debug_zoom
                c.translate(cx, cy)
                c.scale(z, z)
                c.translate(-cx, -cy)
            if self._scena_draw is not None:
                self._scena_draw.apply_camera(c)

    # --- background (unified BackgroundStack) ----------------------------------

    @property
    def background_stack(self):
        """Lazy :class:`~scena.background.BackgroundStack` for ``canvas.background``."""
        if self._background_stack is None:
            from .background import BackgroundStack
            self._background_stack = BackgroundStack()
        return self._background_stack

    def _camera_sample_for_background(self):
        from .background import CameraSample
        canvas_facade = self._canvas
        if canvas_facade is not None:
            return CameraSample(
                pan_x=float(canvas_facade.pan_x),
                pan_y=float(canvas_facade.pan_y),
                zoom=float(canvas_facade.zoom),
                rotation=float(canvas_facade.rotation),
                rest_x=float(canvas_facade.pan_rest_x),
                rest_y=float(canvas_facade.pan_rest_y),
            )
        cx = self.design_width * 0.5
        cy = self.design_height * 0.5
        return CameraSample(
            pan_x=cx,
            pan_y=cy,
            zoom=1.0,
            rotation=0.0,
            rest_x=cx,
            rest_y=cy,
        )

    def _draw_background(self, skia_canvas) -> None:
        """Draw base wallpaper + extra fields (identity CTM, pre-camera).

        Does **not** require the offscreen scene RT (unlike ``canvas.effects``).
        Display letterbox (maximize / fullscreen): full FB is black; wallpaper
        lives in the design rectangle only. Debug zoom still letterboxes the
        wallpaper about the content center.
        """
        stack = self.background_stack
        cam = self._camera_sample_for_background()
        try:
            size = skia_canvas.getBaseLayerSize()
            w = float(size.width())
            h = float(size.height())
        except Exception:
            w = float(self.fb_width)
            h = float(self.fb_height)
        if w <= 0 or h <= 0:
            return
        t = float(getattr(self.clock, "time", 0.0) or 0.0)
        inspector_zoom = float(self._debug_zoom) if self._debug_zoom_active else None
        origin = (0.0, 0.0)
        if self._uses_letterbox():
            skia_canvas.save()
            skia_canvas.resetMatrix()
            skia_canvas.clear(skia.Color4f(0.0, 0.0, 0.0, 1.0))
            skia_canvas.restore()
            pr = float(self.pixel_ratio) or 1.0
            origin = (
                float(self._letterbox_pad_x) * pr,
                float(self._letterbox_pad_y) * pr,
            )
            w = float(self.design_width) * float(self.view_scale) * pr
            h = float(self.design_height) * float(self.view_scale) * pr
        elif inspector_zoom is not None:
            self._clear_background_fast(skia_canvas)
        stack._render(
            skia_canvas,
            w,
            h,
            t,
            cam,
            design_width=float(self.design_width),
            design_height=float(self.design_height),
            fw=self,
            inspector_zoom=inspector_zoom,
            origin=origin,
        )

    def _clear_background_fast(self, skia_canvas) -> None:
        """Cheap clear for window FB before a scene-image blit covers it.

        The full field stack would be invisible under the blit — only need a
        solid fill so uncovered edges / letterboxing do not show garbage.
        Display letterbox bands are always black (not wallpaper).
        """
        if self._uses_letterbox():
            skia_canvas.clear(skia.Color4f(0.0, 0.0, 0.0, 1.0))
            return
        stack = self._background_stack
        color4f = skia.Color4f(0.0, 0.0, 0.0, 1.0)
        if stack is not None:
            base = stack.base
            solid = getattr(base, "_solid_color4f", None)
            if callable(solid):
                c = solid()
                if c is not None:
                    color4f = c
        skia_canvas.clear(color4f)

    def _post_draw_live(self) -> bool:
        """True when the script registered a real ``post_draw`` callback."""
        cb = getattr(self, 'post_draw', None)
        return cb is not None and not _is_noop_callback(cb)

    def _builtin_post_active(self) -> bool:
        """True when the framework should run ``canvas.effects`` (no custom post_draw)."""
        if self._post_draw_live():
            return False
        stack = self._post_fx_stack
        return stack is not None and stack._is_active

    def _needs_scene_rt(self) -> bool:
        return self._post_draw_live() or self._builtin_post_active()

    def _recover_direct_fb_path(self) -> None:
        """Reset GPU / window-FB state after leaving the scene-RT post path.

        After many SkSL passes + compose RTs, drawing the scene straight into
        the window backend RT can fall into a pathological slow path (FPS
        cliff on ``none`` while any active effect stays fast via scene RT).
        Purge unlocked GPU resources, drop retained RuntimeEffect children,
        and rebind the window surface once on the transition.
        """
        stack = self._post_fx_stack
        if stack is not None:
            stack._release_surfaces()
            drop = getattr(stack, "_release_retained_runtime_images", None)
            if callable(drop):
                drop()
        self._scene_surface = None
        self._fx_surface = None
        self._fx_surface2 = None
        if self._scena_draw is not None:
            self._scena_draw._shape_fx_surface = None
            pool = getattr(self._scena_draw, "_shape_fx_pool", None)
            if isinstance(pool, list):
                pool.clear()
        ctx = self._context
        if ctx is None:
            return
        try:
            ctx.flush()
        except Exception:
            pass
        try:
            ctx.freeGpuResources()
        except Exception:
            pass
        try:
            ctx.resetGLTextureBindings()
        except Exception:
            pass
        self._create_drawing_surface()

    def _draw_scene_to(self, skia_canvas, *, exclude_top: bool = False) -> None:
        """Draw scene into ``skia_canvas``, optionally skipping the ``top`` layer."""
        saved = self._scena_draw.skia_canvas
        self._scena_draw.skia_canvas = skia_canvas
        try:
            t = self.clock.time if self.clock is not None else None
            if exclude_top:
                self._scena_draw.draw(layer_filter=lambda name: name != "top", t=t)
            else:
                self._scena_draw.draw(t=t)
        finally:
            self._scena_draw.skia_canvas = saved

    def _draw_top_layer(self, skia_canvas) -> None:
        """Draw only the reserved ``top`` layer onto ``skia_canvas``."""
        saved = self._scena_draw.skia_canvas
        self._scena_draw.skia_canvas = skia_canvas
        try:
            t = self.clock.time if self.clock is not None else None
            self._scena_draw.draw(layer_filter=lambda name: name == "top", t=t)
        finally:
            self._scena_draw.skia_canvas = saved

    def _window_stencil_bits(self) -> int:
        """Stencil bits actually attached to framebuffer 0 (0 if none)."""
        try:
            n = GL.glGetFramebufferAttachmentParameteriv(
                GL.GL_FRAMEBUFFER,
                GL.GL_STENCIL,
                GL.GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE,
            )
            if isinstance(n, (list, tuple)):
                n = n[0] if n else 0
            return max(0, int(n))
        except Exception:
            return 0

    def _draw_ui_layer(self, skia_canvas) -> None:
        """Draw the reserved ``ui`` view-pass layer (no camera, no cull).

        Tight loop: HUD N is small. Filtered Graphics (e.g. ``Text`` + ``Glow``)
        use the same saveLayer / shape-FX path as world draws — paint-attached
        ImageFilters on the window RT clip halos and are a known HiDPI cliff.
        """
        from .registry import UI_LAYER
        layer = self._scena_draw.registry.layers.get(UI_LAYER)
        if layer is None or not layer.visible:
            return
        if getattr(layer, "_tombstones", 0):
            layer._compact()
        engine = self._scena_draw
        saves = skia_canvas.getSaveCount()
        try:
            self._draw_ui_objects(skia_canvas, layer, engine)
        finally:
            skia_canvas.restoreToCount(saves)

    def _draw_ui_objects(self, skia_canvas, layer, engine) -> None:
        for o in layer._objects:
            if o is None or not _drawn(o):
                continue
            if getattr(o, "_plain_blit", False):
                blit = getattr(o, "_blit_plain", None)
                if blit is not None:
                    blit(skia_canvas)
                    continue
            ff = getattr(o, "fill_filter", None)
            lf = getattr(o, "line_filter", None)
            has_ff = ff is not None and getattr(ff, "_skia_filter", None) is not None
            has_lf = lf is not None and getattr(lf, "_skia_filter", None) is not None
            if has_ff or has_lf:
                saved = engine.skia_canvas
                engine.skia_canvas = skia_canvas
                try:
                    if has_ff:
                        engine._draw_fill_only(o)
                    if has_lf:
                        engine._draw_stroke_only(o)
                    visual = getattr(o, "visual", None)
                    overlay = (
                        getattr(visual, "_overlay_after_filters", None)
                        if visual is not None
                        else None
                    )
                    if callable(overlay):
                        overlay(o, skia_canvas)
                finally:
                    engine.skia_canvas = saved
                continue
            o.draw(skia_canvas)

    def _draw_collision_debug(self, skia_canvas) -> None:
        """Deprecated name — use :meth:`_draw_debug_overlays`."""
        self._draw_debug_overlays(skia_canvas)

    def _design_view_world_corners(self):
        """Four corners of the design viewport in world space (author camera).

        Identity camera → design rect ``(0,0)–(W,H)``. Used for the inspect
        view-quad stroke; never includes debug-zoom inspector scale.
        """
        W = float(self.design_width)
        H = float(self.design_height)
        corners = ((0.0, 0.0), (W, 0.0), (W, H), (0.0, H))
        draw_canvas = self._scena_draw
        if draw_canvas is None or not draw_canvas._camera_active:
            return corners
        inv = skia.Matrix()
        if not draw_canvas._camera_matrix.invert(inv):
            return corners
        return tuple(
            (float(inv.mapXY(x, y).x()), float(inv.mapXY(x, y).y()))
            for x, y in corners
        )

    def _stroke_design_view_quad(self, skia_canvas) -> None:
        """Stroke the player design-view quad in world space."""
        corners = self._design_view_world_corners()
        paint = skia.Paint()
        paint.setStyle(skia.Paint.kStroke_Style)
        paint.setStrokeWidth(1.5)
        paint.setAntiAlias(True)
        paint.setColor4f(skia.Color4f(1.0, 0.85, 0.2, 0.9))
        path = skia.Path()
        path.moveTo(corners[0][0], corners[0][1])
        for x, y in corners[1:]:
            path.lineTo(x, y)
        path.close()
        skia_canvas.drawPath(path, paint)

    def _stroke_origin_cross(self, skia_canvas) -> None:
        """Short cross + light axes at world origin."""
        paint = skia.Paint()
        paint.setStyle(skia.Paint.kStroke_Style)
        paint.setStrokeWidth(1.0)
        paint.setAntiAlias(True)
        # Light axes (short)
        paint.setColor4f(skia.Color4f(0.55, 0.55, 0.6, 0.55))
        axis = 80.0
        skia_canvas.drawLine(-axis, 0.0, axis, 0.0, paint)
        skia_canvas.drawLine(0.0, -axis, 0.0, axis, paint)
        # Brighter origin cross
        paint.setColor4f(skia.Color4f(1.0, 0.4, 0.4, 0.95))
        paint.setStrokeWidth(1.5)
        arm = 18.0
        skia_canvas.drawLine(-arm, 0.0, arm, 0.0, paint)
        skia_canvas.drawLine(0.0, -arm, 0.0, arm, paint)

    def _draw_debug_overlays(self, skia_canvas) -> None:
        """Immediate-mode inspect overlays (colliders, view quad, origin, paths).

        No Shape churn. Off → return immediately. View quad also draws while
        debug zoom is active even if the overlay pack is off. Track overlay is
        inspect pack (Ctrl+Shift+7) / ``show_tracks`` only — not debug zoom.
        ``show_colliders`` (SPACE in smoke scripts) still draws without the pack.
        """
        show_pack = self._overlay_pack
        show_zoom = self._debug_zoom_active
        cs = self.collision_system
        show_colliders = cs is not None and cs._show
        from .track import tracks_overlay_wanted, draw_track_overlay
        show_tracks_ov = tracks_overlay_wanted()
        if not (show_pack or show_zoom or show_colliders or show_tracks_ov):
            return
        if show_colliders:
            cs.debug_draw(skia_canvas)
        # Design-view quad + playfield: inspect pack (7) and debug zoom (8).
        # Track overlay: inspect pack (7) and author show_tracks() — not zoom.
        if show_pack or show_zoom:
            self._stroke_design_view_quad(skia_canvas)
            try:
                from .bounds import get_bounds_system
                get_bounds_system().debug_stroke(skia_canvas)
            except Exception:
                pass
        if show_pack or show_tracks_ov:
            draw_track_overlay(skia_canvas)
        if show_pack:
            self._stroke_origin_cross(skia_canvas)

    def _top_exempt_from_post(self) -> bool:
        layer = self._scena_draw.registry.layers.get("top") if self._scena_draw else None
        return bool(layer is not None and getattr(layer, "_exempt_from_post", False))

    def _disable_fx_auto_if_manual(self) -> None:
        """Author quality/rate changes turn Auto off (unless Auto is applying)."""
        if self._fx_auto and not self._fx_auto_applying:
            self._fx_auto = False
            self._fx_auto_ctrl = None

    def _apply_fx_quality(self, quality) -> None:
        """Apply an :class:`~scena.fx_quality.FxQuality` preset (scales + batch)."""
        self._disable_fx_auto_if_manual()
        from .fx_quality import activate_quality, preset_for, profile_index_for_quality
        q = activate_quality(quality)
        preset = preset_for(q)
        self._fx_quality = q
        self.post_fx_scale = float(preset["post_scale"])
        self.shape_fx_scale = float(preset["shape_scale"])
        self.batch_shared_filters = bool(preset["batch_shared_filters"])
        # Keep Ctrl+Shift+3 profile ladder aligned with the author quality knob.
        self._render_profile_index = profile_index_for_quality(q)
        target = self._canvas if self._canvas is not None else self._scena_draw
        if target is not None:
            target.batch_shared_filters = self.batch_shared_filters
            target.shape_fx_scale = self.shape_fx_scale
        # Rebind packages whose draw path / style channels depend on fidelity
        # (e.g. Glow / _OrbHalo multipass LOD vs GlowFilter batching).
        self._refresh_fidelity_sensitive_visuals()

    @property
    def fx_auto(self) -> bool:
        return bool(self._fx_auto)

    def set_fx_auto(
        self,
        enabled: bool = True,
        refresh_hz: float = None,
        params=None,
    ) -> None:
        """Enable/disable automatic quality + present policy (on by default).

        When enabled, starts at the aspirational rung (high @ 60) and may step
        the ladder based on measured CPU frame work. Manual
        ``canvas.fx_quality`` / ``canvas.framerate`` (and their shortcuts) disable Auto.

        ``params`` is an optional :class:`~scena.fx_auto.AutoParams` override
        (labs / A/B of hysteresis); ignored when disabling.
        """
        if not enabled:
            self._fx_auto = False
            self._fx_auto_ctrl = None
            return
        from .fx_auto import FxAutoController

        r = float(refresh_hz) if refresh_hz is not None else float(self._monitor_refresh_hz)
        if r <= 0:
            r = 60.0
        self._monitor_refresh_hz = r
        ctrl = FxAutoController(refresh_hz=r, params=params)
        rung = ctrl.reset_to_aspirational()
        self._fx_auto_ctrl = ctrl
        self._fx_auto = True
        self._apply_auto_rung(rung)
        # Construct-time enable (no HUD yet) stays silent; Ctrl+Shift+2 flashes.
        if self._system_label is not None:
            self._flash_system_feedback(f"FX Auto: on ({rung.label})")

    def _apply_auto_rung(self, rung) -> None:
        """Apply one ladder rung without disabling Auto.

        Rungs are display-locked (``"vsync60"`` / ``"vsync30"``): the pacer
        implements the interval itself, so the measured FPS tracks the rung
        on every OS (scena/pacing.py).
        """
        self._fx_auto_applying = True
        try:
            self._apply_fx_quality(rung.fidelity)
            self._framerate = rung.framerate
            self.set_glfw_fps()
        finally:
            self._fx_auto_applying = False

    def _valid_glfw_monitor(self, monitor):
        """Return ``monitor`` if non-null; else ``None``.

        pyGLFW may wrap a C NULL as a ctypes object that is not Python
        ``None``; ``get_video_mode`` on that pointer segfaults.
        """
        if monitor is None:
            return None
        try:
            if not monitor:
                return None
        except Exception:
            return None
        try:
            # Explicit address check (ctypes null).
            addr = getattr(monitor, "value", None)
            if addr is None and hasattr(monitor, "__int__"):
                try:
                    addr = int(monitor)
                except Exception:
                    addr = None
            if addr == 0:
                return None
        except Exception:
            pass
        return monitor

    def _read_monitor_refresh_hz(self) -> float:
        """Primary / window monitor refresh; fallback 60.

        Must not crash the process: bad monitor handles can SEGV inside GLFW.
        """
        try:
            monitor = None
            if self._window is not None:
                monitor = self._valid_glfw_monitor(
                    glfw.get_window_monitor(self._window)
                )
            if monitor is None:
                monitor = self._valid_glfw_monitor(glfw.get_primary_monitor())
            if monitor is None:
                return 60.0
            mode = glfw.get_video_mode(monitor)
            if mode is None:
                return 60.0
            rate = float(getattr(mode, "refresh_rate", 0) or 0)
            return rate if rate > 1.0 else 60.0
        except Exception:
            return 60.0

    def _sync_monitor_refresh(self) -> None:
        """Refresh monitor Hz; rebuild Auto ladder if it changed."""
        r = self._read_monitor_refresh_hz()
        if abs(r - self._monitor_refresh_hz) < 0.5:
            return
        self._monitor_refresh_hz = r
        if self._fx_auto and self._fx_auto_ctrl is not None:
            self._fx_auto_ctrl.set_refresh_hz(r)
            self._apply_auto_rung(self._fx_auto_ctrl.current_rung())
        else:
            self.set_glfw_fps()

    def _refresh_fidelity_sensitive_visuals(self) -> None:
        """Re-run ``visual._apply`` for fidelity-sensitive looks; recompose stamps."""
        registry = None
        for holder in (self._scena_draw, self._canvas):
            if holder is None:
                continue
            registry = getattr(holder, "registry", None)
            if registry is not None:
                break
        if registry is None:
            return
        layers = getattr(registry, "layers", None)
        if layers is None:
            return
        try:
            iter_layers = layers.iter_draw_order()
        except Exception:
            return
        from .stamps import capture_stamp_bases, sync_stamp_filters, has_any_stamp
        for layer in iter_layers:
            for obj in getattr(layer, "_objects", ()) or ():
                vis = getattr(obj, "visual", None)
                if vis is not None and getattr(vis, "_fidelity_sensitive", False):
                    reapply = getattr(obj, "_reapply_visual", None)
                    if callable(reapply):
                        reapply()
                    else:
                        apply = getattr(vis, "_apply", None)
                        if callable(apply):
                            apply(obj)
                            if hasattr(obj, "_stamp_base_ff"):
                                capture_stamp_bases(obj)
                                sync_stamp_filters(obj)
                elif has_any_stamp(obj):
                    # Shadow drops at low; glow ImageFilter path may change.
                    sync_stamp_filters(obj)

    @property
    def post_fx_stack(self):
        """Lazy :class:`~scena.postfx.PostFxStack` for ``canvas.effects``."""
        if self._post_fx_stack is None:
            from .postfx import PostFxStack
            self._post_fx_stack = PostFxStack()
        return self._post_fx_stack

    @property
    def fx_quality(self):
        return self._fx_quality

    @fx_quality.setter
    def fx_quality(self, value) -> None:
        self._apply_fx_quality(value)

    # --- system HUD / framework shortcuts --------------------------------------

    # SCENA WARNING banner (view space, above the FPS line). Opaque dark-amber
    # plate + light ink so the message stays readable on any scene. Author
    # errors never reach it — they raise.
    _HUD_INFO_INTERVAL_S = 0.1  # wall-clock seconds between stats-line rebuilds
    _ERROR_HUD_Y = 42.0
    _WARN_HUD_FG = (1.0, 0.97, 0.88, 1.0)
    _WARN_HUD_BG = (0.42, 0.28, 0.04, 1.0)

    def _flash_system_feedback(self, message: str) -> None:
        """Show a short system message on the shared HUD label."""
        self._feedback_text = message
        self._feedback_until = time.perf_counter() + self._feedback_duration
        self._apply_system_label_text(message)

    def _live_label(self, name: str):
        """The framework HUD label ``name``, or None when it is missing or
        destroyed (``is_alive`` is False; a hard registry wipe — e.g. a test's
        ``destroy_all()`` — reaches it too). A frame must not fail on a dead HUD label (bug O3);
        ``_build_system_labels`` makes new ones at the next game start."""
        label = getattr(self, name, None)
        if label is None or getattr(label, "is_alive", True) is False:
            return None
        return label

    def _apply_system_label_text(self, text: str) -> None:
        label = self._live_label("_system_label")
        if label is None:
            return
        label.text = text
        label.visible = True

    def _refresh_error_label(self) -> None:
        """Show or hide the view-space SCENA WARNING banner (above FPS)."""
        label = self._live_label("_error_label")
        if label is None:
            return
        from .process import last_author_error
        err = last_author_error()
        if err is None:
            label.visible = False
            return
        message = err.get("message", "")
        count = err.get("count", 1)
        text = f"SCENA WARNING  {message}"
        if count > 1:
            text = f"{text}  (×{count})"
        text = f"{text}  [Ctrl+Shift+E dismiss]"
        label.text = text
        label.visible = True

    def _dismiss_author_error(self) -> None:
        from .process import clear_author_error, last_author_error
        prev = last_author_error()
        clear_author_error()
        self._refresh_error_label()
        kind = "WARNING" if (prev and prev.get("severity") == "warning") else "ERROR"
        self._flash_system_feedback(f"SCENA {kind} dismissed")

    def _tick_leak_detector(self) -> None:
        """Sample registry/graph sizes on wall-clock cadence; warn via SCENA WARNING.

        Non-sample frames pay only a time comparison inside ``LeakSampler.advance``.
        """
        sampler = self._leak_sampler
        now = self.clock.real_time if self.clock is not None else None
        if not sampler.advance(now):
            return
        from .state import get_scena_system
        ss = get_scena_system()

        def count() -> Tuple[int, int]:
            graph_nodes = len(ss.dependency_graph.nodes) if ss else 0
            return self._count_registry_objects(), graph_nodes

        def recount() -> Tuple[int, int]:
            # Only before a new warning: a full collection is a few ms.
            gc.collect()
            return count()

        hit = sampler.sample(*count(), recount=recount)
        if hit is None:
            return
        _kind, message = hit
        from .process import report_author_warning
        report_author_warning("leak-detector", message)

    def _count_registry_objects(self) -> int:
        if self._scena_draw is None:
            return 0
        from .shapes import Point
        n = 0
        for layer in self._scena_draw.registry.layers.iter_draw_order():
            for obj in layer._objects:
                # ``None`` is a removal hole (tombstone) until compact().
                if obj is not None and not isinstance(obj, Point):
                    n += 1
        return n

    def _system_info_text(self) -> str:
        from .state import get_scena_system
        ss = get_scena_system()
        graph_nodes = len(ss.dependency_graph.nodes) if ss else 0
        fps = self.clock.fps
        if self._fx_auto and self._fx_auto_ctrl is not None:
            tgt = max(1.0, float(self._fx_auto_ctrl.current_rung().present_hz))
            parts = [f"FPS: {fps:.0f}/{tgt:.0f}"]
        else:
            parts = [f"FPS: {fps:.0f}"]
        parts.extend(
            [
                f"objs: {self._count_registry_objects()}",
                f"graph: {graph_nodes}",
            ]
        )
        if self._fx_auto and self._fx_auto_ctrl is not None:
            rung = self._fx_auto_ctrl.current_rung()
            parts.append(f"auto:{rung.label}")
            ctrl = self._fx_auto_ctrl
            if ctrl._ema_ready:
                parts.append(f"work:{ctrl.ema_ms:.1f}/{ctrl.net_budget_ms():.1f}ms")
            if ctrl.slip_rate > 0.0:
                parts.append(f"slip:{100.0 * ctrl.slip_rate:.1f}%")
        mx = getattr(self.mouse, "x", 0.0) if self.mouse is not None else 0.0
        my = getattr(self.mouse, "y", 0.0) if self.mouse is not None else 0.0
        parts.append(f"xy: {mx:.0f}, {my:.0f}")
        if self._debug_zoom_active:
            pct = int(round(float(self._debug_zoom) * 100.0))
            parts.append(f"zoom:{pct}%")
        if self._debug_time_step == 1:
            parts.append("time:pause")
        elif self._debug_time_step == 2:
            parts.append("time:1/4")
        return "  ".join(parts)

    def _refresh_system_label(self, *, force: bool = False) -> None:
        """Update the shared system label (feedback wins over FPS info)."""
        label = self._live_label("_system_label")
        if label is None:
            return

        now = time.perf_counter()
        if self._feedback_until and now < self._feedback_until:
            # Feedback still active; leave text alone unless force replaces it.
            if force and self._feedback_text:
                self._apply_system_label_text(self._feedback_text)
            return

        if self._feedback_until and now >= self._feedback_until:
            self._feedback_until = 0.0
            self._feedback_text = None
            force = True

        if not self._show_system_info:
            label.visible = False
            return

        last = self._last_hud_info_time
        if not force and last is not None and (now - last) < self._HUD_INFO_INTERVAL_S:
            return
        self._last_hud_info_time = now
        self._apply_system_label_text(self._system_info_text())

    def _apply_render_profile(self, index: int) -> str:
        from .fx_quality import RENDER_PROFILES
        profile = RENDER_PROFILES[index % len(RENDER_PROFILES)]
        self._render_profile_index = index % len(RENDER_PROFILES)
        # Quality apply owns scales + batch_shared_filters.
        self.fx_quality = profile.quality
        return profile.label

    def _cycle_render_profile(self) -> None:
        from .fx_quality import RENDER_PROFILES
        nxt = (self._render_profile_index + 1) % len(RENDER_PROFILES)
        label = self._apply_render_profile(nxt)
        self._flash_system_feedback(f"Quality: {label}")

    @property
    def display(self) -> str:
        return self._display_mode

    @display.setter
    def display(self, value) -> None:
        self._apply_display_mode(coerce_display_mode(value))

    def _lock_aspect(self) -> None:
        if self._window is None:
            return
        glfw.set_window_aspect_ratio(
            self._window, int(self.design_width), int(self.design_height)
        )

    def _drop_aspect_lock(self) -> None:
        if self._window is None:
            return
        glfw.set_window_aspect_ratio(self._window, glfw.DONT_CARE, glfw.DONT_CARE)

    def _window_monitor(self):
        """Monitor for this window. Windowed windows have no exclusive monitor.

        pyGLFW wraps C NULL as a ctypes object that is not Python ``None``;
        passing that to ``get_monitor_workarea`` / ``get_video_mode`` SIGSEGVs.
        """
        if self._window is not None:
            mon = self._valid_glfw_monitor(glfw.get_window_monitor(self._window))
            if mon is not None:
                return mon
            try:
                wx, wy = glfw.get_window_pos(self._window)
                ww, wh = glfw.get_window_size(self._window)
                cx, cy = wx + ww * 0.5, wy + wh * 0.5
                for m in glfw.get_monitors() or ():
                    m = self._valid_glfw_monitor(m)
                    if m is None:
                        continue
                    mx, my = glfw.get_monitor_pos(m)
                    mode = glfw.get_video_mode(m)
                    if mode is None:
                        continue
                    if (
                        mx <= cx < mx + mode.size.width
                        and my <= cy < my + mode.size.height
                    ):
                        return m
            except Exception:
                pass
        return self._valid_glfw_monitor(glfw.get_primary_monitor())

    def _os_maximized(self) -> bool:
        if self._window is None:
            return False
        return bool(glfw.get_window_attrib(self._window, glfw.MAXIMIZED))

    def _capture_windowed_geom(self) -> None:
        if self._window is None:
            return
        if self._applying_display:
            return
        if self._display_mode != DISPLAY_WINDOWED:
            return
        if self._os_maximized():
            return
        self._windowed_geom = (
            *glfw.get_window_pos(self._window),
            *glfw.get_window_size(self._window),
        )

    def _restore_windowed_geom(self) -> None:
        if self._window is None:
            return
        glfw.set_window_attrib(self._window, glfw.DECORATED, True)
        self._lock_aspect()
        x, y, w, h = self._windowed_geom or (
            100, 100, self.window_width, self.window_height
        )
        glfw.set_window_monitor(
            self._window, None, int(x), int(y), int(w), int(h), 0
        )

    def _enter_borderless_fullscreen(self) -> None:
        glfw.set_window_attrib(self._window, glfw.DECORATED, False)
        self._drop_aspect_lock()
        monitor = self._window_monitor()
        if monitor is None:
            return
        mx, my = glfw.get_monitor_pos(monitor)
        mode = glfw.get_video_mode(monitor)
        if mode is None:
            return
        mw, mh = int(mode.size.width), int(mode.size.height)
        glfw.set_window_monitor(self._window, None, int(mx), int(my), mw, mh, 0)

    def _apply_display_mode(self, target: str) -> None:
        """Absolute writer for windowed / maximized / fullscreen."""
        target = coerce_display_mode(target)
        if self._window is None:
            self._display_mode = target
            return
        if target == self._display_mode:
            return

        prev = self._display_mode
        self._applying_display = True
        try:
            if prev == DISPLAY_WINDOWED:
                self._capture_windowed_geom()
            if prev == DISPLAY_FULLSCREEN and target != DISPLAY_FULLSCREEN:
                glfw.set_window_attrib(self._window, glfw.DECORATED, True)

            if target == DISPLAY_FULLSCREEN:
                if prev != DISPLAY_FULLSCREEN:
                    self._display_before_fullscreen = prev
                self._enter_borderless_fullscreen()
                self._display_mode = DISPLAY_FULLSCREEN
            elif target == DISPLAY_MAXIMIZED:
                self._drop_aspect_lock()
                if prev == DISPLAY_FULLSCREEN:
                    # Leave F first so maximize sees a decorated window.
                    self._restore_windowed_geom()
                    self._drop_aspect_lock()
                if not self._os_maximized():
                    glfw.maximize_window(self._window)
                self._display_mode = DISPLAY_MAXIMIZED
            else:
                if prev == DISPLAY_MAXIMIZED or self._os_maximized():
                    glfw.restore_window(self._window)
                self._restore_windowed_geom()
                self._display_mode = DISPLAY_WINDOWED

            self._sync_after_window_mode_change()
        finally:
            self._applying_display = False

    def _toggle_fullscreen(self) -> None:
        """Ctrl+Shift+F: toggle real fullscreen (full monitor + letterbox)."""
        if self._display_mode == DISPLAY_FULLSCREEN:
            restore = self._display_before_fullscreen or DISPLAY_WINDOWED
            self._apply_display_mode(restore)
            self._flash_system_feedback("Fullscreen: off")
            return
        self._display_before_fullscreen = self._display_mode
        self._apply_display_mode(DISPLAY_FULLSCREEN)
        self._flash_system_feedback("Fullscreen: on")

    def _toggle_maximize(self) -> None:
        """Ctrl+Shift+M: toggle OS maximize (work area + letterbox)."""
        if self._display_mode == DISPLAY_FULLSCREEN:
            self._display_before_fullscreen = DISPLAY_MAXIMIZED
            self._apply_display_mode(DISPLAY_MAXIMIZED)
            self._flash_system_feedback("Maximized: on")
            return
        if self._display_mode == DISPLAY_MAXIMIZED:
            self._apply_display_mode(DISPLAY_WINDOWED)
            self._flash_system_feedback("Maximized: off")
            return
        self._apply_display_mode(DISPLAY_MAXIMIZED)
        self._flash_system_feedback("Maximized: on")

    def _handle_window_maximize(self, window, maximized) -> None:
        """Title-bar Maximize/Restore takes the same letterbox path as M."""
        if self._applying_display or self._display_mode == DISPLAY_FULLSCREEN:
            return
        if maximized:
            if self._display_mode == DISPLAY_WINDOWED:
                self._capture_windowed_geom()
            self._drop_aspect_lock()
            self._display_mode = DISPLAY_MAXIMIZED
        else:
            self._lock_aspect()
            self._display_mode = DISPLAY_WINDOWED
        self._sync_after_window_mode_change()

    def _sync_after_window_mode_change(self) -> None:
        """Resync metrics + Skia surfaces after fullscreen / restore / maximize."""
        # Drain pending size events before reading metrics.
        glfw.poll_events()
        self._sync_window_and_framebuffer_metrics()
        if self.fb_width <= 0 or self.fb_height <= 0:
            return
        GL.glViewport(0, 0, self.fb_width, self.fb_height)
        if self._context is not None:
            self._scene_surface = None
            self._fx_surface = None
            self._fx_surface2 = None
            self._create_drawing_surface()
            if self._scena_draw is not None:
                self._scena_draw.rebind(
                    self._drawing_canvas, pixel_ratio=self.pixel_ratio
                )
            if self.widget_manager is not None:
                self.widget_manager.widget_theme.pixel_ratio = self.pixel_ratio

    def _toggle_system_info(self) -> None:
        self._show_system_info = not self._show_system_info
        state = "on" if self._show_system_info else "off"
        self._flash_system_feedback(f"System info: {state}")
        if self._show_system_info:
            # After feedback expires, force a fresh stats line.
            self._last_hud_info_time = None

    def _cycle_framerate(self) -> None:
        self._disable_fx_auto_if_manual()
        cur = self._framerate
        i = FRAMERATE_CYCLE.index(cur) if cur in FRAMERATE_CYCLE else -1
        self._framerate = FRAMERATE_CYCLE[(i + 1) % len(FRAMERATE_CYCLE)]
        self.set_glfw_fps()
        self._flash_system_feedback(
            "Framerate: " + framerate_label(self._framerate, self._monitor_refresh_hz))

    def _toggle_fx_auto(self) -> None:
        if self._fx_auto:
            self.set_fx_auto(False)
            self._flash_system_feedback("FX Auto: off")
        else:
            if self._window is not None:
                self._monitor_refresh_hz = self._read_monitor_refresh_hz()
            self.set_fx_auto(True)

    def _sync_debug_zoom_to_canvas(self) -> None:
        """Mirror the bool flag onto ScenaCanvas for the cull hot path."""
        if self._scena_draw is not None:
            self._scena_draw._debug_zoom_active = self._debug_zoom_active

    def _set_debug_zoom(self, scale: float) -> None:
        """Set inspector zoom; ``1.0`` clears the active flag (hot-path no-op)."""
        z = float(scale)
        self._debug_zoom = z
        self._debug_zoom_active = z != 1.0
        self._sync_debug_zoom_to_canvas()

    def _cycle_debug_zoom(self) -> None:
        """Cycle debug zoom: 100% → 50% → 25% → 100%."""
        ladder = (1.0, 0.5, 0.25)
        try:
            idx = ladder.index(float(self._debug_zoom))
        except ValueError:
            idx = 0
        nxt = ladder[(idx + 1) % len(ladder)]
        self._set_debug_zoom(nxt)
        pct = int(round(nxt * 100.0))
        self._flash_system_feedback(f"Debug zoom: {pct}%")

    def _toggle_overlay_pack(self) -> None:
        """Toggle inspect overlay pack: colliders + view quad + origin cross."""
        if self._overlay_pack:
            self._overlay_pack = False
            if self.collision_system is not None:
                self.collision_system.show_colliders(False)
            self._show_system_info = self._hud_before_overlay_pack
            self._flash_system_feedback("Overlays: off")
            if self._show_system_info:
                self._last_hud_info_time = None
            return

        self._overlay_pack = True
        self._hud_before_overlay_pack = self._show_system_info
        self._show_system_info = True
        if self.collision_system is not None:
            self.collision_system.show_colliders(True)
        self._flash_system_feedback("Overlays: on")

    def _cycle_debug_time(self) -> None:
        """Cycle world time: run → pause → ¼ → run (restores author scale)."""
        if self.clock is None:
            self._flash_system_feedback("Time: unavailable")
            return
        step = self._debug_time_step
        if step == 0:
            # Entering debug time cycle: remember author scale.
            saved = float(self.clock.scale)
            if saved <= 0.0:
                saved = float(getattr(self.clock, "_scale_before_pause", 1.0) or 1.0)
            if saved <= 0.0:
                saved = 1.0
            self._debug_time_saved_scale = saved
            self.clock.paused = True
            self._debug_time_step = 1
            self._flash_system_feedback("Time: pause")
        elif step == 1:
            self.clock.scale = 0.25
            self._debug_time_step = 2
            self._flash_system_feedback("Time: 1/4")
        else:
            restore = self._debug_time_saved_scale
            if restore <= 0.0:
                restore = 1.0
            self.clock.scale = restore
            self._debug_time_step = 0
            self._flash_system_feedback("Time: run")

    def _close_vetoed(self) -> bool:
        guard = self._close_guard
        return guard is not None and guard() is False

    def _quit_framework(self) -> None:
        if self._close_vetoed():
            return
        self._running = False

    def _handle_window_close(self, window) -> None:
        if self._close_vetoed():
            glfw.set_window_should_close(window, False)

    def _handle_framework_shortcut(self, key, action, mods) -> bool:
        """Handle Ctrl+Shift framework shortcuts (quality, HUD, inspect).

        Returns True if consumed. Digit + letter keys (not F1–F7 function keys):
        F1–F7 are often claimed by the OS / keyboard firmware, especially on macOS.
        """
        if action != glfw.PRESS:
            return False
        if not ((mods & glfw.MOD_CONTROL) and (mods & glfw.MOD_SHIFT)):
            return False

        handlers = {
            glfw.KEY_1: self._toggle_system_info,
            glfw.KEY_2: self._toggle_fx_auto,
            glfw.KEY_3: self._cycle_render_profile,
            glfw.KEY_4: self._cycle_framerate,
            # KEY_5 / KEY_6 unused (points/handles are per-shape APIs only).
            glfw.KEY_7: self._toggle_overlay_pack,
            glfw.KEY_8: self._cycle_debug_zoom,
            glfw.KEY_E: self._dismiss_author_error,
            glfw.KEY_P: self._cycle_debug_time,
            glfw.KEY_F: self._toggle_fullscreen,
            glfw.KEY_M: self._toggle_maximize,
            glfw.KEY_Z: self._quit_framework,
        }
        handler = handlers.get(key)
        if handler is None:
            return False
        handler()
        return True

    def _offscreen_surface(self, w: int, h: int):
        """Offscreen RGBA surface: a GPU RT, or raster when there is no GL context.

        No context = headless (tests, ``make_guia_thumbs.py``): post FX still
        draw, on the CPU, through the same code path as a window.
        """
        info = skia.ImageInfo.Make(
            w, h,
            skia.kRGBA_8888_ColorType,
            skia.kPremul_AlphaType,
            skia.ColorSpace.MakeSRGB(),
        )
        if self._context is None:
            return skia.Surface.MakeRaster(info)
        return skia.Surface.MakeRenderTarget(self._context, skia.Budgeted.kYes, info)

    def _ensure_scene_surface(self):
        """Offscreen RT matching the window framebuffer (for post_draw)."""
        w, h = int(self.fb_width), int(self.fb_height)
        surf = self._scene_surface
        if surf is not None and surf.width() == w and surf.height() == h:
            return surf
        self._scene_surface = self._offscreen_surface(w, h)
        if self._scene_surface is None:
            raise RuntimeError("Failed to create scene render target for post_draw")
        return self._scene_surface

    def _ensure_fx_surface(self, width: int, height: int):
        """Offscreen RT for reduced-resolution post FX (bloom/blur/haze/…)."""
        w, h = max(1, int(width)), max(1, int(height))
        surf = self._fx_surface
        if surf is not None and surf.width() == w and surf.height() == h:
            return surf
        self._fx_surface = self._offscreen_surface(w, h)
        if self._fx_surface is None:
            raise RuntimeError("Failed to create post-FX render target")
        return self._fx_surface

    def _ensure_fx_surface2(self, width: int, height: int):
        """Second low-res RT. Keeps a snapshot of the first surface alive."""
        w, h = max(1, int(width)), max(1, int(height))
        surf = self._fx_surface2
        if surf is not None and surf.width() == w and surf.height() == h:
            return surf
        self._fx_surface2 = self._offscreen_surface(w, h)
        if self._fx_surface2 is None:
            raise RuntimeError("Failed to create post-FX render target")
        return self._fx_surface2

    def _init_skia(self):
        self._context = skia.GrDirectContext.MakeGL()
        self._create_drawing_surface()

    def _create_drawing_surface(self):
        """(Re)create Skia surface matching the current OpenGL framebuffer."""
        backend_render_target = skia.GrBackendRenderTarget(
            self.fb_width,
            self.fb_height,
            0,
            self._window_stencil_bits(),
            skia.GrGLFramebufferInfo(0, GL.GL_RGBA8)
        )

        self._drawing_surface = skia.Surface.MakeFromBackendRenderTarget(
            self._context,
            backend_render_target,
            skia.kBottomLeft_GrSurfaceOrigin,
            skia.kRGBA_8888_ColorType,
            skia.ColorSpace.MakeSRGB()
        )

        if not self._drawing_surface:
            raise RuntimeError("Failed to create Skia surface")

        self._drawing_canvas = self._drawing_surface.getCanvas()
        if self._scena_draw is not None:
            self._scena_draw.skia_canvas = self._drawing_canvas
        self._apply_view_transform()

    def _handle_window_resize(self, window, width, height):
        if width <= 0 or height <= 0:
            return
        self._sync_window_and_framebuffer_metrics()
        self._capture_windowed_geom()

    def _handle_window_pos(self, window, x, y):
        self._capture_windowed_geom()

    def _handle_framebuffer_resize(self, window, fb_w, fb_h):
        if fb_w <= 0 or fb_h <= 0:
            return
        self._sync_window_and_framebuffer_metrics()
        GL.glViewport(0, 0, self.fb_width, self.fb_height)
        if self._context is not None:
            self._scene_surface = None  # recreate at new FB size
            self._fx_surface = None
            self._fx_surface2 = None
            self._create_drawing_surface()

    def _init_scenacanvas(self, skia_canvas, pixel_ratio=1.0):
        self.widget_manager = WidgetManager(pixel_ratio)
        self.canvas_manager = CanvasManager()

        # ScenaCanvas uses design size (stable authored coordinates).
        self._scena_draw = ScenaCanvas(
            skia_canvas=skia_canvas,
            background_color=(0.0, 0.0, 0.0),
            width=self.design_width,
            height=self.design_height,
            pixel_ratio=pixel_ratio,
        )
        self._scena_draw.shape_fx_scale = float(self.shape_fx_scale)
        self._scena_draw.batch_shared_filters = bool(self.batch_shared_filters)
        self._canvas = Canvas(self._scena_draw)
        self.shape_manager = ShapeInteractionManager(self._scena_draw.registry)
        from .collision import get_collision_system
        self.collision_system = get_collision_system()

        builtins.canvas = self._canvas
        builtins.group = GroupOperator(self._scena_draw.registry)
        builtins.ready = ReadyManager()
        builtins.recently = RememberedManager()

    def _create_raster_surface(self):
        """(Re)create the in-memory (CPU) Skia surface used before a real OS
        window exists, sized to the current design space.
        """
        self._raster_surface = skia.Surface(int(self.design_width), int(self.design_height))
        return self._raster_surface

    def bootstrap(self, width=None, height=None, title=None, *,
                  window_scale=None, display=None, ui_scale=None, ui_font=None):
        """Set up the design space, canvas, state, and widget system -- without
        opening an OS window.

        Called automatically on `import scena` with no arguments (framework
        defaults apply). Scripts that need a specific design size -- e.g.
        because they read `canvas.width` / `canvas.height` before calling
        run(), like a layout computed relative to the canvas -- must call
        this explicitly (via the module-level `init()`) with their own
        values, as the first statement after `from scena import *` and
        before creating any shapes. Window size/title can only be configured
        here; run() does not take size arguments, so there is exactly one
        place in a script that decides them.

        ``width`` / ``height`` are design space, not OS pixels.
        ``window_scale`` is the fraction of the largest windowed window that
        fits the work area (default 0.8), consumed at ``open_window()``.
        ``display`` writes ``canvas.display`` (``"windowed"`` /
        ``"maximized"`` / ``"fullscreen"``).

        ``ui_scale`` / ``ui_font`` write widget chrome (``ui.scale`` / ``ui.font``)
        when passed; omitted leaves the current values (import-time defaults
        are scale 1 and platform UI font). Same as assigning those properties
        before constructing widgets. ``ui.min_label_space`` is assignment-only
        and is also left alone.

        Safe to call more than once before run(): if the design size
        actually changes, the existing canvas is resized/rebound in place
        (not replaced), so the `canvas` / `obj` / `group` builtins and any
        shapes already constructed keep their identity and stay valid.
        """
        if ui_scale is not None:
            ui.scale = ui_scale
        if ui_font is not None:
            ui.font = ui_font
        if width is not None:
            self.design_width = float(width)
        if height is not None:
            self.design_height = float(height)
        self.width = self.design_width
        self.height = self.design_height

        if title is not None:
            self.title = title
        scale = window_scale
        if scale is not None:
            s = float(scale)
            if s <= 0.0:
                raise ValueError("window_scale must be > 0")
            self.window_scale = s
        if display is not None:
            self.display = display

        if self._scena_draw is None:
            self._create_raster_surface()
            self._init_scenacanvas(self._raster_surface.getCanvas(), pixel_ratio=1.0)
        elif not self._windowed:
            # Re-bootstrap before any real window exists (e.g. an explicit
            # init(width=.., height=..) call after the automatic import-time
            # bootstrap ran with defaults): resize/rebind in place.
            self._create_raster_surface()
            self._scena_draw.rebind(
                skia_canvas=self._raster_surface.getCanvas(),
                width=self.design_width,
                height=self.design_height,
                pixel_ratio=1.0,
            )

        self.initialized = True

    # Keyboard and Mouse handling ------------------------------------------------------------------------

    def _handle_char(self, window, char_num):
        char = chr(char_num)
        if not self.widget_manager.handle_char(char) and not self.widget_manager._modal_consumes():
            self.canvas_manager.handle_char(char)

    def _handle_key(self, window, key, scancode, action, mods):
        # Framework-wide Ctrl+Shift shortcuts (quality, HUD, debug overlays, quit).
        if self._handle_framework_shortcut(key, action, mods):
            return
            
        # Convert GLFW key to friendly name. A key Scena cannot name (numpad,
        # Caps Lock, GLFW_KEY_UNKNOWN) is dropped — never a raw code like "46".
        key_name = get_glfw_key_name(key)
        if key_name is None:
            return
        # Scripts compare this. Widgets keep the plain physical name.
        script_key = KeyName(self.keys._script_key_name(key_name))
        modal = self.widget_manager._modal_consumes()
        self.widget_manager._key_mods = mods
        
        wm = self.widget_manager

        # Release always reaches keyp, even when a focused widget claimed the
        # press — otherwise the key sticks. The up goes where the down went.
        if action == glfw.RELEASE:
            self.keys._release(key_name)
            if key_name in wm._claimed_down:
                wm._claimed_down.discard(key_name)
                wm.handle_key_up(key_name)
            elif not modal:
                self.canvas_manager.handle_key_up(script_key)
            return
        if action not in (glfw.PRESS, glfw.REPEAT):
            return

        # A focused keyboard widget (TextInput) keeps only the keys it claims:
        # its editing keys, keys that type text, its own Primary shortcuts.
        # Everything else (Cmd+S, F-keys, a modifier alone) goes on to keyp and
        # on_key, after the widget commits its pending text.
        if wm.claims_key(key_name, mods):
            if action == glfw.PRESS:
                wm._claimed_down.add(key_name)
                wm.handle_key_down(key_name)
            wm.handle_key(key_name)
            return
        wm.key_leaves_widget(key_name)
        if action == glfw.PRESS:
            self.keys._press(key_name)
        # After _press: delivery reads the held state (a play key only unmodified).
        delivers = not modal and self.keys._delivers_script_key(key_name)
        if action == glfw.PRESS and delivers:
            self.canvas_manager.handle_key_down(script_key)
        if delivers:
            self.canvas_manager.handle_key(script_key)

    def _pointer_from_glfw(self, glfw_x, glfw_y):
        """GLFW window points → (world_x, world_y, view_x, view_y)."""
        world_x, world_y = self.screen_to_world_coords(glfw_x, glfw_y)
        view_x, view_y = self.screen_to_view_coords(glfw_x, glfw_y)
        return world_x, world_y, view_x, view_y

    def _sync_pointer_level(self, *, hover=False):
        """Sample OS cursor into ``mouse`` as level (no ``dx``, no ``on_mouse_move``).

        ``hover=True`` at window open so widgets / ui under the cursor light up
        without treating the sample as author motion.
        """
        if self._window is None:
            return
        glfw_x, glfw_y = glfw.get_cursor_pos(self._window)
        world_x, world_y, view_x, view_y = self._pointer_from_glfw(glfw_x, glfw_y)
        self.mouse._sync_position(world_x, world_y)
        sm = getattr(self, "shape_manager", None)
        if sm is not None:
            # Level sample: a camera pan under a still cursor moves the world
            # pointer; step_hover re-resolves on the change.
            sm.note_pointer((view_x, view_y), (world_x, world_y))
        if hover:
            self.widget_manager.handle_mouse_move(view_x, view_y)
            self.shape_manager.handle_mouse_move(view_x, view_y, ui=True)
            self.shape_manager.handle_mouse_move(world_x, world_y, ui=False)

    def _seed_held_keys_from_os(self):
        """Copy currently-down keys into ``keyp`` without press edges."""
        if self._window is None:
            return
        held = []
        for glfw_key in known_glfw_keys():
            if glfw.get_key(self._window, glfw_key) == glfw.PRESS:
                held.append(get_glfw_key_name(glfw_key))
        self.keys._seed_held(held)

    def _step_hover(self):
        sm = self.shape_manager
        if sm is None:
            return
        wm = self.widget_manager
        widget = None
        modal = False
        if wm is not None:
            widget = wm.pressed_widget or wm.mouse_over_widget
            modal = wm._modal_consumes()
        sm.step_hover(widget, modal)

    def _handle_mouse_move(self, window, glfw_x, glfw_y):
        world_x, world_y, view_x, view_y = self._pointer_from_glfw(glfw_x, glfw_y)
        self.mouse._update_position(world_x, world_y)

        # Widgets + ui Graphics use view space; world shapes use world.
        # A modal widget swallows the rest (no hover or drag on the game).
        self.widget_manager.handle_mouse_move(view_x, view_y)
        if self.widget_manager._modal_consumes():
            return
        self.shape_manager.handle_mouse_move(view_x, view_y, ui=True)
        self.shape_manager.handle_mouse_move(world_x, world_y, ui=False)
        self.canvas_manager.handle_mouse_move(world_x, world_y)

    def _handle_mouse_button(self, window, glfw_button, action, mods):
        glfw_x, glfw_y = glfw.get_cursor_pos(window)
        world_x, world_y = self.screen_to_world_coords(glfw_x, glfw_y)
        view_x, view_y = self.screen_to_view_coords(glfw_x, glfw_y)
        button = get_glfw_mouse_button(glfw_button)

        if action == glfw.PRESS:
            self.mouse._button_down(button, world_x, world_y)
            if not self.widget_manager.handle_mouse_down(view_x, view_y, button):
                if not self.shape_manager.handle_mouse_down(
                    view_x, view_y, button, ui=True
                ):
                    if not self.shape_manager.handle_mouse_down(
                        world_x, world_y, button, ui=False
                    ):
                        self.canvas_manager.handle_mouse_down(
                            world_x, world_y, button, view=(view_x, view_y)
                        )

        elif action == glfw.RELEASE:
            self.mouse._button_up(button)
            to_script = False
            if not self.widget_manager.handle_mouse_up(view_x, view_y, button):
                # Prefer the space that owns the press (ui vs world).
                if self.shape_manager._pressed_shape is not None:
                    if self.shape_manager._press_in_ui:
                        self.shape_manager.handle_mouse_up(
                            view_x, view_y, button, ui=True
                        )
                    else:
                        self.shape_manager.handle_mouse_up(
                            world_x, world_y, button, ui=False
                        )
                elif not self.shape_manager.handle_mouse_up(
                    view_x, view_y, button, ui=True
                ):
                    if not self.shape_manager.handle_mouse_up(
                        world_x, world_y, button, ui=False
                    ):
                        to_script = True
                        self.canvas_manager.handle_mouse_up(
                            world_x, world_y, button, view=(view_x, view_y)
                        )
            if not to_script:
                # Release went to a widget / shape: no script click, stop drag.
                self.canvas_manager.forget_press(button)

    def _handle_mouse_scroll(self, window, xoffset, yoffset):
        glfw_x, glfw_y = glfw.get_cursor_pos(window)
        world_x, world_y = self.screen_to_world_coords(glfw_x, glfw_y)
        view_x, view_y = self.screen_to_view_coords(glfw_x, glfw_y)
        if not self.widget_manager.handle_mouse_scroll(view_x, view_y, xoffset, yoffset):
            # Scroll uses the pressed shape's space (view or world coords unused
            # for rotate_by — only the press ownership matters).
            if not self.shape_manager.handle_mouse_scroll(
                world_x, world_y, xoffset, yoffset
            ):
                self.canvas_manager.handle_mouse_scroll(
                    world_x, world_y, xoffset, yoffset
                )

    def world_to_view_coords(self, world_x, world_y):
        """Map y-up world coords to y-up **view** (design-window) coords.

        ``view = [inspector] · camera · world`` — the same prefix as
        :meth:`_apply_view_transform` / :meth:`screen_to_world_coords`,
        without ``view_scale · flipY``. Identity camera and inspector
        leave the point unchanged. Used by canvas ``*_at`` overlays so
        bursts sit on the sprite after pan/zoom/rotate and debug zoom.
        """
        x, y = float(world_x), float(world_y)
        draw_canvas = self._scena_draw
        if draw_canvas is not None and draw_canvas._camera_active:
            p = draw_canvas._camera_matrix.mapXY(x, y)
            x, y = float(p.x()), float(p.y())
        if self._debug_zoom_active:
            cx = self.design_width * 0.5
            cy = self.design_height * 0.5
            z = float(self._debug_zoom)
            x = cx + z * (x - cx)
            y = cy + z * (y - cy)
        return x, y

    def world_to_view_scale(self) -> float:
        """Uniform length scale of :meth:`world_to_view_coords`.

        ``camera.zoom * inspector.zoom`` (1.0 when both are identity).
        Design-unit overlay radii / heights bake this at spawn.
        """
        s = 1.0
        draw_canvas = self._scena_draw
        if draw_canvas is not None and draw_canvas._camera_active:
            s *= float(draw_canvas._zoom)
        if self._debug_zoom_active:
            s *= float(self._debug_zoom)
        return s

    def world_to_view_rotation(self) -> float:
        """Camera rotation in degrees (0 when the camera is identity)."""
        draw_canvas = self._scena_draw
        if draw_canvas is not None and draw_canvas._camera_active:
            return float(draw_canvas._rotation)
        return 0.0

    def screen_to_view_coords(self, screen_x, screen_y):
        """Convert GLFW window points to y-up **view** (design-window) coords.

        Same units as design size, origin bottom-left of the windowed design
        rectangle. No camera: used for widget hit-testing / layout so HUD stays
        under the cursor after pan/zoom/rotate.
        pixel_ratio is not applied — GLFW cursor is already in window points.
        """
        vs = self.view_scale
        H = self.design_height
        pad_x = self._letterbox_pad_x
        pad_y = self._letterbox_pad_y
        if vs:
            return (screen_x - pad_x) / vs, H - (screen_y - pad_y) / vs
        return screen_x - pad_x, H - (screen_y - pad_y)

    def screen_to_world_coords(self, screen_x, screen_y):
        """Convert GLFW window points to y-up world coords.

        Full map: ``screen = T(pad) · view_scale · flipY · [inspector] · camera · world``
        where ``flipY = T(0, H) · S(1, -1)``.
        pixel_ratio is not applied — GLFW cursor is already in window points.
        When the camera is identity and debug zoom is inactive, this matches
        :meth:`screen_to_view_coords`.
        """
        vs = self.view_scale
        H = self.design_height
        draw_canvas = self._scena_draw
        cam_active = draw_canvas is not None and draw_canvas._camera_active
        if not cam_active and not self._debug_zoom_active:
            return self.screen_to_view_coords(screen_x, screen_y)

        # Build T(pad) · view_scale · flipY · [inspector] · camera, then invert.
        matrix = skia.Matrix()
        matrix.setTranslate(self._letterbox_pad_x, self._letterbox_pad_y)
        scale_m = skia.Matrix()
        scale_m.setScale(vs, vs)
        matrix.preConcat(scale_m)
        flip = skia.Matrix()
        flip.setTranslate(0, H)
        flip.preScale(1, -1)
        matrix.preConcat(flip)
        if self._debug_zoom_active:
            cx = self.design_width * 0.5
            cy = self.design_height * 0.5
            z = float(self._debug_zoom)
            insp = skia.Matrix()
            # T(cx,cy) · S(z) · T(-cx,-cy)
            t_neg = skia.Matrix()
            t_neg.setTranslate(-cx, -cy)
            s = skia.Matrix()
            s.setScale(z, z)
            t_pos = skia.Matrix()
            t_pos.setTranslate(cx, cy)
            insp.setConcat(t_pos, s)
            insp.preConcat(t_neg)
            matrix.preConcat(insp)
        if cam_active:
            matrix.preConcat(draw_canvas._camera_matrix)

        inverse = skia.Matrix()
        if matrix.invert(inverse):
            point = inverse.mapXY(screen_x, screen_y)
            return point.x(), point.y()
        return self.screen_to_view_coords(screen_x, screen_y)

    def open_window(self):
        """Create the real OS window and GPU-backed Skia surface, using
        whatever design width/height/title/window_scale are already
        configured (see bootstrap() / the module-level init()).

        Called by run(); does not take size arguments itself, so window
        sizing has exactly one entry point (init(), before run()).

        Rebinds the existing ScenaCanvas in place (rather than creating a
        new one), so shapes/widgets/state created before run() -- against
        the placeholder raster canvas set up by bootstrap() -- keep working
        unchanged once real drawing begins.
        """
        if not self.initialized:
            self.bootstrap()

        self._init_glfw()

        self.window_width, self.window_height = self._compute_window_size(
            self.design_width, self.design_height, self.window_scale
        )

        self._create_glfw_window()
        self._init_skia()
        # Wallpaper images built before the window: decode now, not on the
        # frame that first shows them.
        from .style import prewarm_pending_images
        prewarm_pending_images()

        # _init_skia() -> _create_drawing_surface() already retargets
        # self._scena_draw.skia_canvas onto the new GL-backed canvas; just
        # bring pixel_ratio (design size is unchanged) up to date too.
        self._scena_draw.rebind(self._drawing_canvas, pixel_ratio=self.pixel_ratio)
        self.widget_manager.widget_theme.pixel_ratio = self.pixel_ratio

        self._windowed = True
        if self._display_mode != DISPLAY_WINDOWED:
            # Create windowed first (insets / scale / center), then enter mode.
            intended = self._display_mode
            self._display_mode = DISPLAY_WINDOWED
            self._apply_display_mode(intended)
        # OS pointer/keys exist now. Seed level (not edges) so @= linked before
        # run() re-pulls before setup() and first draw. Eager: still outside
        # begin_frame_batch.
        self._seed_held_keys_from_os()
        self._sync_pointer_level(hover=True)

    # ---------------------------------------------------------------------------------------------------
                
    def run(self):
        """Start audio, run ``setup()`` + the frame loop, then release resources.

        Cleanup runs however the loop ends — window closed, author code
        raising (the exception propagates unchanged), or Ctrl+C.
        """
        self._running = True

        try:
            from .audio_mixer import get_mixer
            get_mixer().start_device()
        except Exception:
            pass  # environment: no audio output device

        try:
            self._run_loop()
        finally:
            self._running = False
            self._cleanup()

    def _cleanup(self) -> None:
        """Close microphones, stop playback, abandon the GPU context, terminate GLFW.

        Each step is guarded so a failing cleanup never replaces the
        exception that ended ``run()``.
        """
        try:
            from .audio_capture import close_all_microphones
            close_all_microphones()
        except Exception:
            pass
        try:
            from .audio_mixer import get_mixer
            get_mixer().stop_device()
        except Exception:
            pass  # environment: no audio output device

        def abandon_gpu_context():
            if self._context is not None:
                self._context.abandonContext()

        def stop_pacer():
            self._pacer.stop()

        for step in (stop_pacer, thaw_world, abandon_gpu_context, glfw.terminate):
            try:
                step()
            except Exception as e:
                warnings.warn(
                    f"SCENA cleanup: {getattr(step, '__name__', step)} "
                    f"failed: {e!r}",
                    RuntimeWarning,
                    stacklevel=2,
                )

    def _build_system_labels(self) -> None:
        """Framework HUD labels (system info, SCENA WARNING). Built once.

        Framework singletons: marked ``_scena_internal`` so an act change
        never removes them (Act Design, "Framework singletons").
        """
        # Built once per process: headless drivers begin many games. Anything
        # that is not a live Scena label (None, destroyed, a test stub) is
        # replaced.
        if getattr(self._system_label, "is_alive", False) and \
                getattr(self._error_label, "is_alive", False):
            return
        # Shared system HUD caption (FPS info + shortcut feedback). Small + discrete.
        from .text import Text
        from .color import Color
        # Anchors are tops: place each single-line caption, then lift it by its
        # own height so its bottom edge sits on the chrome baseline.
        self._system_label = Text(text="", top_left=(20, 16), font_size=14, stack=False)
        self._system_label.move_by(0, self._system_label.box.height)
        self._system_label.visible = self._show_system_info
        # SCENA WARNING banner sits above the FPS line so smoke top chrome stays free.
        self._error_label = Text(
            text="",
            top_left=(20, self._ERROR_HUD_Y),
            font_size=14,
            color=Color(*self._WARN_HUD_FG),
            background=Color(*self._WARN_HUD_BG),
            stack=False,
        )
        self._error_label.move_by(0, self._error_label.box.height)
        self._error_label.visible = False
        self._last_hud_info_time = None
        if self._show_system_info:
            self._refresh_system_label(force=True)
        self._refresh_error_label()
        object.__setattr__(self._system_label, "_scena_internal", True)
        object.__setattr__(self._error_label, "_scena_internal", True)

    def _begin_game(self, first_act=None) -> None:
        """Everything that runs once at startup, then the top level ends.

        Order (Act Design, "Where the top level ends"): the script ``setup``
        hook, the framework HUD labels, the seal (everything alive now is the
        game), the first act, then the clock origin. Headless drivers call
        this too (``SystemWorld.begin_game``), so tests and ``run()`` share it.
        """
        # Call user setup with the public Canvas facade
        callback_if_exists(self, 'setup', self._canvas)
        self.frame_count = 0

        self._build_system_labels()

        # The top level ends: what is alive now is the game.
        from .act import get_act_manager
        manager = get_act_manager()
        manager._seal(act_mode=first_act is not None)
        if first_act is not None:
            manager.enter_first(first_act)

        # GC policy: the built world is frozen, so play-time GC passes walk
        # only what play creates (scena/gc_policy.py). Before the clock
        # origin: the collect is not a frame.
        freeze_world()

        # Origin the clock after setup / HUD / first act so frame-1 dt is a
        # real step, not time spent building the world.
        self.clock._mark_play_start()


    def _run_loop(self) -> None:
        self._begin_game(self._first_act)
        pacer = self._pacer
        pacer.start()

        # Event Loop
        while self._running and not glfw.window_should_close(self._window):
            current_time = time.perf_counter()
            self._simulate_frame(now=current_time, smooth=pacer.smooth_dt)

            self._draw_frame()

            # Render
            self._drawing_surface.flushAndSubmit()
            # Drop the scene snapshot and SkSL children after the GPU has
            # consumed them, before the next frame draws into the scene RT.
            self._scene_image = None
            stack = self._post_fx_stack
            if stack is not None:
                stack._release_retained_runtime_images()

            # CPU work of this frame (before the present wait), for FX Auto.
            work_ms = (time.perf_counter() - current_time) * 1000.0

            # Pacing (scena/pacing.py): wait for this frame's present slot
            # (display link / timer), swap (blocks under native VSync).
            pacer.wait_for_present()
            glfw.swap_buffers(self._window)
            pacer.presented()

            # FX Auto after the present: it also needs whether this present
            # overran its vblank (the frame did not fit) and the present overhead.
            ctrl = self._fx_auto_ctrl
            if self._fx_auto and ctrl is not None:
                ctrl.note_work_ms(work_ms, slipped=pacer.last_overran)
                ctrl.set_present_overhead_ms(pacer.present_overhead() * 1000.0)
                rung = ctrl.maybe_step(time.perf_counter())
                if rung is not None:
                    self._apply_auto_rung(rung)
                    self._flash_system_feedback(f"FX Auto: {rung.label}")

            self.frame_count += 1

    def _simulate_frame(self, now: Optional[float] = None, dt: Optional[float] = None,
                        smooth=None) -> None:
        """Run the simulation half of one frame (everything before paint).

        The single frame body shared by ``_run_loop`` and headless drivers
        (``tests/system_support.py``), so tests exercise the real order:
        clock → layer scroll → HUD / leak sampler → poll + pointer → ``update`` → processes
        → collision → leave playfield → ``flush`` → pre-draw ticks.

        Clock: ``dt`` (a test / driver step) uses ``clock.advance(dt)`` — not
        capped; otherwise ``clock._tick(now)`` (wall time, clamped to
        ``MAX_FRAME_DT``), with ``now`` defaulting to ``time.perf_counter()``.
        ``smooth`` (the run loop's ``FramePacer.smooth_dt``) snaps the step to
        whole vblank periods when pacing is locked to the display.
        """
        ss = get_scena_system()

        # Frame-consistent reactivity: writes during tick + user update(dt)
        # only mark dirty; one flush() resolves derived geometry, links, and
        # @when before draw. Outside run(), updates stay eager.
        if ss is not None:
            ss.begin_frame_batch()
        try:
            if dt is not None:
                self.clock.advance(dt)
            else:
                # Update clock (this updates dt, time, frame, fps attributes)
                self.clock._tick(time.perf_counter() if now is None else now,
                                smooth=smooth)

            # Layer scroll is world state: integrate it with the clock, before
            # update(dt) and the process tick read layer.view (not in draw).
            self._scena_draw.advance_layer_scroll(self.clock.time)

            # System HUD: feedback timeout + throttled FPS/info refresh.
            self._refresh_system_label()
            self._refresh_error_label()
            self._tick_leak_detector()

            # Poll events (keys / buttons / view-space motion callbacks)
            glfw.poll_events()
            # World pointer is a sample, not only a move callback — still
            # cursor + camera pan with no GLFW motion.
            self._sync_pointer_level()

            # Call user update. The sync watchdog (tight loop → skip frame)
            # is off by default; opt in with set_sync_watchdog(True).
            try:
                _run_with_watchdog(
                    callback_if_exists, self, 'update', clock.dt, self._canvas,
                    sync=True,
                )
            except _Watchdog:
                warnings.warn(
                    f"SCENA ERROR: script update() ran more than "
                    f"{WATCHDOG_RESUME_S:g}s without returning — skipped "
                    f"for this frame (likely a tight loop). Fix the spin "
                    f"or call set_watchdog(False) for benchmarks.\n"
                    f"{traceback.format_exc()}",
                    stacklevel=2,
                )

            # Process tick (tweens, timers, async resume, on_update). After
            # author motion, before collision, so this frame's poses are
            # current and collision handlers may start new timers (first
            # tick next frame).
            tick_processes()

            # Collision step: snapshot → broad/narrow → enter/stay/exit.
            # Runs before flush so @when sees post-collision writes from handlers.
            if self.collision_system is not None:
                self.collision_system.step()

            get_bounds_system().step()

            # Hover level + @hover / @hover_exit edges, once per frame, in the
            # same flush window as collision handlers (Shapes Design, Hover).
            self._step_hover()

            if ss is not None:
                ss.flush()

            # Pre-draw ticks stay inside the batch: their writes (e.g. an
            # author on_done) mark dirty and reach @when at the next
            # frame's flush, like everything else after flush — no eager
            # per-write poll of every event, no second flush.
            self._tick_pre_draw()
        finally:
            # Every reader of this frame has run: unread key edges expire, so
            # keyp.once is True only in the frame of the press (PM3). A press
            # that arrives after this (between frames) is read next frame.
            self.keys._expire_edges()
            if ss is not None:
                ss.end_frame_batch()

    def _tick_pre_draw(self) -> None:
        """Advance paint-side lifecycles after flush, before paint."""
        # Shape-local transients: complete lifecycle before paint (not in draw).
        tick_all_transients()
        # History duration eviction (same pre-draw window as transients).
        tick_all_histories()
        # Canvas cover overlay (fade/wipe/iris). Tick before draw so on_done
        # can swap the act while the hold is already at 1.
        tick_cover()
        # SpatialFx ambient emitters (particles / soft domains).
        tick_all_spatial_fx()

    def _draw_frame(self) -> None:
        """Paint one frame: background → camera view → scene → post → HUD → cover.

        Runs after update / processes / collision / flush / pre-draw ticks, and
        samples the post path once, so background parallax, the camera CTM and
        the scene all use this frame's camera in every path.
        """
        # macOS NSOpenGLContext can reset the viewport after resize / mode
        # changes; re-assert every frame (cheap).
        GL.glViewport(0, 0, self.fb_width, self.fb_height)
        if self._needs_scene_rt():
            # Scene → GPU RT → post → window FB. Widgets stay crisp after.
            self._was_using_post = True
            scene_surf = self._ensure_scene_surface()
            scene_canvas = scene_surf.getCanvas()
            self._draw_background(scene_canvas)
            self._apply_view_transform(scene_canvas)
            top_exempt = self._top_exempt_from_post()
            self._draw_scene_to(scene_canvas, exclude_top=top_exempt)
            scene_image = scene_surf.makeImageSnapshot()
            self._scene_image = scene_image

            self._clear_background_fast(self._drawing_canvas)
            if self._post_draw_live():
                callback_if_exists(
                    self, 'post_draw', self._drawing_canvas, scene_image
                )
            else:
                # Built-in canvas.effects engine
                self.post_fx_stack._render(
                    self._drawing_canvas,
                    scene_image,
                    fw=self,
                    t=self.clock.time,
                )
            # Widgets (and optionally top layer) stay on the window FB.
            self._apply_view_transform()
            if top_exempt:
                self._draw_top_layer(self._drawing_canvas)
        else:
            if self._was_using_post:
                self._recover_direct_fb_path()
                self._was_using_post = False
            # Scene straight onto the window FB.
            self._draw_background(self._drawing_canvas)
            self._apply_view_transform()
            self._scena_draw.draw(t=self.clock.time)
        self._draw_collision_debug(self._drawing_canvas)
        # Widgets + ui Graphics: view space only (no camera) so HUD stays fixed.
        self._apply_view_transform(camera=False)
        self._draw_ui_layer(self._drawing_canvas)
        self.widget_manager.draw(self._drawing_canvas)
        # Cover overlay last (after HUD). Same design CTM as widgets.
        if is_cover_active():
            draw_cover(
                self._drawing_canvas,
                self.design_width,
                self.design_height,
            )

    def set_auto_callbacks(self, namespace):
        # List of all possible callbacks
        execution_callbacks = [
            'setup', 'update', 'post_draw',
        ]

        input_callbacks = [
            'on_key_down', 'on_key_up', 'on_key', 'on_char',
            'on_mouse_down', 'on_mouse_up', 'on_mouse_click', 'on_mouse_double_click', 'on_mouse_move', 'on_mouse_drag', 'on_mouse_scroll'
        ]
        
        # For each callback name, check if it exists in the namespace
        # Setup execution_callbacks in ScenaFramework
        for callback in execution_callbacks:
            if callback in namespace:
                # Set the callback if it exists
                setattr(self, callback, namespace[callback])
        # Setup input_callbacks in CanvasManager
        for callback in input_callbacks:
            if callback in namespace:
                # Set the callback if it exists
                setattr(self.canvas_manager, callback, namespace[callback])

# Global functions for the framework -----------------------------------------------------------

def run(first_act=None):
    """Open the window (using whatever design size/title/window_scale were
    configured via init()) and start the main loop.

    ``run(Titulo)`` starts the game at an act (``class Titulo(Act)``); it is
    built once the top level ends. ``run()`` with no argument has no acts.

    run() does not take width/height/title arguments: window sizing must be
    configured via init(width=.., height=..) *before* calling run(), so a
    script has exactly one place that decides the window's size. This
    matters because code that runs before run() (e.g. layout computed from
    canvas.width/canvas.height) needs the design size to already be final.

    Args:
        first_act: The Act class to start in (``run(Titulo)``); omit for a script
            without acts.
    """
    if first_act is not None:
        # Validate before the window opens: a bad argument changes nothing.
        from .act import _check_act_class
        _check_act_class(first_act, "run")

    fw = ScenaFramework.get_instance()
    fw._first_act = first_act

    if not fw.initialized:
        fw.bootstrap()
    if not fw._windowed:
        fw.open_window()

    # Get the caller's frame and its local variables and set the callbacks
    frame = inspect.currentframe()
    caller_frame = frame.f_back
    caller_globals = caller_frame.f_globals

    fw.set_auto_callbacks(caller_globals)

    # Run the main loop
    fw.run() 

def init(width=None, height=None, title=None, *,
         window_scale=None, display=None, ui_scale=None, ui_font=None):
    """Configure design size, windowed scale, display mode, and widget chrome.

    Does not open an OS window. Called automatically on `import scena` with
    no arguments (framework defaults apply).

    Args:
        width, height: design space (``canvas.width`` / ``canvas.height``,
            default 2000 × 1200), not OS pixels.
        title: OS window title (default ``"Scena"``).
        window_scale: fraction of the largest windowed window that fits the
            work area (default 0.8); consumed at ``open_window()``.
        display: ``"windowed"`` / ``"maximized"`` / ``"fullscreen"`` (sugar
            for ``canvas.display``).
        ui_scale, ui_font: widget chrome (``ui.scale`` / ``ui.font``);
            omitted keeps the current value.

    ``run()`` does not accept size arguments.
    """
    fw = ScenaFramework.get_instance()
    fw.bootstrap(
        width=width, height=height, title=title, window_scale=window_scale,
        display=display, ui_scale=ui_scale, ui_font=ui_font,
    )

def forget_hud_column_item(obj) -> None:
    """Drop ``obj`` from the current HUD column; rewind the cursor if it empties."""
    fw = ScenaFramework.get_instance()
    wm = getattr(fw, "widget_manager", None)
    if wm is None:
        return
    wm._forget_column_item(obj)


def restore_hud_cursor(obj) -> None:
    """A constructor raised: put the HUD cursor back where ``obj`` found it."""
    saved = getattr(obj, "__dict__", {}).pop("_hud_cursor_before", None)
    if saved is not None:
        wm, state = saved
        wm._restore_cursor_state(state)


def unregister_widget(obj) -> None:
    """Drop a widget from the HUD hit/draw lists. Safe on non-widgets."""
    wm = getattr(obj, "_widget_manager", None)
    if wm is None:
        return
    wm.remove_widget(obj)


def set_fx_auto(enabled: bool = True, refresh_hz: float = None, params=None):
    """Enable/disable automatic fidelity + present ladder (on by default).

    When on, measures CPU frame work and may step quality/rate. Manual quality
    or framerate changes disable Auto. See ``scena.fx_auto``.

    Optional ``params`` (:class:`~scena.fx_auto.AutoParams`) overrides
    hysteresis for labs; ignored when ``enabled`` is False.

    Args:
        enabled: Turn FX Auto on (default) or off.
        refresh_hz: Display refresh to plan for; ``None`` = measure it.
        params: Tuning object for labs (``scena.fx_auto.AutoParams``); ignored when off.
    """
    from .validate import expect_bool
    ScenaFramework.get_instance().set_fx_auto(
        expect_bool(enabled, "set_fx_auto enabled"), refresh_hz=refresh_hz, params=params
    )


def set_leak_detector(enabled: bool = True) -> None:
    """Enable/disable the periodic registry/graph leak sampler (on by default).

    Benches that intentionally grow the registry should call ``set_leak_detector(False)``
    so the SCENA WARNING banner stays quiet. Non-sample frames still cost only a
    time comparison when enabled. The sampler warns only on sustained unbounded
    climb (spawn bursts and slot-warmup plateaus stay quiet).
    """
    from .validate import expect_bool
    enabled = expect_bool(enabled, "set_leak_detector enabled")
    sampler = ScenaFramework.get_instance()._leak_sampler
    sampler.enabled = enabled
    if not enabled:
        sampler.reset()


def flush():
    """Resolve pending reactive updates (derived geometry, links, @when).

    The run loop flushes automatically before each draw. Call this if you
    need mid-update derived reads, or after a batch of writes outside run().
    """
    from .state import flush as _flush
    _flush()

