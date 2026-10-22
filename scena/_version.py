# The one place the release number lives. pyproject.toml reads it
# (``[tool.setuptools.dynamic]``), so ``scena.__version__`` stays right in a
# source checkout and in an editable install whose metadata is stale.
# Bumping it: design/Scena Design.md, "Compatibility and versions".
__version__ = "0.9.0"
