# Examples

Beginner-style Scena games. Prefer these over smoke/bench when learning the API.
They read like a beginner's code: flat classes, Portuguese names, game data in
`st`, no advanced Python.

## Tutorial endpoints

Each tutorial in [`docs/pt/tutorial/`](../docs/pt/tutorial/index.html) ends in one of these
files: the file is the last step's code plus a docstring, nothing else
(`tests/test_tutorials.py` compares them). Change the tutorial first; then copy
its last step here.

| Tutorial | File |
| --- | --- |
| 01 Primeiro script | `primeiro_script.py` |
| 02 Pegar estrelas | `pegar_estrelas.py` |
| 03 Geometria | `ponto_medio.py` |
| 04 UI Widgets | `cadeia_de_bolas.py`, `barras_girando.py`, `osciloscopio.py` |
| 05 Naves | `naves.py` |

```bash
python examples/naves.py
```

More games join this folder when they are ready (each one runs headless in
`tests/test_scripts_run.py`, like these).

## Media and licenses

The images and sounds in `media/` are not under Scena's MIT license. Each
folder has its own `license.txt`, and [`media/CREDITS.md`](media/CREDITS.md)
lists every file's author and license. Most of it is CC0 (no conditions). A few
sounds are CC-BY / CC-BY-SA: a game that ships them must credit their authors
(credits screen or README). The credit lines, ready to copy, are in
[`media/CREDITS.md`](media/CREDITS.md#attribution-required).
