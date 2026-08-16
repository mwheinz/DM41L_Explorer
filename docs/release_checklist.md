# DM41L Explorer — Public Release Checklist

Status as of 2026-08-13: the repo (`github.com/mwheinz/DM41L_Explorer`) is
already **public**, but is missing the documentation, licensing, and CI/CD
that make a public repo usable and trustworthy to a stranger. Nothing here
is urgent/blocking each other — pick items in any order — but README +
LICENSE are the highest-leverage starting point.

## 1. Cross-platform build/test environment

- [X] Windows: use GitHub Actions' `windows-latest` runner as the primary
  native x64 build/test machine — no local Windows box needed for CI.
- [ ] For manual GUI smoke-testing, a **Windows 11 ARM64 VM in UTM** on your
  Apple Silicon Mac works well (native Apple virtualization, not slow QEMU
  emulation). No official free ARM64 ISO from Microsoft, but the Windows
  Insider Program provides one, or build one via UUP dump. Windows 11 ARM
  includes x64 emulation, so it can run your standard x64 PyInstaller build. I
  still don't know the correct way to get a free Windows license for this
  purpose.
- [ ] Linux (Ubuntu via UTM, already set up): keep as-is for manual testing;
  matches the `ubuntu-latest` CI runner reasonably well.

## 2. Distribution trust / code signing (no paid dev accounts)

- [ ] Optional, if codesigning becomes a significant source of friction:
      [SignPath.org](https://signpath.org)'s free code-signing program
      for open-source projects (requires acceptance + CI integration) —
      the only no-cost path to a real Windows signature.

## 4. Release process

- [ ] Write release notes summarizing what's in the first public build.
- [ ] Update the release workflow to use `dm41l.spec`/`build.sh` as the single
  source of truth for local + CI builds (recommended — CI should just invoke
  `build.sh`, not duplicate its steps in YAML).
- [ ] Decide on a way to identify owners of the DM41L and advertise
  DM41L_Explorer to them.
