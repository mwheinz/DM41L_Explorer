# DM41L Explorer — Public Release Checklist

Status as of 2026-08-13: the repo (`github.com/mwheinz/DM41L_Explorer`) is
already **public**, but is missing the documentation, licensing, and CI/CD
that make a public repo usable and trustworthy to a stranger. Nothing here
is urgent/blocking each other — pick items in any order — but README +
LICENSE are the highest-leverage starting point.

## 1. Repo hygiene

- [ ] Add `src/dm41-venv/` (or a generic `*venv*/`) to `.gitignore`. It's
      not currently tracked, but it's also not ignored — a future
      `git add -A` would sweep the whole venv into the repo.
- [ ] Split `requirements.txt` into:
  - `requirements.txt` — runtime only: `customtkinter`, `darkdetect`,
    `pyserial`
  - `requirements-dev.txt` — `black`, `pytest`, `pyinstaller`, and
    black's own transitive deps (`click`, `mypy_extensions`, `packaging`,
    `pathspec`, `platformdirs`, `Pygments`, `pytokens`, `iniconfig`,
    `pluggy`)
- [ ] Generate `resources/MyIcon.ico` (multi-resolution, same Pillow
      approach `resources/makeicon.sh` already uses for `.icns`).
      `src/dm41l.spec` currently points `EXE(icon=...)` at the `.icns`
      file unconditionally — Windows needs `.ico` there. Branch the icon
      path on `platform.system()` in the spec.

## 2. Documentation

- [ ] `README.md` — what the tool is/does, a screenshot or two, and
      per-OS build/install instructions (the existing `src/build.sh`
      header comment has the bones of this already — pull it up to a
      real README).
- [ ] Link out to `docs/memory.md`, `docs/flags.md`, `docs/program.md`
      from the README so they're discoverable.
- [ ] `LICENSE` — **needs your decision.** MIT is the common default for
      a permissive hobby/utility project; something copyleft (GPL/AGPL)
      is the alternative if you want downstream changes to stay open.
      Not decided yet.
- [ ] Optional: `CONTRIBUTING.md` if you want outside PRs, issue
      templates if you want structured bug reports.

## 3. Code organization

- [ ] Split `src/memory.py` (78KB, single file) into a `memory/` package.
      Class boundaries are already clean (confirmed via
      `grep '^class '`), so this should be a mechanical move, not a
      redesign:
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

- [ ] **Test workflow** — run on push/PR across
      `ubuntu-latest` / `macos-latest` / `windows-latest`.
      Linux runner needs `sudo apt-get install python3-tk` explicitly
      (not bundled by default — same lesson this project already hit
      when testing under Xvfb).
- [ ] **Release workflow** — triggered on a version tag, builds on all
      three OSes (reuses `src/build.sh` / `dm41l.spec`), zips each
      platform's output, computes SHA256 checksums, and attaches both to
      a GitHub Release.

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

- [ ] **macOS**: add ad-hoc signing to `build.sh` — required on Apple
      Silicon just to run at all, and it's free:
      `codesign --force --deep --sign - "dist/DM41L Explorer.app"`
- [ ] Document the Gatekeeper workaround in the README (right-click the
      app → Open, confirm once) for anyone downloading a release
      binary — ad-hoc signing doesn't satisfy Gatekeeper's quarantine
      check, only full notarization ($99/yr Apple Developer Program)
      would remove the prompt entirely.
- [ ] **Windows**: document the SmartScreen click-through ("More info" →
      "Run anyway") in the README.
- [ ] Optional/later if the friction becomes a real problem:
      [SignPath.org](https://signpath.org)'s free code-signing program
      for open-source projects (requires acceptance + CI integration) —
      the only no-cost path to a real Windows signature.
- [ ] Publish SHA256 checksums with every release regardless, so users
      have an integrity check independent of signing.

## 7. Release process

- [ ] Tag a version (e.g. `v0.1.0`), let the release workflow build and
      publish artifacts.
- [ ] Write release notes summarizing what's in the first public build.
- [ ] Decide whether to keep `dm41l.spec`/`build.sh` as the single
      source of truth for local + CI builds (recommended — CI should
      just invoke `build.sh`, not duplicate its steps in YAML).

---
*Generated 2026-08-13 from a DM41L_Explorer planning session. See project
memory (`public_release_prep.md`) for the full reasoning behind each item.*
