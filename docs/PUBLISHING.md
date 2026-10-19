# Publishing FreeDM to GitHub

FreeDM is published as a **public** repository under the **PolyForm
Noncommercial 1.0.0** license (source-available, not open source):

- Repository: <https://github.com/EddyGameDev/FreeDM>
- Release: <https://github.com/EddyGameDev/FreeDM/releases/tag/v1.1.0>
- License: `LICENSE` (complete, unmodified PolyForm Noncommercial 1.0.0 text)
- Copyright notice: `NOTICE`
- Releases: the Windows build (`FreeDM-1.1.0.exe`) is attached to the release
- Patch notes: `CHANGELOG.md` — the single source of truth; each release's
  notes are extracted with `scripts/release_notes.py`

The repository is a normal git repository: `Plan\FreeDM\.git` holds the full
history, and the working copy at `F:\OMNI Config\FreeDM` is a plain file copy.

> **What happened on 2026-10-19.** The project was first published under the
> account `outlawproductionstwo-hash`. That account was then **suspended by
> GitHub** within minutes - the API returned *"Sorry. Your account was
> suspended"* and the account now 404s. No reason is given by the API; the
> likely cause is an automated trigger (see §5). The repository was re-created
> under the account `EddyGameDev` and the full local history was pushed to it
> unchanged, together with a verified `v1.0.0` release.
>
> If this ever happens again: **do not re-upload from a fresh account to work
> around a content-related suspension** - that is circumventing the
> enforcement. Appeal instead, or publish from an established account once the
> reason is known.

---

## 1. Before the first push

| Check | Why |
|---|---|
| `LICENSE` matches the official text | The PolyForm text must be **complete and unmodified**. Verify: `https://raw.githubusercontent.com/polyformproject/polyform-licenses/1.0.0/PolyForm-Noncommercial-1.0.0.md` |
| `NOTICE` names the real copyright holder | Do **not** invent a holder — replace `outlawproductionstwo-hash` if the legal owner is a different person or company. |
| `Required Notice:` line in every source file | The license requires anyone who receives *any part* of the software to receive this line. It is the first comment of every `.py`, `.js` and `.html` file. |
| Third-party licences | The shipped exe bundles `requests` (Apache-2.0), `urllib3` (MIT), `certifi` (MPL-2.0), `idna` (BSD-3), `charset-normalizer` (MIT). PyInstaller is a **build tool only**. The table lives in `README.md`. |
| `git status` is clean | `build/`, `dist/` and `__pycache__/` are excluded by `.gitignore`; the exe is distributed as a release asset, not in git. |

## 2. Create the repository and push

With the GitHub CLI (the easiest route):

```
gh auth login
gh repo create FreeDM --public --description "A free, source-available Internet Download Manager (IDM) alternative for Windows"
git remote add origin https://github.com/<user>/FreeDM.git
git push -u origin main
```

Without the CLI, use the API with a token that has the `repo` scope:

```
POST https://api.github.com/user/repos
{"name": "FreeDM", "private": false, "auto_init": false}
```

then push over HTTPS. On Windows the token usually lives in the Windows
Credential Manager, so `git push` works without any token in the remote URL.

## 3. Publish a release with the Windows build

> **The patch notes come from `CHANGELOG.md`.** It is the single source of
> truth for every build, so the release page can never drift from the code.
> Write the section first, then generate the notes from it.

```
# 1. write the notes for the new version in CHANGELOG.md
#    (### Build with the file name, size and SHA-256, then Added/Changed/Fixed)

# 2. build it
powershell -ExecutionPolicy Bypass -File build.ps1   # entry point: freedm\main.py

# 3. record the real hash in CHANGELOG.md
certutil -hashfile dist\FreeDM.exe SHA256

# 4. commit, tag and push
git add -A
git commit -m "v1.1.0: ..."
git tag -a v1.1.0 -m "FreeDM v1.1.0"
git push origin main
git push origin v1.1.0

# 5. generate the release notes from the changelog
python scripts\release_notes.py v1.1.0 --file notes.md

# 6. create the release and attach the exe
gh release create v1.1.0 dist\FreeDM.exe --title "FreeDM v1.1.0" --notes-file notes.md
```

The notes file from step 5 is what goes on the release page. Always put the
**SHA-256** of the exe in it so users can verify the download:

```
certutil -hashfile dist\FreeDM.exe SHA256
```

After uploading, compare the asset digest reported by the API with the local
file — they must be identical:

```
GET https://api.github.com/repos/<user>/FreeDM/releases
-> assets[].digest   e.g. "sha256:..."
```

> If the digest differs, the upload was malformed (a `multipart/form-data`
> body makes GitHub keep the part headers, which corrupts the file). Upload the
> raw bytes with `Content-Type: application/octet-stream` and the
> `?name=<file name>` query parameter instead.
>
> If a deleted asset still downloads with the old bytes, the CDN cached that
> URL: publish the build under a **versioned file name**
> (`FreeDM-1.1.0.exe`) so the URL changes.

## 4. After publishing

- The licence shows as **"Other"** in GitHub's sidebar. That is expected:
  GitHub's licence picker has no PolyForm entry, so the `LICENSE` file is
  the authoritative text. This is not a problem.
- Update `docs/MILESTONE_2.md` (progress log) and the "Download / Run"
  section of `README.md` with the release link.
- Re-sync the working copy and verify the hashes, as with any other change.

## 5. If the account gets suspended

GitHub's API gives no reason - it only says *"Sorry. Your account was
suspended"* (HTTP 403) and the profile returns 404. Check, in this order:

1. **The account's email inbox** (including spam). GitHub sends a notice that
   names the reason category and links the appeal form. This is the only
   authoritative source.
2. **The release asset scan.** GitHub scans uploaded binaries with
   VirusTotal, and a PyInstaller `--onefile` exe is a classic false positive
   (it bundles a Python runtime and unpacks itself at run time). The upload
   succeeds and the account is suspended *minutes later*, when the scan
   finishes. A brand-new account makes this much more likely.
3. **New-account and spam heuristics.** Creating a repository, pushing a lot
   of files and uploading a large binary within minutes is a classic spam
   pattern.
4. **Trademark or abuse reports.** The project deliberately avoids calling
   itself an "IDM alternative" in the *repository description* (the first
   line moderators and bots read); the README explains the comparison in
   words instead.

**What to do:** appeal at <https://support.github.com/contact> ("Account
suspended") and state that the project is original work, source-available
under PolyForm Noncommercial, with no paid or copyrighted content - and offer
to publish source-only if a binary was the trigger. If the account cannot be
recovered, publish from another established account: the local history is
complete, so it is one `git push`.

**Reduce the risk next time:** publish the source first and let the repository
exist for a while before attaching an unsigned binary; or publish source only
and let users build it (`build.ps1`).
