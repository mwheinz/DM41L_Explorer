import sys
import argparse
from pathlib import Path
from memory import Memory, StatusRegisters, ExtendedMemory


def print_status_registers(sr: StatusRegisters):
    print(f"{'='*40}")
    print("Status Registers")
    print(f"{'='*40}")
    for addr in range(0x00, 0x10):
        label_info = sr.label_for(addr)
        if label_info:
            print(label_info + " / " + sr.get_register(addr).get_hex())
        else:
            print(f"Addr {addr:02x}: Unknown format")
    print("-" * 40)
    print(f"Alpha Register: '{str(sr.alpha)}' / {sr.alpha.get_hex()}")


def print_extended_memory(xm: ExtendedMemory):
    print(f"{'='*40}")
    print("Extended Memory")
    print(f"{'='*40}")
    files = xm.list_files()
    if not files:
        print("(no files found)")
        return

    for f in files:
        print(
            f"{f.name!r:<12} {f.type_label:<6} "
            f"header=0x{f.header_addr:03x}  data=0x{f.data_start:03x}-0x{f.data_end:03x} "
            f"({f.num_registers} registers, header declares {f.declared_length})"
        )
        if f.file_type == xm.TYPE_DATA:
            numbers = f.get_numbers()
            preview = ", ".join(f"{n:g}" for n in numbers[:8])
            more = f", ... ({len(numbers)} total)" if len(numbers) > 8 else ""
            print(f"    {preview}{more}")
        elif f.file_type == xm.TYPE_ASCII:
            records = f.get_records()
            preview = ", ".join(repr(r) for r in records[:8])
            more = f", ... ({len(records)} total)" if len(records) > 8 else ""
            print(f"    {preview}{more}")
        print()


def inspect(file_path: str):
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File '{file_path}' not found.")
        return

    try:
        memory = Memory.from_file(path)
        sr = StatusRegisters(memory)
        xm = ExtendedMemory(memory, address_range=[0x40, 0x3FF])

        print(f"Source: {path.name}")
        print_status_registers(sr)
        print()
        print_extended_memory(xm)

    except Exception as e:
        print(f"An error occurred while parsing the file: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="Inspect the status registers and extended memory of a DM41 dump file."
    )
    parser.add_argument("filename", help="Path to the .dm41 dump file")
    args = parser.parse_args()
    inspect(args.filename)


if __name__ == "__main__":
    main()
