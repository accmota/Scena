"""Audio effects tests. Run: python -m unittest tests.test_audio_effects -v"""
from __future__ import annotations

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.audio_effects import (
    Distortion,
    Echo,
    HighPass,
    LowPass,
    Reverb,
    Wavefold,
    apply_effects,
    max_tail_seconds,
)
from scena.audio_mixer import SAMPLE_RATE, BufferSource, Voice, make_sine, render
from scena.audio import Sound, play_sound, reset_audio
from scena.process import reset_process_scheduler


def _tone(freq, duration=0.2, amp=1.0):
    return make_sine(freq, duration, amp=amp)


class TestAudioEffects(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        reset_audio()

    def tearDown(self):
        reset_process_scheduler()
        reset_audio()

    def test_defaults_match_catalog(self):
        self.assertEqual(LowPass().cutoff, 300.0)
        self.assertEqual(HighPass().cutoff, 2000.0)
        self.assertEqual(Echo().delay, 0.25)
        self.assertEqual(Echo().decay, 0.6)
        self.assertEqual(Reverb().size, 1.0)
        self.assertEqual(Reverb().mix, 0.6)
        self.assertEqual(Distortion().drive, 8.0)
        self.assertEqual(Wavefold().drive, 3.0)

    def test_lowpass_loses_high_frequency_vs_highpass(self):
        tone = _tone(8000, 0.15, amp=0.8)
        lp = LowPass(cutoff=400)
        hp = HighPass(cutoff=400)
        through_lp = apply_effects(tone.copy(), [lp], SAMPLE_RATE)
        through_hp = apply_effects(tone.copy(), [hp], SAMPLE_RATE)
        amp_lp = float(np.sqrt(np.mean(through_lp[2000:] ** 2)))
        amp_hp = float(np.sqrt(np.mean(through_hp[2000:] ** 2)))
        self.assertLess(amp_lp, amp_hp * 0.35)

    def test_echo_delayed_repeat(self):
        n = SAMPLE_RATE  # 1s
        impulse = np.zeros((n, 2), dtype=np.float32)
        impulse[0] = 1.0
        delay = 0.1
        decay = 0.5
        out = apply_effects(impulse, [Echo(delay=delay, decay=decay)], SAMPLE_RATE)
        offset = int(round(delay * SAMPLE_RATE))
        self.assertAlmostEqual(float(out[0, 0]), 1.0, places=5)
        self.assertGreater(float(out[offset, 0]), 0.4)
        self.assertAlmostEqual(float(out[offset, 0]), decay, places=2)

    def test_reverb_extends_decay(self):
        n = SAMPLE_RATE // 2
        burst = np.zeros((n, 2), dtype=np.float32)
        burst[:64] = 1.0
        dry_tail = float(np.sum(burst[2000:] ** 2))
        wet = apply_effects(burst.copy(), [Reverb(size=0.8, mix=0.9)], SAMPLE_RATE)
        wet_tail = float(np.sum(wet[2000:] ** 2))
        self.assertGreater(wet_tail, dry_tail + 1e-4)

    def test_distortion_adds_harmonics_without_huge_gain(self):
        tone = _tone(440, 0.25, amp=0.5)
        dry_rms = float(np.sqrt(np.mean(tone ** 2)))
        dry = np.abs(np.fft.rfft(tone[:, 0] * np.hanning(tone.shape[0])))
        wet = apply_effects(tone.copy(), [Distortion(drive=8.0)], SAMPLE_RATE)
        wet_rms = float(np.sqrt(np.mean(wet ** 2)))
        # Makeup: not ~4× louder like the old tanh(drive*x).
        self.assertLess(wet_rms, dry_rms * 2.5)
        dist = np.abs(np.fft.rfft(wet[:, 0] * np.hanning(wet.shape[0])))
        freqs = np.fft.rfftfreq(tone.shape[0], 1 / SAMPLE_RATE)
        fund = np.argmin(np.abs(freqs - 440))
        third = np.argmin(np.abs(freqs - 1320))
        second = np.argmin(np.abs(freqs - 880))
        dry_ratio = dry[third] / max(dry[fund], 1e-12)
        wet_ratio = dist[third] / max(dist[fund], 1e-12)
        self.assertGreater(wet_ratio, dry_ratio * 2)
        # Asymmetry → some even harmonic energy.
        self.assertGreater(dist[second] / max(dist[fund], 1e-12), dry[second] / max(dry[fund], 1e-12))

    def test_wavefold_adds_high_harmonics(self):
        tone = _tone(220, 0.2, amp=0.6)
        dry = np.abs(np.fft.rfft(tone[:, 0] * np.hanning(tone.shape[0])))
        wet = apply_effects(tone.copy(), [Wavefold(drive=4.0)], SAMPLE_RATE)
        folded = np.abs(np.fft.rfft(wet[:, 0] * np.hanning(wet.shape[0])))
        freqs = np.fft.rfftfreq(tone.shape[0], 1 / SAMPLE_RATE)
        fund = np.argmin(np.abs(freqs - 220))
        hi = np.argmin(np.abs(freqs - 1540))  # 7th-ish
        dry_ratio = dry[hi] / max(dry[fund], 1e-12)
        wet_ratio = folded[hi] / max(folded[fund], 1e-12)
        self.assertGreater(wet_ratio, dry_ratio * 3)

    def test_enabled_false_is_bit_identical(self):
        tone = _tone(1200, 0.05, amp=0.6)
        for fx in (
            LowPass(cutoff=200),
            HighPass(cutoff=200),
            Echo(),
            Reverb(),
            Distortion(),
            Wavefold(),
        ):
            fx.enabled = False
            out = apply_effects(tone.copy(), [fx], SAMPLE_RATE)
            np.testing.assert_array_equal(out, tone)

    def test_remove_idempotent_and_handle_stack(self):
        h = play_sound(Sound._from_pcm(_tone(440, 0.4)))
        lp = h.effects.add(LowPass(cutoff=600))
        self.assertEqual(len(h.effects), 1)
        lp.remove()
        self.assertEqual(len(h.effects), 0)
        lp.remove()
        h.effects.remove(lp)
        h.effects.clear()
        h.cancel()

    def test_render_applies_lowpass(self):
        tone = _tone(8000, 0.05, amp=0.8)
        lp = LowPass(cutoff=300)
        voices = {1: Voice(1, BufferSource(tone), volume=1.0, effects=(lp,))}
        wet = render(voices, tone.shape[0]).block
        dry_amp = float(np.sqrt(np.mean(tone[1000:] ** 2)))
        wet_amp = float(np.sqrt(np.mean(wet[1000:] ** 2)))
        self.assertLess(wet_amp, dry_amp * 0.5)

    def test_echo_tail_drains_after_eof(self):
        n = SAMPLE_RATE // 5  # 0.2 s dry
        impulse = np.zeros((n, 2), dtype=np.float32)
        impulse[0] = 1.0
        echo = Echo(delay=0.1, decay=0.5)
        tail = echo._tail_seconds()
        self.assertGreater(tail, 0.3)
        voices = {1: Voice(1, BufferSource(impulse), volume=1.0, effects=(echo,))}
        # Render dry length — should not finish yet (tail remaining).
        r1 = render(voices, n)
        self.assertEqual(r1.finished_ids, [])
        self.assertIn(1, voices)
        self.assertTrue(voices[1].draining)
        # Energy still present in a post-EOF block.
        r2 = render(voices, SAMPLE_RATE // 10)
        self.assertGreater(float(np.max(np.abs(r2.block))), 0.01)
        # Drain the rest of the estimated tail (+slack).
        left = int(math.ceil((tail + 0.05) * SAMPLE_RATE))
        r3 = render(voices, left)
        self.assertEqual(len(r3.finished_ids), 1)
        self.assertEqual(r3.finished_ids[0][0], 1)

    def test_max_tail_seconds(self):
        self.assertEqual(max_tail_seconds([]), 0.0)
        self.assertEqual(max_tail_seconds([Distortion(), Wavefold()]), 0.0)
        self.assertGreater(max_tail_seconds([Echo()]), 1.0)
        self.assertGreater(max_tail_seconds([Reverb()]), 0.5)
        echo = Echo()
        rev = Reverb()
        self.assertAlmostEqual(
            max_tail_seconds([echo, rev]),
            max(echo._tail_seconds(), rev._tail_seconds()),
            places=5,
        )

    def test_bake_transpose_preserves_duration(self):
        tone = _tone(440, 1.0, amp=0.7)
        src = Sound._from_pcm(tone, path="<bake-tone>")
        baked = src.bake(transpose=12)
        self.assertAlmostEqual(baked.duration, src.duration, places=2)
        # Peak near 880 Hz.
        mono = baked._samples[:, 0]
        win = mono * np.hanning(mono.shape[0])
        mag = np.abs(np.fft.rfft(win))
        freqs = np.fft.rfftfreq(mono.shape[0], 1 / SAMPLE_RATE)
        peak = float(freqs[int(np.argmax(mag[1:]) + 1)])
        self.assertGreater(peak, 700)
        self.assertLess(peak, 1100)
        # Intern: same knobs → same object.
        again = src.bake(transpose=12)
        self.assertIs(again, baked)

    def test_bake_pads_echo_tail(self):
        n = SAMPLE_RATE // 5
        impulse = np.zeros((n, 2), dtype=np.float32)
        impulse[0] = 1.0
        src = Sound._from_pcm(impulse, path="<bake-echo>")
        echo = Echo(delay=0.1, decay=0.5)
        baked = src.bake(echo)
        self.assertGreater(baked.duration, src.duration + 0.2)

    def test_bake_pitch_changes_duration(self):
        tone = _tone(440, 1.0, amp=0.7)
        src = Sound._from_pcm(tone, path="<bake-pitch>")
        baked = src.bake(pitch=2.0)
        self.assertAlmostEqual(baked.duration, src.duration / 2.0, places=2)
        again = src.bake(pitch=2.0)
        self.assertIs(again, baked)
        # Distinct from transpose intern key.
        transposed = src.bake(transpose=12)
        self.assertIsNot(transposed, baked)

    def test_amp_db_range(self):
        from scena.audio import amp_db
        self.assertEqual(amp_db(0.0), 0.0)
        self.assertEqual(amp_db(-0.5), 0.0)
        self.assertAlmostEqual(amp_db(1.0), 1.0, places=5)
        self.assertEqual(amp_db(2.0), 1.0)  # above full-scale → clamp
        self.assertAlmostEqual(amp_db(0.001, floor=-60), 0.0, places=5)  # -60 dB
        mid = amp_db(0.1, floor=-60)  # -20 dB → 40/60
        self.assertAlmostEqual(mid, 40.0 / 60.0, places=4)
        with self.assertRaises(ValueError):
            amp_db(0.5, floor=0)


class TestEffectGuards(unittest.TestCase):
    def test_echo_bad_delay_raises_at_construction(self):
        for delay in (float("nan"), float("inf"), -1.0):
            with self.assertRaises(ValueError):
                Echo(delay=delay, decay=0.5)

    def test_echo_bad_delay_is_dry(self):
        """A bad value mutated in after construction still renders dry."""
        impulse = np.zeros((128, 2), dtype=np.float32)
        impulse[0] = 1.0
        for delay in (float("nan"), float("inf"), -1.0):
            echo = Echo(decay=0.5)
            echo.delay = delay
            self.assertEqual(echo._tail_seconds(), 0.0)
            out = echo._process(impulse.copy(), SAMPLE_RATE)
            np.testing.assert_allclose(out, impulse, atol=1e-6)

    def test_distortion_is_chunk_invariant(self):
        sig = np.concatenate([
            np.zeros((4410, 2), dtype=np.float32),
            make_sine(440, 0.2, amp=0.5),
        ])
        whole = Distortion(drive=8.0)._process(sig.copy(), SAMPLE_RATE)
        part = Distortion(drive=8.0)
        split = np.concatenate([
            part._process(sig[:4410].copy(), SAMPLE_RATE),
            part._process(sig[4410:].copy(), SAMPLE_RATE),
        ])
        self.assertLess(float(np.max(np.abs(whole - split))), 0.05)

    def test_distortion_empty_input(self):
        empty = np.zeros((0, 2), dtype=np.float32)
        out = Distortion()._process(empty, SAMPLE_RATE)
        self.assertEqual(out.shape, (0, 2))

    def test_reverb_wet_is_near_unity(self):
        tone = make_sine(440, 0.5, amp=0.5)
        wet = Reverb(size=1.0, mix=1.0)._process(tone.copy(), SAMPLE_RATE)
        dry_rms = float(np.sqrt(np.mean(tone[-4410:] ** 2)))
        wet_rms = float(np.sqrt(np.mean(wet[-4410:] ** 2)))
        self.assertLess(wet_rms / dry_rms, 1.5)
        self.assertGreater(wet_rms / dry_rms, 0.2)

    def test_short_transpose_still_shifts(self):
        tone = make_sine(440, 0.02, amp=0.7)
        src = Sound._from_pcm(tone, path="<short-transpose>")
        baked = src.bake(transpose=12)
        self.assertAlmostEqual(baked.duration, src.duration, places=2)

        def peak_hz(samples):
            mono = samples[:, 0]
            mag = np.abs(np.fft.rfft(mono * np.hanning(mono.shape[0])))
            freqs = np.fft.rfftfreq(mono.shape[0], 1 / SAMPLE_RATE)
            return float(freqs[int(np.argmax(mag[1:]) + 1)])

        self.assertGreater(peak_hz(baked._samples), peak_hz(tone) + 200)

    def test_bake_cache_includes_pcm_and_volume(self):
        a = Sound._from_pcm(make_sine(440, 0.3), path="<pcm>")
        b = Sound._from_pcm(make_sine(880, 0.3), path="<pcm>")
        self.assertIsNot(a.bake(), b.bake())
        tone = make_sine(440, 0.3)
        quiet = Sound._from_pcm(tone.copy(), volume=0.3, path="<v>").bake()
        loud = Sound._from_pcm(tone.copy(), volume=0.9, path="<v>").bake()
        self.assertIsNot(quiet, loud)
        self.assertAlmostEqual(quiet.volume, 0.3)
        self.assertAlmostEqual(loud.volume, 0.9)

    def test_bake_rejects_bad_pitch_and_transpose(self):
        src = Sound._from_pcm(make_sine(440, 0.1), path="<bad-bake>")
        for pitch in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                src.bake(pitch=pitch)
        for semitones in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                src.bake(transpose=semitones)

    def test_bake_empty_distortion(self):
        empty = Sound._from_pcm(np.zeros((0, 2), dtype=np.float32), path="<empty>")
        baked = empty.bake(Distortion())
        self.assertEqual(baked.duration, 0.0)


# The 0.9.0 effects, one sample at a time: the sound authors have heard. The
# effects now run a block (or a channel of Python floats) per step (WP32); they
# must give these bytes, block after block, whatever the block sizes.

def _ref_delay(buf, idx, x, step):
    out = np.empty_like(x)
    for i in range(x.shape[0]):
        out[i], buf[idx] = step(buf[idx], x[i])
        idx = (idx + 1) % buf.shape[0]
    return out, idx


class _Ref:
    def __init__(self, kind, **kw):
        self.kind, self.kw, self.st = kind, kw, None

    def _process(self, x, sr):
        return getattr(self, "_" + self.kind)(x, sr, **self.kw)

    def _onepole(self, x, sr, cutoff, high):
        a = float(1.0 - np.exp(-2.0 * np.pi * cutoff / sr))
        lp = np.zeros(x.shape[1]) if self.st is None else self.st.astype(np.float64)
        y = np.empty_like(x)
        for i in range(x.shape[0]):
            lp += a * (x[i].astype(np.float64) - lp)
            y[i] = x[i] - lp if high else lp
        self.st = lp.astype(np.float32)
        return y.astype(np.float32)

    def _LowPass(self, x, sr, cutoff):
        return self._onepole(x, sr, cutoff, False)

    def _HighPass(self, x, sr, cutoff):
        return self._onepole(x, sr, cutoff, True)

    def _Echo(self, x, sr, delay, decay):
        if self.st is None:
            self.st = [np.zeros((max(1, int(round(delay * sr))), x.shape[1]), np.float32), 0]
        buf, idx = self.st

        def step(read, s):
            mixed = s + read * decay
            return mixed, mixed
        out, self.st[1] = _ref_delay(buf, idx, x, step)
        return out

    def _Reverb(self, x, sr, size, mix):
        if self.st is None:
            ms = [29.7, 37.1, 41.1, 43.7, 5.0, 1.7]
            self.st = [[np.zeros((max(1, int(round(m * size * 0.001 * sr))), x.shape[1]),
                                 np.float32), 0] for m in ms]
        src = x.astype(np.float32)
        wet = np.zeros_like(src)
        for line in self.st[:4]:   # combs: the output is the value written
            acc, line[1] = _ref_delay(line[0], line[1], src,
                                      lambda read, s: (s + read * 0.84,) * 2)
            wet += acc
        wet *= (1.0 - 0.84) / 4.0

        def allpass(read, s):
            y = read - 0.7 * s
            return y, s + 0.7 * y
        for line in self.st[4:]:
            wet, line[1] = _ref_delay(line[0], line[1], wet, allpass)
        return (src * (1.0 - mix) + wet * mix).astype(np.float32)

    def _Distortion(self, x, sr, drive):
        src = x.astype(np.float64)
        a = 1.0 - np.exp(-2.0 * np.pi * 3000.0 / sr)
        nch = src.shape[1]
        lp_pre, lp_de, e_in, e_out = self.st or (np.zeros(nch), np.zeros(nch), 0.0, 0.0)
        lp_pre, lp_de = lp_pre.astype(np.float64), lp_de.astype(np.float64)
        pre = np.empty_like(src)
        for i in range(src.shape[0]):
            lp_pre += a * (src[i] - lp_pre)
            pre[i] = src[i] + 0.55 * (src[i] - lp_pre)
        shaped = np.tanh((pre + 0.08) * drive) / max(math.tanh(drive), 1e-12)
        out = np.empty_like(shaped)
        for i in range(shaped.shape[0]):
            lp_de += a * (shaped[i] - lp_de)
            out[i] = shaped[i] - 0.35 * (shaped[i] - lp_de)
        rel = math.exp(-1.0 / (sr * 0.03))
        for i in range(out.shape[0]):
            e_in = max(float(np.max(np.abs(src[i]))), e_in * rel)
            e_out = max(float(np.max(np.abs(out[i]))), e_out * rel)
            out[i] *= (e_in * 1.1) / max(e_out, 1e-12)
        self.st = (lp_pre.astype(np.float32), lp_de.astype(np.float32), e_in, e_out)
        return out.astype(np.float32)


class TestEffectsMatchTheSampleLoop(unittest.TestCase):
    """WP32: each effect gives the 0.9.0 per-sample bytes, mono and stereo,
    in one block, in mixer-size blocks and in ragged ones (a block shorter
    than a delay line, one longer)."""

    CASES = (
        [("Reverb", dict(size=s, mix=m)) for s in (0.05, 1.0, 1.5) for m in (0.6, 1.0)]
        + [("Echo", dict(delay=d, decay=0.6)) for d in (1 / SAMPLE_RATE, 3 / SAMPLE_RATE, 0.01)]
        + [("LowPass", dict(cutoff=300.0)), ("HighPass", dict(cutoff=2000.0))]
        + [("Distortion", dict(drive=d)) for d in (0.1, 8.0)]
    )

    def test_same_bytes_in_any_blocks(self):
        rng = np.random.default_rng(7)
        new = {"Reverb": Reverb, "Echo": Echo, "LowPass": LowPass,
               "HighPass": HighPass, "Distortion": Distortion}
        for nch in (1, 2):
            x = (rng.standard_normal((6000, nch)) * 0.4).astype(np.float32)
            x[1000:2500] = 0.0
            for blocks in ([6000], [512] * 11 + [368], [7, 3000, 1, 1300, 1692]):
                for kind, kw in self.CASES:
                    with self.subTest(kind=kind, kw=kw, nch=nch, blocks=len(blocks)):
                        ref, fx = _Ref(kind, **kw), new[kind](**kw)
                        got, want, pos = [], [], 0
                        for n in blocks:
                            seg = x[pos:pos + n]
                            pos += n
                            want.append(ref._process(seg.copy(), SAMPLE_RATE))
                            got.append(fx._process(seg.copy(), SAMPLE_RATE))
                        self.assertEqual(np.concatenate(got).tobytes(),
                                         np.concatenate(want).tobytes())


class TestNoSampleLoopOverRows(unittest.TestCase):
    """The class of WP32: an effect that steps through a numpy array a row at a
    time (``for i in range(x.shape[0])``) pays numpy's call cost per sample, on
    the mixer's thread for a live voice. Delay lines take a run per step
    (``_delay_line``); one-pole filters loop over Python floats."""

    def test_no_range_over_rows_in_the_effects(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "scena", "audio_effects.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Call) \
                    and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range":
                for arg in node.iter.args:
                    if any(isinstance(n, ast.Attribute) and n.attr in ("shape", "size")
                           or isinstance(n, ast.Call) and getattr(n.func, "id", "") == "len"
                           for n in ast.walk(arg)):
                        found.append(node.lineno)
        self.assertEqual(found, [], "a per-sample loop over array rows")


if __name__ == "__main__":
    unittest.main()
