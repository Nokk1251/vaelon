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
`.github/workflows/ci.yml` runs the core test files on Windows, Linux and macOS (pull requests: macOS with Python 3.13
only; a push to main and a weekly run: Python 3.10 and 3.13 everywhere), type-checks the UI and scans for secrets.
`release.yml` runs all test files before it builds the installers.

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

## 7b. Release signatures (minisign, key offline)
Every release file can carry a signature (`FILE.minisig`, minisign format) made with Vaelon's release key. The key
stays OFFLINE on the owner's computer, encrypted with a password - it never goes to GitHub. People who use Vaelon do
nothing different; anyone who wants can check a download.

What it proves: the file is exactly the one the owner signed for that version, under that name. It protects against
a file replaced later (on GitHub, a mirror, a download site, a cache) and against an old version renamed as a new one.
Because the key is not on GitHub, a taken-over GitHub account cannot make new valid signatures - but that protects only
people who already have the real public key (an earlier copy, or one from another place). Someone who took over the
account could also replace `release-key.pub` on GitHub and the website, so a key change without a signature from the
old key is a warning sign. What it does not prove: that the code or the build was clean - the owner signs the files
that are in the draft at that moment (`sign-draft` prints the draft's `SHA256SUMS.txt`: compare it with the "Checksums"
step in the log of the release run). It cannot help if the owner's own computer or the key's password is compromised.

**Making the key (once, by the owner):**
1. Outside the project folder (the script refuses a path inside it) and outside folders that sync to a cloud (OneDrive,
   Dropbox), with a long password - a passphrase of a few words, at least 12 characters:
   ```powershell
   python scripts/release_sign.py keygen "$env:USERPROFILE\vaelon-keys\vaelon-release.key"
   ```
   It writes the public key to `release-key.pub` (commit it in a pull request) and the SECRET key - encrypted with the
   password - to the file you named. Nothing secret is printed.
2. Keep ONE backup of that encrypted file (e.g. in a password manager, or on a USB stick) and keep the password in the
   password manager. Without both, a lost key can only be replaced by a new one.

**Each release:** the tag builds the draft as before. Then, before pressing Publish:
```powershell
python scripts/release_sign.py sign-draft 0.20.0 --key "$env:USERPROFILE\vaelon-keys\vaelon-release.key"
```
It refuses if there is more than one draft for that version, asks for the password, downloads the draft's files with
your GitHub CLI login, checks every file against `SHA256SUMS.txt` (and prints it - compare it with the run's log), signs
them all, uploads the `.minisig` files and checks that every file of the draft now has exactly one signature. Then
press Publish. If anything fails nothing is published: fix it and run the command again. Turn on "immutable releases"
(repository Settings) so a published release can no longer be changed.

**A new key (rotation):**
1. `python scripts/release_sign.py keygen <new key file> --pub-dir new-key` (writes `new-key\release-key.pub`).
2. `python scripts/release_sign.py sign new-key\release-key.pub --key <OLD key file>` (the old key still matches the
   published `release-key.pub`).
3. A pull request that replaces `release-key.pub` with the new one and adds `release-key.pub.minisig`; say it in the
   release notes. A key change without that signature is a warning sign.

**Checking a download (anyone):** `minisign -H -Vm Vaelon-Setup-X.Y.Z.exe -P <public key line from release-key.pub>`,
and check that the "file:" shown is the name you expect - or, from a source checkout,
`python scripts/release_sign.py verify Vaelon-Setup-X.Y.Z.exe` (the `.minisig` file next to it).

## 8. winget
Vaelon was submitted to the Windows Package Manager as `Nokk_7.Vaelon` (microsoft/winget-pkgs#489220, passed Microsoft's
checks, waiting for a volunteer moderator). Once it is merged: `winget install Vaelon`. Every later version needs its
own update pull request there, or `winget upgrade` keeps offering the old one. Keep the fork `Nokk1251/winget-pkgs`:
the updates are opened from it.

`scripts/winget_update.py` prepares the update from `installer/winget/*.yaml`: it reads the installer's SHA-256 from the
published release (GitHub's digest of the asset and `SHA256SUMS.txt` must both exist and agree), fills the three
manifests and opens "Update: Nokk_7.Vaelon to X.Y.Z". It refuses drafts and pre-releases, an odd version, a version
already in winget or already proposed by someone else, and - while the first submission still waits - a second "New
package". It uses only Python's standard library.

Look first, nothing sent:
```powershell
python scripts/winget_update.py 0.20.0 --dry-run
winget validate --manifest installer/winget/out/0.20.0
```

**Way A - from this computer (recommended: no token stored anywhere):** after publishing a release,
```powershell
$env:WINGET_TOKEN = (gh auth token); python scripts/winget_update.py 0.20.0; Remove-Item Env:WINGET_TOKEN
```
(`gh auth token` is your normal GitHub CLI login; it is used for this one run and sent only to api.github.com.)

**Way B - automatic:** `.github/workflows/winget.yml` runs when a release is released (not for drafts or
pre-releases). It needs a *classic* personal access token with only the `public_repo` scope (fine-grained tokens cannot
open pull requests in another owner's repository). Be clear about the risk: `public_repo` can write to ALL your public
repositories - including `Nokk1251/vaelon` itself (push code, create tags and releases, replace release files). It
cannot change workflow files. So, if you choose Way B:
1. Give the token a short expiry (30-90 days) and renew it.
2. Keep it only in the protected environment `winget` (Settings > Environments > winget): deployment rule "selected
   tags" `v*`, required reviewer = you. Then the token is released only for a version tag, after your click.
   ```powershell
   gh secret set WINGET_TOKEN --repo Nokk1251/vaelon --env winget
   ```
3. Settings > Branches > main: turn on "Do not allow bypassing the above settings", so even an admin token cannot push
   to `main` directly.

Without the secret the workflow shows a warning and sends nothing. The Microsoft CLA was signed once (2026-11-25) and
covers later pull requests; Microsoft's checks and a volunteer moderator review each one.

## 9. Updates (ready)
`vaelon update` asks the public release page whether a newer version exists and prints the link. Nothing is
downloaded automatically; users compare the SHA-256 themselves.

## 10. Legal pages (ready)
`LICENSE` (GPL-3.0), `NOTICE` (author credit that must stay), `THIRD_PARTY.md`, `PRIVACY.md`, `SECURITY.md`,
`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.

To protect the *name and logo* (a license does not), register a trademark - in the EU at euipo.europa.eu.
This file is practical guidance, not legal advice.
