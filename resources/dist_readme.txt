DM41L Explorer
==============

This folder is the complete application -- both files/folders below have
to stay together in the same place to run:

  dm41lexplorer (or dm41lexplorer.exe on Windows)   <- run this
  _internal/                                        <- required support
                                                        files (Python
                                                        runtime, bundled
                                                        libraries, docs)

_internal/ isn't optional or extra -- it's not safe to delete it, and if
you move the app somewhere else (a different folder, a USB drive, etc.),
move this whole folder as a unit rather than just the executable. This
is standard PyInstaller "onedir" packaging, not something specific to
this app.

Full usage instructions, known limitations, and how to get past the
Windows SmartScreen "unknown publisher" warning on this unsigned build
are in the project's README on GitHub:
https://github.com/mwheinz/DM41L_Explorer
