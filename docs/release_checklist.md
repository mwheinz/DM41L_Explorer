# DM41L Explorer — Public Release Checklist

Status as of 2026-08-13: the repo (`github.com/mwheinz/DM41L_Explorer`) is
already **public**, but is missing the documentation, licensing, and CI/CD
that make a public repo usable and trustworthy to a stranger. Nothing here
is urgent/blocking each other — pick items in any order — but README +
LICENSE are the highest-leverage starting point.

## 1. Repo hygiene

- [X] Add `src/dm41-venv/` (or a generic `*venv*/`) to `.gitignore`. It's not
  currently tracked, but it's also not ignored — a future `git add -A` would
  sweep the whole venv into the repo. (Done. dm41-venv already exists at the
  root level and is in .gitignore.
- [X] Split `requirements.txt` into:
  - `requirements.txt` — runtime only: `customtkinter`, `darkdetect`,
    `pyserial`
  - `requirements-dev.txt` — `black`, `pytest`, `pyinstaller`, and black's own
    transitive deps (`click`, `mypy_extensions`, `packaging`, `pathspec`,
    `platformdirs`, `Pygments`, `pytokens`, `iniconfig`, `pluggy`)
    (Done 2026-08-13. `requirements-dev.txt` starts with `-r requirements.txt`
    so a dev install pulls in both.)
- [X] Generate `resources/MyIcon.ico` for Windows and `resources/MyIcon.png`
  for Linux. `src/dm41l.spec`'s `EXE()`/`BUNDLE()` icon now branches on
  `platform.system()` (`.ico` on Windows, `.icns` on macOS, no icon on
  Linux — PyInstaller doesn't support one there; `MyIcon.png` is ready for
  a future `.desktop` file's `Icon=` instead).
  (Done 2026-08-14. `resources/makeicon.sh` rewritten: the macOS `.icns`
  step still uses `sips`/`iconutil` and only runs on macOS; `.ico`/`.png`
  generation now uses Pillow (`requirements-dev.txt`) and runs on any
  platform. `resources/MyIcon.ico`/`resources/MyIcon.png` were generated
  from the real `icon.png` and delivered alongside the script, so nothing
  further to run before the next build/release.)

## 2. Documentation

- [X] `README.md` — what the tool is/does, a screenshot or two, and
      per-OS build/install instructions (the existing `src/build.sh`
      header comment has the bones of this already — pull it up to a
      real README).
      (Done 2026-08-13, including three real screenshots rendered from the
      app itself under Xvfb, in `resources/screenshots/`.)
- [X] Link out to `docs/memory.md`, `docs/flags.md`, `docs/program.md`
      from the README so they're discoverable.
      (Done 2026-08-13, part of the README above.)
- [X] `LICENSE` — **needs your decision.** MIT is the common default for
      a permissive hobby/utility project; something copyleft (GPL/AGPL)
      is the alternative if you want downstream changes to stay open.
      Not decided yet.
      (Decided 2026-08-13: Simplified/2-clause BSD ("NetBSD license").
      LICENSE file added.)
- [X] Optional: `CONTRIBUTING.md` if you want outside PRs, issue
      templates if you want structured bug reports.
      (Done 2026-08-14: `CONTRIBUTING.md` added — dev setup, running
      tests, `black` formatting convention, PR expectations, and bug
      report guidance. Issue templates not done — flagged as a further
      optional step if you want more structure than free-form issues.)

## 3. Code organization

- [X] Split `src/memory.py` (78KB, single file) into a `memory/` package.
      Class boundaries are already clean (confirmed via
      `grep '^class '`), so this should be a mechanical move, not a
      redesign. (Done 2026-08-13, verified against the full test suite
      before and after the split — identical results, 100 passed/4
      skipped.)
  - `memory/registers.py` — `Register`, `AlphaRegister`,
    `DM41LMemoryError`
  - `memory/regions.py` — `MemoryRegion` + `StatusRegisters`,
    `KeyAssignments`, `Alarms`, `ProgramMemory`, `PrimaryData`,
    `UnusedRegion`
  - `memory/xm_file.py` — `XMFile`, `ExtendedMemory`
  - `memory/program_info.py` — `ProgramInfo`
  - `memory/__init__.py` (or `memory/memory.py`) — the `Memory`
    orchestrator class
  - Re-export everything from `memory/__init__.py` so existing imports
    elsewhere (`gui/*`, `engine/*`, `tests/*`) don't need to change.

## 4. CI/CD (`.github/workflows/`)

- [X] **Test workflow** — run on push/PR across
      `ubuntu-latest` / `macos-latest` / `windows-latest`.
      Linux runner needs `sudo apt-get install python3-tk` explicitly
      (not bundled by default — same lesson this project already hit
      when testing under Xvfb).
      (Done 2026-08-13: `.github/workflows/test.yml`. Note: workflow files
      under `.github/` can't be written via the device bridge for security
      reasons — delivered as a download instead; you'll need to drop it
      into place yourself.)
- [X] **Release workflow** — triggered on a version tag, builds on all
      three OSes (reuses `src/build.sh` / `dm41l.spec`), zips each
      platform's output, computes SHA256 checksums, and attaches both to
      a GitHub Release.
      (Done 2026-08-13: `.github/workflows/release.yml`, same manual-drop
      caveat as above.)
- [X] Set up issues and test with the github workflow.
      (Confirmed 2026-08-14 by checking the repo's Actions/Releases pages
      directly: `test.yml` has run repeatedly on recent pushes to `main`
      and every run passed; `release.yml` has now published two full
      (non-draft) GitHub Releases end-to-end — `v2026.08.01` and
      `v2026.08.02`, the latter with 10 build/checksum assets attached.
      Both workflows are working as designed.)

## 5. Cross-platform build/test environment

- [ ] Windows: use GitHub Actions' `windows-latest` runner as the
      primary native x64 build/test machine — no local Windows box
      needed for CI.
- [ ] For manual GUI smoke-testing, a **Windows 11 ARM64 VM in UTM** on
      your Apple Silicon Mac works well (native Apple virtualization, not
      slow QEMU emulation). No official free ARM64 ISO from Microsoft,
      but the Windows Insider Program provides one, or build one via UUP
      dump. Windows 11 ARM includes x64 emulation, so it can run your
      standard x64 PyInstaller build.
- [ ] Linux (Ubuntu via UTM, already set up): keep as-is for manual
      testing; matches the `ubuntu-latest` CI runner reasonably well.

## 6. Distribution trust / code signing (no paid dev accounts)

- [X] **macOS**: add ad-hoc signing to `build.sh` — required on Apple
      Silicon just to run at all, and it's free:
      `codesign --force --deep --sign - "dist/DM41L Explorer.app"`
      (Done 2026-08-13: added to `src/build.sh`, guarded by
      `[ "$(uname)" = "Darwin" ]` so it's a no-op elsewhere.)
- [X] Document the Gatekeeper workaround in the README (right-click the
      app → Open, confirm once) for anyone downloading a release
      binary — ad-hoc signing doesn't satisfy Gatekeeper's quarantine
      check, only full notarization ($99/yr Apple Developer Program)
      would remove the prompt entirely.
      (Already done as part of the README's "Building a standalone
      application" section — noticed and checked off 2026-08-14.)
- [X] **Windows**: document the SmartScreen click-through ("More info" →
      "Run anyway") in the README.
      (Same section as above — already done, checked off 2026-08-14.)
- [X] Linux/Windows onedir builds need their `_internal/` support-files
      folder kept alongside the executable — explain this so a release
      download isn't mistaken for clutter. Considered switching to
      PyInstaller "onefile" mode instead, but decided against it: onefile
      exes have to self-extract to a temp folder on every launch (slower
      startup) and are flagged by Windows Defender/antivirus far more
      often than onedir builds (a classic malware-dropper pattern) —
      not worth the risk on top of the SmartScreen friction already
      documented above.
      (Done 2026-08-14: `resources/dist_readme.txt` added, copied into
      `dist/dm41lexplorer/README.txt` by `build.sh` for Linux/Windows
      builds — ships inside every release zip automatically since
      `release.yml` zips that whole directory. Not needed for macOS;
      the `.app` bundle is already a single self-contained unit. Also
      added: `build.sh` now bundles `resources/MyIcon.png` into the
      Linux build's output folder too — Linux has no equivalent of a
      Windows `.exe`'s baked-in icon, so this ships the icon file
      alongside the binary, ready for a `.desktop` file's `Icon=` entry
      if the user sets one up.)
- [ ] Optional/later if the friction becomes a real problem:
      [SignPath.org](https://signpath.org)'s free code-signing program
      for open-source projects (requires acceptance + CI integration) —
      the only no-cost path to a real Windows signature.
- [ ] Publish SHA256 checksums with every release regardless, so users
      have an integrity check independent of signing.

## 7. Release process

- [X] One-time repo setting: Settings → Actions → General → Workflow
      permissions → "Read and write permissions". Required for
      `release.yml`'s `gh release create` step to be allowed to publish —
      the default is read-only and would make that step fail with a
      permissions error.
      (Confirmed set 2026-08-13; confirmed working in practice 2026-08-14
      — `release.yml` has successfully published to GitHub Releases.)
- [X] Tag a version (e.g. `v0.1.0`), let the release workflow build and
      publish artifacts.
      (Done — `v2026.08.01` and `v2026.08.02` both published as full
      releases with build artifacts and checksums attached, confirmed
      2026-08-14 via the repo's Releases page.)
- [ ] Write release notes summarizing what's in the first public build.
- [ ] Decide whether to keep `dm41l.spec`/`build.sh` as the single
      source of truth for local + CI builds (recommended — CI should
      just invoke `build.sh`, not duplicate its steps in YAML).

## 8. Post release enhancements

- [ ] Improve dark/light modes so that the content inside frames respond to the
  current mode. Right now the use of alternating rows prevents dark/light mode
  changes from working properly.
- [ ] LoadMemoryStringCommand doesn't validate the string before sending it.

---
*Generated 2026-08-13 from a DM41L_Explorer planning session. See project
memory (`public_release_prep.md`) for the full reasoning behind each item.*
