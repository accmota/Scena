# Scena scripts

Run from the **repo root**.

| Folder | Audience | Role |
|--------|----------|------|
| [`smoke/`](smoke/) | Developers | Visual / behavioural proof (eyeball) |
| [`bench/`](bench/) | Developers | Parametrized performance + soak |
| [`tools/`](tools/) | Developers | Eval helpers, bench wrap |

Assets live in [`examples/media/`](../examples/media/) (tracked, one license per pack: [`CREDITS.md`](../examples/media/CREDITS.md)). Smoke scripts reach them script-relative (`../../examples/media/…` or `scripts/smoke/_media.py`); benches run from the repo root with cwd-relative `examples/media/…` paths.

```bash
python scripts/smoke/shape_fx.py
python scripts/bench/live_mix.py --bench --duration 3
python scripts/bench/soak_leak.py --cycles 20 --json
python scripts/bench/fx_churn.py --quick
python examples/naves.py
```

Author-facing games live in [`examples/`](../examples/) at the repo root.
