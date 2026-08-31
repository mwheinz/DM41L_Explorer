DM41L Explorer
==============

This folder is the complete application:

  dm41lexplorer (or dm41lexplorer.exe on Windows)   <- run this
  _internal/                                        <- required support
                                                        files (Python
                                                        runtime, bundled
                                                        libraries, docs)
  library/                                          <- sample .dm41
                                                        programs, browse
                                                        or copy freely

_internal/ isn't optional or extra -- it's not safe to delete it, and if
you move the app somewhere else (a different folder, a USB drive, etc.),
move it along with the executable rather than leaving it behind. This is
standard PyInstaller "onedir" packaging, not something specific to this
app.

library/ is just data -- sample programs to load via File > Open Dump,
or Import into an existing dump. Nothing else in the app depends on it,
so it's fine to browse, copy files out of, or delete.

Full usage instructions, known limitations, and how to get past the
Windows SmartScreen "unknown publisher" warning on this unsigned build
are in the project's README on GitHub:
https://github.com/mwheinz/DM41L_Explorer
