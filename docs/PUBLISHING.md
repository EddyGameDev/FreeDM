# Publishing FreeDM to GitHub

FreeDM is published as a **public** repository under the **PolyForm
Noncommercial 1.0.0** license (source-available, not open source):

- Repository: <https://github.com/outlawproductionstwo-hash/FreeDM>
- License: `LICENSE` (complete, unmodified PolyForm Noncommercial 1.0.0 text)
- Copyright notice: `NOTICE`
- Releases: the Windows build is attached to the release page

The repository is a normal git repository: `Plan\FreeDM\.git` holds the full
history, and the working copy at `F:\OMNI Config\FreeDM` is a plain file copy.

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

```
# 1. build it
powershell -ExecutionPolicy Bypass -File build.ps1

# 2. tag the release
git tag -a v1.0.0 -m "FreeDM v1.0.0"
git push origin v1.0.0

# 3. create the release and attach the exe
gh release create v1.0.0 dist\FreeDM.exe --title "FreeDM v1.0.0" --notes "..."
```

Always put the **SHA-256** of the exe in the release notes so users can
verify the download:

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
> (`FreeDM-1.0.0.exe`) so the URL changes.

## 4. After publishing

- The licence shows as **"Other"** in GitHub's sidebar. That is expected:
  GitHub's licence picker has no PolyForm entry, so the `LICENSE` file is
  the authoritative text. This is not a problem.
- Update `docs/MILESTONE_2.md` (progress log) and the "Download / Run"
  section of `README.md` with the release link.
- Re-sync the working copy and verify the hashes, as with any other change.
