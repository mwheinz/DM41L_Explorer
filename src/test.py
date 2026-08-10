import sys
import argparse
from pathlib import Path
from memory import Memory, StatusRegisters, STATUS_REGISTER_LABELS

def print_status_registers(file_path: str):
    """Loads a DM41 dump and prints all status register values."""
    path = Path(file_path)
    
    if not path.exists():
        print(f"Error: File '{file_path}' not found.")
        return

    try:
        # Load memory from file
        memory = Memory.from_file(path)
        sr = StatusRegisters(memory)
        
        print(f"{'='*40}")
        print(f"DM41 Status Registers Dump")
        print(f"Source: {path.name}")
        print(f"{'='*40}")

        # 1. Print the named system registers T through e using label_for logic
        # The class method label_for uses addresses 0x00 - 0x0F 
        # to determine formatting and labels.
        for addr in range(0x00, 0x10):
            label_info = sr.label_for(addr)
            if label_info:
                print(label_info + " / " + sr.get_register(addr).get_hex())
            else:
                print(f"Addr {addr:02x}: Unknown format")

        # 2. Print Alpha register separately as it is a special composition property 
        # and not accessed via simple memory addressing in the same way.
        print("-" * 40)
        # get_ascii() shows non-printable as dots for predictability
        print(f"Alpha Register: '{str(sr.alpha)}' / {sr.alpha.get_hex()}")
        print(f"{'='*40}")

    except Exception as e:
        print(f"An error occurred while parsing the file: {e}")
        import traceback
        traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(
        description="Inspect the status registers of a DM41 memory dump file."
    )
    parser.add_argument(
        "filename", 
        help="Path to the .dm41 dump file"
    )
    
    args = parser.parse_args()
    print_status_registers(args.filename)

if __name__ == "__main__":
    main()

