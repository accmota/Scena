# Contributing to Scena

Contributions are welcome: bug reports, fixes, features, docs and examples.

## License of contributions

Scena is under the MIT license (see [LICENSE](LICENSE)). By submitting a
contribution you agree that it is licensed under the same MIT license. You
keep the copyright on your own work.

## Sign off your commits

Every commit must carry a `Signed-off-by` line. It certifies the
[Developer Certificate of Origin](https://developercertificate.org): that you
wrote the change, or otherwise have the right to submit it under the
project's license. Git adds the line for you:

```
git commit -s
```

## Third-party material

- Code copied or adapted from elsewhere must be under a license compatible
  with MIT. Say where it came from, in the pull request and in a comment
  next to the code.
- Images, sounds and fonts go in `examples/media/`, each folder with its
  license file, and are listed in `examples/media/CREDITS.md`. Only CC0,
  CC-BY or similarly free licenses: no "free for personal use" assets.

## Before you open a pull request

- Read `design/Scena Design.md` for how the framework fits together.
- New features come with unit tests; bug fixes come with a test that catches
  the bug.
- Run the quick test tier: `python tests/run_tiers.py quick`
  (see `tests/README.txt`).
- Update the design documents in `design/` when the change affects them.
- A change authors will notice gets a line under **Unreleased** in
  `CHANGELOG.md`. The API is published: a change that breaks author code
  needs a good reason and follows "Compatibility and versions" in
  `design/Scena Design.md` (the old spelling raises with the new one).
