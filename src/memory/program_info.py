'''
ProgramInfo: one entry ("chain link") found while walking the global
label/END chain in program memory. See Memory.list_programs() in
memory.py, and docs/program.md sec 5, for the full derivation.
'''

from typing import Optional


class ProgramInfo:
    '''
    One entry found while walking the "global chain" -- the backward-
    linked list of every global alpha label and END marker in program
    memory, described in docs/program.md sec 5 (reverse-engineered from
    sample dumps and Wickes' "Synthetic Programming on the HP-41C",
    section 2C).

    `name` is set for a global alpha label -- what CAT 1 shows as a
    program's name -- and is None for a plain END marker. Do NOT assume
    these pair up one-to-one with "programs": per the user's own testing
    against a modified copy of 6x-xm.dm41, a single END can have zero,
    one, or several global labels chained to it. Each ProgramInfo is just
    one independent chain link (a label header or an END marker), not "a
    program's boundary" -- `kind` says which it is.

    `distance_bytes` (built from the raw `bbb`/`distance_registers` marker
    fields, plus `end_type` for END entries -- see docs/program.md sec 5.1)
    is the byte distance *this* entry's own marker reports onward to the
    next chain link the backward walk visits from here. It is NOT a
    program's size -- it's the only per-entry number the chain format
    actually encodes, exposed as-is (rather than interpreted) so it can be
    weighed against CAT 1's reported program byte lengths while that
    reconciliation is still being researched (see docs/program.md's open
    TODOs). Showing an interpreted "size" here, before that's resolved,
    was the mistake an earlier attempt at a Program tab made (see project
    notes) -- this deliberately shows the raw marker data instead.

    One entry can be the permanent `.END.` itself (`end_type == 2`) -- the
    newest thing in program memory, sitting right where the most-recently-
    created chain link's own "next END" would otherwise be. An earlier
    version of `list_programs()` always discarded this one, on the theory
    it was bookkeeping rather than a real chain link; the user's own
    byte-count comparison against a real CAT 1 listing showed that was
    wrong to assume -- the newest program's reported byte count can extend
    into exactly the bytes this entry's distance covers. It's now included
    like any other entry, distinguished via `kind` (`".END."` rather than
    `"END"`) so it reads clearly as the top-of-memory marker, not a
    duplicate of a normal END.
    '''

    def __init__(
        self,
        header_addr: int,
        header_offset: int,
        name: Optional[str],
        key_assignment: Optional[int],
        distance_bytes: int,
        bbb: int,
        distance_registers: int,
        end_type: Optional[int],
    ):
        self.header_addr = header_addr
        self.header_offset = header_offset
        self.name = name
        self.key_assignment = key_assignment
        self.distance_bytes = distance_bytes
        self.bbb = bbb
        self.distance_registers = distance_registers
        self.end_type = end_type

    @property
    def is_named(self) -> bool:
        return self.name is not None

    @property
    def kind(self) -> str:
        '''"LBL" for a global-label header, "END" for a plain END marker,
        or ".END." for the one permanent end-of-program-memory marker
        (end_type == 2) -- the newest entry in the chain, when present.'''
        if self.is_named:
            return "LBL"
        return ".END." if self.end_type == 2 else "END"

    @property
    def display_name(self) -> str:
        return self.name if self.name is not None else "END"

    @property
    def address_label(self) -> str:
        return f"0x{self.header_addr:03x}:{self.header_offset}"

    @property
    def distance_label(self) -> str:
        return f"{self.distance_bytes} byte{'s' if self.distance_bytes != 1 else ''}"

    def __repr__(self):
        return (
            f"ProgramInfo({self.kind} {self.display_name!r} "
            f"@ {self.address_label}, distance={self.distance_bytes})"
        )
