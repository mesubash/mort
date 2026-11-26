# Releasing mort

Steps for a release. Each one that publishes something is done by the maintainer.

## Before a release

1. `python3 -m unittest` passes.
2. Version is set in `mort/__init__.py`, in `packaging/mort.rb` (url and test), and in the README badge.
3. On a Linux machine: `mort daemon install`, `mort run -- sh -c 'sleep 5; exit 1'`, and a "died" notice within a minute.
4. `python3 -m build` makes `dist/mort_watcher-<version>.tar.gz` and a wheel; `pipx install dist/*.whl` gives a working `mort --version`.

## Publish

1. Make the repository public (GitHub settings).
2. Tag and push: `git tag v<version> && git push origin v<version>`, then make a GitHub release from the tag.
3. PyPI, name `mort-watcher` (the name `mort` is taken): `python3 -m twine upload dist/*`, with your own PyPI token.
4. Homebrew: create the repository `homebrew-tap` under your account, copy `packaging/mort.rb` to `Formula/mort.rb` (it needs Homebrew's `python@3.14`), set `sha256` to the output of `curl -sL <url> | shasum -a 256`, then check with `brew install --build-from-source <user>/tap/mort` and `brew test mort`.
5. Update the install section of the README to `pipx install mort-watcher` and `brew install <user>/tap/mort`.

## After publishing

The launch test from `docs/PLAN.md` phase 4: within 30 days of posting, at least 100 GitHub stars or 25 people who say they run it. Below that, mort stays a personal tool.
