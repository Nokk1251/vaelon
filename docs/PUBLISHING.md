# Publishing checklist

Everything the project needs before strangers download it. Steps marked **you** need your own account, a payment or
a legal decision; the rest is already prepared in the repository.

## 1. The name (done)
The project is called **Vaelon**. When this was written the name was free on PyPI and npm and the `.com` and `.ai`
domains were unregistered. Still to do by **you** before a release: search the EUIPO and USPTO trademark databases
for "Vaelon" in classes 9 and 42, and register the domain you want.

## 2. Clean the tree
```bash
python scripts/check_secrets.py        # must print "No secrets found."
```
`.gitignore` already excludes build output and `CLAUDE.md` (private working notes). Never add `~/.vaelon`.

## 3. GitHub repository - **you**
```bash
git init -b main
git add .
git commit -m "Vaelon 0.5.0"
gh repo create vaelon --public --source . --push
```
Then in the repository settings: turn on *Private vulnerability reporting*, *Dependabot alerts*, and protect `main`
(pull request + passing checks). Put the repository address into `__source__` in `src/vaelon/__init__.py`: the About
screen shows it and `vaelon update` starts working.

## 4. Automatic checks (ready)
`.github/workflows/ci.yml` runs every test file on Windows, Linux and macOS, type-checks the UI and scans for secrets
on each push and pull request.

## 5. Releases (ready)
```bash
git tag v0.5.0 && git push origin v0.5.0
```
`.github/workflows/release.yml` builds the app on a clean Windows machine, makes the installer and a portable zip,
writes `SHA256SUMS.txt` and an SBOM, and attaches all of it to a **draft** release. Read the draft, then press Publish.

## 6. Installer (ready)
`installer/vaelon.iss` (Inno Setup, free): Program Files install, Start-menu entry, uninstaller, shows the license.
Local build: install Inno Setup 7, run `python scripts/build_app.py`, then
`ISCC.exe installer\vaelon.iss` (Inno Setup 7). Mac: on a Mac run `python3 scripts/build_mac.py` -> `dist/Vaelon-<version>.dmg`.

## 7. Code signing - not used
Releases are not code-signed (the owner's decision, 2026-11-18: no paid certificate). Windows SmartScreen shows
"Unknown publisher" on first launch ("More info" > "Run anyway"); macOS asks once (System Settings > Privacy & Security
> "Open Anyway"). Users can check a download against `SHA256SUMS.txt` on the release page. If this changes later,
SignPath Foundation signs open-source projects free of charge once the repository builds in GitHub Actions.

## 8. winget
```powershell
winget install wingetcreate
wingetcreate new https://github.com/Nokk1251/vaelon/releases/download/v0.5.0/Vaelon-Setup-0.5.0.exe
```
It writes the manifest and opens the pull request to `microsoft/winget-pkgs`. After it is merged:
`winget install Nokk1251.Vaelon`.

## 9. Updates (ready)
`vaelon update` asks the public release page whether a newer version exists and prints the link. Nothing is
downloaded automatically; users compare the SHA-256 themselves.

## 10. Legal pages (ready)
`LICENSE` (GPL-3.0), `NOTICE` (author credit that must stay), `THIRD_PARTY.md`, `PRIVACY.md`, `SECURITY.md`,
`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.

To protect the *name and logo* (a license does not), register a trademark - in the EU at euipo.europa.eu.
This file is practical guidance, not legal advice.
