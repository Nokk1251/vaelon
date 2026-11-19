# Contributing to Vaelon

Thank you for helping. Vaelon is free software (GPL-3.0-or-later, see `LICENSE` and `NOTICE`). By sending a change you
agree that it is published under the same license, and that the original author credit in `NOTICE` stays in place.

## Ground rules
1. **Privacy first.** Nothing may leave the user's computer unless the user chose a cloud model or a cloud voice.
   No telemetry, no analytics, no accounts, no "phone home".
2. **Safety is not optional.** Every new tool declares its risk (`SAFE`, `REVERSIBLE`, `DANGEROUS`). Anything that
   reads the outside world is `untrusted=True` and goes through `web._guard`. Never weaken approval, taint, the vault
   or the DLP checks.
3. **Only your own code.** Do not paste code from other projects unless its license is compatible with GPL-3.0 and
   you list it in `THIRD_PARTY.md`.
4. **No secrets.** Keys never go into code, tests, issues or logs. Run `python scripts/check_secrets.py` before a commit.
5. **No voices of real people.** Presets, the designer, or the user's own voice only.
6. English for code, comments, UI text and documentation.

## Set up
```bash
pip install -e ".[all]"                 # Python 3.10+
cd ui/web && npm install                # Node 22+
```

## Before you open a pull request
```bash
for f in tests/test_*.py; do PYTHONPATH=src python -I "$f"; done   # every file must end with OK
cd ui/web && npx tsc --noEmit                                       # the UI must type-check
python scripts/check_secrets.py                                     # no keys in the tree
```
- Add a test for every behaviour you add or fix. Tests are offline: fake the network.
- Keep the static system prompt stable (it is cached); per-request data goes into the user message.
- New network tool: add it to a router group, to `README.md`, and give it a test.
- Describe in the pull request what you ran and what you could not test (for example real phone calls).

## Reporting bugs and ideas
Use the issue templates. For security problems do **not** open a public issue: see `SECURITY.md`.

## Conduct
Be kind and concrete. See `CODE_OF_CONDUCT.md`.
