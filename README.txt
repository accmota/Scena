Scena is a framework for creative graphics programming. It is written in Python and runs on GLFW and Skia.

By: André Mota.
For: my sons, with much love.

--

It is a framework for beginners, so an API with little or no boilerplate is essential.

Scena's philosophy rests on gradual parameters and on (almost) no boilerplate. If an author asks for a Circle, the framework gives a default circle, a basic element: it only fills in the styles that were not specified. The high-level control (@collide, @when, formulas, etc.) works as a kind of DSL (Domain-Specific Language). The language Scena offers should be very expressive, but without "magic": no hidden clever tricks, no behavior the author did not ask for. The framework must not create in the author's place.

This is a framework for beginner authors. Its goal is learning (teaching programming), not professional practice focused on optimization or centered on the machine. Writing high-performance code should not be a priority for the author, who already has many concepts to learn and master.

--

Version

The current release is in scena/_version.py (scena.__version__). What changed between releases, and how to update code written for an older one, is in CHANGELOG.md.

--

Install

pip install scena (from a copy of this repository: pip install -e .). Then, in a script: from scena import *

Documentation (API guide and tutorials; Portuguese now, English coming): https://accmota.github.io/Scena/ — the same pages are in docs/.

Before 0.6.0 the package was called stage. An install from then is replaced with: pip uninstall stage, then pip install -e .

--

License

Scena's source code and documentation are under the MIT license: see LICENSE. Third-party images and sounds are not.

Each folder in examples/media/ has its own license file (CC0, CC-BY 3.0 or CC-BY-SA 3.0), and examples/media/CREDITS.md lists them all. Most of it is CC0 and can be used with no conditions. A few sounds need attribution: a game that ships them must credit their authors in the game itself (credits screen or README). The credit lines, ready to copy, are in examples/media/CREDITS.md.

Contributions are welcome under the same MIT license: see CONTRIBUTING.md.
