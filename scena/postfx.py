"""
Canvas-wide post-FX engine for Scena.

Authors construct named :class:`PostEffect` instances (``Vignette()``,
``Bloom()``, …); construction appends to ``canvas.effects``. The engine
buckets them by :class:`PostEffectStage` and always composes in a fixed,
validated order (FILTER → ADDITIVE → COLOR → OVERLAY → WARP → SHADER). Quality policy (``post_fx_scale``) is applied inside
the engine — cheap ops stay full-res; fill-rate / blur-bound ops run
at reduced resolution when the hybrid path kicks in.

See ``design/Scena Design.md`` (Effect system) for the measured rationale.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import List, Optional, Sequence

import skia

from .closed import ClosedSurface

from .input import MAX_FRAME_DT as _MAX_FRAME_DT  # the clocks' frame cap


class PostEffectStage(Enum):
    FILTER = "filter"        # replace-style ImageFilter DAG
    ADDITIVE = "additive"    # Plus-blended onto the filtered base
    COLOR = "color"          # ColorFilter matrix
    OVERLAY = "overlay"      # direct canvas draw (Multiply / Plus)
    WARP = "warp"            # full-res DisplacementMap after overlays
    SHADER = "shader"        # compiled-once SkSL RuntimeEffect (last)


def _auto_place_post(effect) -> None:
    """Append ``effect`` to ``canvas.effects`` unless constructed unplaced."""
    from .place import is_unplaced_creation

    if is_unplaced_creation():
        return
    try:
        from .orchestration import ScenaFramework
        stack = ScenaFramework.get_instance().post_fx_stack
    except Exception:
        return
    stack.add(effect)


class PostEffect(ClosedSurface):
    """Base class for a canvas-wide post effect.

    Subclasses set ``stage`` and implement the matching hook. Gradual
    params: constructing with no args must produce a sensible look.
    Construction appends to ``canvas.effects`` (idempotent). Use
    :meth:`temp` or :func:`~scena.place.unplaced_creation` to skip.
    :meth:`remove` detaches from the stack.
    """

    _stage: PostEffectStage = PostEffectStage.FILTER
    # When True, spatial work may run at ``post_fx_scale``; cheap color /
    # grain overlays set this False so they stay full-res.
    _quality_sensitive: bool = True
    # When True on a non-OVERLAY effect, ``_draw_overlay`` is also invoked
    # (e.g. Crt scanlines on the low-res Multiply plate).
    _has_quality_overlay: bool = False
    enabled: bool = True

    def __init__(self):
        _auto_place_post(self)

    def __getitem__(self, key):
        from .closed import no_fields_message
        raise TypeError(no_fields_message(self, key))

    def __init_subclass__(cls, **kwargs):
        if "__init__" in cls.__dict__:
            from .place import wrap_init_autoplace
            wrap_init_autoplace(cls, _auto_place_post)
        # Last: ClosedSurface seals outside the construct-to-place wrapper.
        super().__init_subclass__(**kwargs)

    @classmethod
    def temp(cls, *args, **kwargs):
        """Construct without attaching to ``canvas.effects``."""
        from .place import temp_construct
        return temp_construct(cls, *args, **kwargs)

    def remove(self) -> None:
        """Detach from ``canvas.effects``. Idempotent if not on the stack.

        The Python object remains; :meth:`~PostFxStack.add` puts it back.
        """
        try:
            from .orchestration import ScenaFramework
            stack = ScenaFramework.get_instance().post_fx_stack
        except Exception:
            return
        stack.remove(self)

    def _fx_cache_key(self) -> tuple:
        """Fingerprint for filter-graph memoization."""
        return (type(self).__name__,)

    def _build_filter(self, inp, scale: float = 1.0):
        """FILTER / COLOR: return an ImageFilter (may wrap ``inp``)."""
        return inp

    def _build_additive(self, inp, scale: float = 1.0):
        """ADDITIVE: return an ImageFilter whose output is Plus-blended."""
        return None

    def _build_color_filter(self):
        """COLOR: return a skia.ColorFilter (composed with others)."""
        return None

    def _draw_overlay(self, canvas, w: float, h: float, t: float) -> None:
        """OVERLAY: draw directly onto ``canvas`` (FB or low-res RT)."""
        pass

    def _build_warp_filter(self, w: float, h: float):
        """WARP: return a DisplacementMap (or None if inactive)."""
        return None

    def _draw_shader(self, canvas, image, w: float, h: float, t: float, fw=None) -> None:
        """SHADER: RuntimeEffect pass over ``image`` into ``canvas``."""
        canvas.drawImage(image, 0, 0)

    def _release_resources(self) -> None:
        """Drop retained GPU images / RTs when removed from the stack."""
        pass

    def _discard_feedback(self) -> None:
        """Drop temporal GPU history when this effect is skipped this frame.

        Stateful effects (``MotionTrail`` ping-pong) override this so a mute
        does not flash the previous afterimage on the next active frame.
        """
        pass

    def _is_active(self) -> bool:
        return bool(self.enabled)


class PostFxStack(ClosedSurface):
    """Ordered collection of :class:`PostEffect` instances (``canvas.effects``)."""

    _closed_who = "canvas.effects"

    def __init__(self):
        self._effects: List[PostEffect] = []
        self.enabled: bool = True
        self._hit = None  # lazy HitFeedback singleton
        self._last_ui_t = None  # presentation clock at the last compose
        self._filter_cache_key = None
        self._filter_cache = None
        self._compose_surface = None
        self._mid_surface = None
        self._t0 = time.perf_counter()

    # --- author API --------------------------------------------------------

    def add(self, effect: PostEffect) -> PostEffect:
        """Put a post effect on the screen (``canvas.effects.add(Bloom())``). Already added: nothing changes. Returns the effect."""
        if not isinstance(effect, PostEffect):
            from .validate import family_hint

            hint = family_hint(effect)
            msg = (
                "canvas.effects.add expected a PostEffect "
                f"(Vignette(), Bloom(), …), got {type(effect).__name__}"
            )
            if hint:
                msg = f"{msg}. {hint}"
            raise TypeError(msg)
        if effect not in self._effects:
            self._effects.append(effect)
            self._invalidate()
        return effect

    def remove(self, effect: PostEffect) -> None:
        """Take a post effect off the screen (no-op if it is not on). The object keeps its settings."""
        if effect in self._effects:
            self._effects.remove(effect)
            rel = getattr(effect, "_release_resources", None)
            if callable(rel):
                try:
                    rel()
                except Exception:
                    pass
            self._release_retained_runtime_images()
            self._invalidate()

    def clear(self) -> None:
        """Remove every post effect."""
        for e in self._effects:
            rel = getattr(e, "_release_resources", None)
            if callable(rel):
                try:
                    rel()
                except Exception:
                    pass
        self._effects.clear()
        self._hit = None
        self._release_surfaces()
        self._release_retained_runtime_images()
        self._invalidate()

    def __iter__(self):
        # The author's stack: the impacts' internal HitFeedback (``_hit``) lives
        # in ``_effects`` for the render order but is not one of the author's
        # posts ("Impactos ... não entram nesta pilha", Guia; AC3).
        hit = self._hit
        if hit is None:
            return iter(self._effects)
        return iter([e for e in self._effects if e is not hit])

    def __len__(self) -> int:
        hit = self._hit
        n = len(self._effects)
        if hit is not None and any(e is hit for e in self._effects):
            n -= 1
        return n

    def __bool__(self) -> bool:
        # Agrees with ``len`` / ``list``: the impacts' internal ``_hit`` is not
        # one of the author's posts, so ``if canvas.effects:`` stays False
        # during a shake. The engine's render switch is ``_is_active``.
        if not self.enabled:
            return False
        hit = self._hit
        return any(e._is_active() for e in self._effects if e is not hit)

    @property
    def _is_active(self) -> bool:
        if not self.enabled:
            return False
        return any(e._is_active() for e in self._effects)

    def _hit_feedback(self):
        """Lazy singleton used by ``canvas.flash/shake/glitch/ripple_at/explosion_at/burst_at/bubbles_at/fireworks_at/zap_at/hit_at/debris_at``."""
        if self._hit is None:
            from .effects import HitFeedback
            self._hit = HitFeedback()
            self.add(self._hit)
        return self._hit

    def _invalidate(self) -> None:
        self._filter_cache_key = None
        self._filter_cache = None

    def _discard_skipped_feedback(self, active: Optional[Sequence[PostEffect]] = None) -> None:
        """Drop temporal history on effects skipped this compose (mute / ``enabled``)."""
        keep = None if active is None else {id(e) for e in active}
        for e in self._effects:
            if keep is not None and id(e) in keep:
                continue
            discard = getattr(e, "_discard_feedback", None)
            if callable(discard):
                try:
                    discard()
                except Exception:
                    pass

    def _release_surfaces(self) -> None:
        """Drop cached compose RTs (call when the stack goes idle / cleared)."""
        self._compose_surface = None
        self._mid_surface = None

    def _release_retained_runtime_images(self) -> None:
        """Unlock SkSL child snapshots so GPU cache can purge leftover plates.

        Each RuntimeShaderBuilder keeps the last ``image`` child until replaced.
        Cycling canvas SkSL effects without dropping those children pins one
        full-frame GPU texture per builder; later ALU-heavy washes
        (ColorWash / CosmicBloom) then cliff. Safe to call before a compose:
        this frame's ``_draw_shader`` rebinds, and the previous frame has
        already been flushed.
        """
        try:
            from ._sksl_effects import release_runtime_children
            release_runtime_children()
        except Exception:
            pass
        try:
            from .effects import release_motion_trail_children
            release_motion_trail_children()
        except Exception:
            pass

    # --- render ------------------------------------------------------------

    def _render(self, skia_canvas, scene_image, *, fw, t: Optional[float] = None) -> None:
        """Compose the stack onto ``skia_canvas`` (window FB, y-down pixels)."""
        if t is None:
            t = time.perf_counter() - self._t0
        fb_w = float(fw.fb_width)
        fb_h = float(fw.fb_height)
        scale = float(getattr(fw, "post_fx_scale", 1.0) or 1.0)

        # Unlock leftover RuntimeEffect children from a previous stack
        # (or a prior frame) *before* this compose. Previous frame already
        # flushed; this frame's shaders rebind after ticks.
        self._release_retained_runtime_images()

        # Decay hit-feedback / apply camera shake before composing, on the
        # presentation clock (like the cover and shape transients): on world
        # dt a shake / flash / glitch never ended under ``clock.paused``
        # (review 2026-10-09 X-writers-2, decided). Capped like a frame.
        clk = getattr(fw, "clock", None)
        ui_t = float(getattr(clk, "_ui_time", 0.0) or 0.0)
        last = self._last_ui_t
        self._last_ui_t = ui_t
        dt = 0.0 if last is None else min(max(0.0, ui_t - last), _MAX_FRAME_DT)
        canvas_facade = getattr(fw, "_canvas", None)
        for e in self._effects:
            tick = getattr(e, "tick_frame", None)
            if callable(tick) and canvas_facade is not None:
                tick(dt, canvas_facade)

        skia_canvas.save()
        skia_canvas.resetMatrix()

        if not self._is_active:
            # Identity passthrough — never soft-upscale an empty stack.
            # Mute drops temporal history so the next active frame is clean.
            self._discard_skipped_feedback()
            skia_canvas.drawImage(scene_image, 0, 0)
            skia_canvas.restore()
            return

        active = [e for e in self._effects if e._is_active()]
        self._discard_skipped_feedback(active)
        by_stage = {s: [] for s in PostEffectStage}
        for e in active:
            by_stage[e._stage].append(e)

        warp_filter = None
        for e in by_stage[PostEffectStage.WARP]:
            built = e._build_warp_filter(fb_w, fb_h)
            if built is not None:
                warp_filter = built  # last wins; HitFeedback is typically alone
        want_warp = warp_filter is not None
        want_shader = bool(by_stage[PostEffectStage.SHADER])
        need_wrap = want_warp or want_shader

        if need_wrap:
            surf = self._ensure_compose_surface(fw, fb_w, fb_h)
            target = surf.getCanvas()
            target.clear(skia.ColorBLACK)
            target.save()
            target.resetMatrix()
        else:
            target = skia_canvas

        if scale >= 0.999:
            self._render_full(target, scene_image, fb_w, fb_h, t, by_stage)
        else:
            self._render_hybrid(target, scene_image, fw, fb_w, fb_h, t, scale, by_stage)

        if need_wrap:
            target.restore()
            img = surf.makeImageSnapshot()

            if want_warp:
                paint = skia.Paint(AntiAlias=False)
                warp = warp_filter
                if warp is not None:
                    paint.setImageFilter(warp)
                    if want_shader:
                        mid = self._ensure_mid_surface(fw, fb_w, fb_h)
                        mc = mid.getCanvas()
                        mc.clear(skia.ColorBLACK)
                        mc.drawImage(img, 0, 0, skia.SamplingOptions(), paint)
                        img = mid.makeImageSnapshot()
                    else:
                        skia_canvas.drawImage(img, 0, 0, skia.SamplingOptions(), paint)
                        img = None

            if want_shader and img is not None:
                self._apply_shader_chain(
                    skia_canvas, img, fb_w, fb_h, t, fw, by_stage[PostEffectStage.SHADER]
                )

            # Overlay accents that need the final FB (e.g. ripple ring)
            for e in (
                by_stage[PostEffectStage.WARP]
                + by_stage[PostEffectStage.SHADER]
            ):
                draw_ring = getattr(e, "draw_ring", None)
                if callable(draw_ring):
                    draw_ring(skia_canvas, fb_w, fb_h)

        skia_canvas.restore()

    # --- composition paths -------------------------------------------------

    def _collect_overlays(self, by_stage) -> list:
        """OVERLAY-stage effects, plus SHADER/WARP that opt into ``_draw_overlay``."""
        out = list(by_stage[PostEffectStage.OVERLAY])
        for e in list(by_stage[PostEffectStage.SHADER]) + list(by_stage[PostEffectStage.WARP]):
            if getattr(e, "_has_quality_overlay", False):
                out.append(e)
        return out

    def _render_full(self, canvas, scene_image, fb_w, fb_h, t, by_stage) -> None:
        replace = self._build_replace_filter(by_stage, scale=1.0, phase=t)
        glow = self._build_bloom(by_stage, scale=1.0)
        color_cf = self._compose_color_filters(by_stage)

        filt = replace
        if glow is not None:
            filt = skia.ImageFilters.Xfermode(skia.BlendMode.kPlus, replace, glow)
        if color_cf is not None:
            filt = skia.ImageFilters.ColorFilter(color_cf, filt)

        paint = skia.Paint(AntiAlias=False)
        if filt is not None:
            paint.setImageFilter(filt)
        canvas.drawImage(scene_image, 0, 0, skia.SamplingOptions(), paint)
        for e in self._collect_overlays(by_stage):
            e._draw_overlay(canvas, fb_w, fb_h, t)

    def _render_hybrid(self, canvas, scene_image, fw, fb_w, fb_h, t, scale, by_stage) -> None:
        """Sharp full-res base when possible; low-res for replace / Multiply / bloom."""
        hw = max(1, int(fb_w * scale))
        hh = max(1, int(fb_h * scale))
        linear = skia.SamplingOptions(skia.FilterMode.kLinear)

        overlays = self._collect_overlays(by_stage)
        overlays_low = [e for e in overlays if e._quality_sensitive]
        overlays_full = [e for e in overlays if not e._quality_sensitive]
        replace = self._build_replace_filter(by_stage, scale=scale, phase=t)
        has_bloom = bool(by_stage[PostEffectStage.ADDITIVE])
        need_low = replace is not None or overlays_low or has_bloom

        low_snap = None
        if need_low:
            _, low_snap = self._downsample(fw, scene_image, hw, hh)

        use_low_base = replace is not None or bool(overlays_low)
        color_cf = self._compose_color_filters(by_stage)

        if use_low_base:
            fx = fw._ensure_fx_surface2(hw, hh)
            fc = fx.getCanvas()
            fc.clear(skia.ColorBLACK)
            if replace is not None:
                rp = skia.Paint(AntiAlias=False)
                rp.setImageFilter(replace)
                fc.drawImage(low_snap, 0, 0, skia.SamplingOptions(), rp)
            else:
                fc.drawImage(low_snap, 0, 0)
            for e in overlays_low:
                e._draw_overlay(fc, hw, hh, t)
            base_img = fx.makeImageSnapshot()
            bp = skia.Paint(AntiAlias=False)
            if color_cf is not None:
                bp.setColorFilter(color_cf)
            canvas.drawImageRect(base_img, skia.Rect.MakeWH(fb_w, fb_h), linear, bp)
        else:
            bp = skia.Paint(AntiAlias=False)
            if color_cf is not None:
                bp.setColorFilter(color_cf)
            canvas.drawImage(scene_image, 0, 0, skia.SamplingOptions(), bp)

        if has_bloom and low_snap is not None:
            glow_f = self._build_bloom(by_stage, scale=scale)
            if glow_f is not None:
                fx = fw._ensure_fx_surface2(hw, hh)
                fc = fx.getCanvas()
                fc.clear(skia.ColorBLACK)
                gp = skia.Paint(AntiAlias=False)
                gp.setImageFilter(glow_f)
                fc.drawImage(low_snap, 0, 0, skia.SamplingOptions(), gp)
                glow_img = fx.makeImageSnapshot()
                plus = skia.Paint(AntiAlias=False, BlendMode=skia.BlendMode.kPlus)
                canvas.drawImageRect(
                    glow_img, skia.Rect.MakeWH(fb_w, fb_h), linear, plus
                )

        for e in overlays_full:
            e._draw_overlay(canvas, fb_w, fb_h, t)

    # --- filter builders ---------------------------------------------------

    def _build_replace_filter(self, by_stage, *, scale: float, phase: float):
        filt = None
        for e in by_stage[PostEffectStage.FILTER]:
            if hasattr(e, "set_phase"):
                e.set_phase(phase)
            filt = e._build_filter(filt, scale=scale)
        return filt

    def _build_bloom(self, by_stage, *, scale: float):
        glow = None
        for e in by_stage[PostEffectStage.ADDITIVE]:
            g = e._build_additive(None, scale=scale)
            if g is not None:
                glow = g
        return glow

    def _compose_color_filters(self, by_stage):
        cf = None
        # COLOR-stage effects, plus optional build_color_filter on WARP/SHADER
        # (legacy flash hooks — HitFeedback now flashes in SkSL).
        sources = (
            list(by_stage[PostEffectStage.COLOR])
            + list(by_stage.get(PostEffectStage.WARP, []))
            + list(by_stage.get(PostEffectStage.SHADER, []))
        )
        for e in sources:
            part = e._build_color_filter() if hasattr(e, "_build_color_filter") else None
            if part is None:
                continue
            cf = skia.ColorFilters.Compose(part, cf) if cf else part
        return cf

    def _apply_shader_chain(self, final_canvas, image, w, h, t, fw, shaders: Sequence[PostEffect]):
        if not shaders:
            final_canvas.drawImage(image, 0, 0)
            return
        src = image
        for i, e in enumerate(shaders):
            last = i == len(shaders) - 1
            if last:
                e._draw_shader(final_canvas, src, w, h, t, fw=fw)
            else:
                dst_surf = (
                    self._ensure_mid_surface(fw, w, h)
                    if (i % 2) == 0
                    else self._ensure_compose_surface(fw, w, h)
                )
                dc = dst_surf.getCanvas()
                dc.clear(skia.ColorBLACK)
                e._draw_shader(dc, src, w, h, t, fw=fw)
                src = dst_surf.makeImageSnapshot()

    # --- RT helpers --------------------------------------------------------

    def _downsample(self, fw, scene_image, hw, hh):
        fx = fw._ensure_fx_surface(hw, hh)
        fc = fx.getCanvas()
        fc.clear(skia.ColorBLACK)
        fc.drawImageRect(
            scene_image,
            skia.Rect.MakeWH(hw, hh),
            skia.SamplingOptions(skia.FilterMode.kLinear),
        )
        return fx, fx.makeImageSnapshot()

    def _ensure_compose_surface(self, fw, width, height):
        w, h = max(1, int(width)), max(1, int(height))
        surf = self._compose_surface
        if surf is not None and surf.width() == w and surf.height() == h:
            return surf
        info = skia.ImageInfo.Make(
            w, h,
            skia.kRGBA_8888_ColorType,
            skia.kPremul_AlphaType,
            skia.ColorSpace.MakeSRGB(),
        )
        ctx = getattr(fw, "_context", None)
        surf = skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info) if ctx else None
        if surf is None:
            surf = skia.Surface(w, h)
        self._compose_surface = surf
        return surf

    def _ensure_mid_surface(self, fw, width, height):
        w, h = max(1, int(width)), max(1, int(height))
        surf = self._mid_surface
        if surf is not None and surf.width() == w and surf.height() == h:
            return surf
        info = skia.ImageInfo.Make(
            w, h,
            skia.kRGBA_8888_ColorType,
            skia.kPremul_AlphaType,
            skia.ColorSpace.MakeSRGB(),
        )
        ctx = getattr(fw, "_context", None)
        surf = skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info) if ctx else None
        if surf is None:
            surf = skia.Surface(w, h)
        self._mid_surface = surf
        return surf
