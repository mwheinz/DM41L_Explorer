# -*- mode: python ; coding: utf-8 -*-
#
# Run via `./build.sh` from this directory (src/), not `pyinstaller`
# directly -- build.sh is what regenerates dm41version.py before pyinstaller
# runs, and it also clears out any previous build/dist first.

import os

ICON_PATH = "../resources/MyIcon.icns"
icon = ICON_PATH if os.path.exists(ICON_PATH) else None

a = Analysis(
    ["gui/app.py"],
    pathex=["."],
    binaries=[],
    # docs/flags.md is bundled so the Flags tab's live flag names match the
    # docs even when frozen. gui/flags_doc.py already falls back to its own
    # built-in copy of the same table if this can't be found at the
    # expected path inside the bundle, so a missing/stale copy here
    # degrades gracefully rather than crashing the app.
    datas=[("../docs/flags.md", "docs")],
    # dm41version.py is generated fresh by build.sh right before this spec
    # runs (see above) -- it's not imported anywhere except gui/app.py's
    # own `try: from dm41version import _version / except ImportError`, so
    # PyInstaller's static analysis won't find it on its own.
    hiddenimports=["dm41version"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [("O", None, "OPTION"), ("O", None, "OPTION")],
    exclude_binaries=True,
    name="dm41lexplorer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="dm41lexplorer",
)
app = BUNDLE(
    coll,
    name="DM41L Explorer.app",
    icon=icon,
    bundle_identifier=None,
    info_plist={
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "DM41L Memory Dump",
            # "Editor", not "Viewer" (unlike AtomDataExtractor's adv.spec):
            # File > Save Dump/Save Dump As... actually write .dm41 files,
            # this isn't a read-only viewer.
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Owner",
            "CFBundleTypeExtensions": ["dm41"],
        }],
    },
)
