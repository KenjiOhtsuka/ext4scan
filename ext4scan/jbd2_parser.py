# ext4scan/jbd2_parser.py

import struct
from .logger import log_debug

JBD2_MAGIC = 0xC03B3998
JBD2_BLOCKTYPE_COMMIT = 2

class JBD2Parser:
    """
    Minimal JBD2 parser (MVP).
    Extracts:
    - magic
    - block type
    - sequence
    - timestamp
    """

    def parse_block(self, block):
        raw = block["raw"]
        block_number = block["block_number"]

        # JBD2 header is 12 bytes:
        # magic (4), blocktype (4), sequence (4)
        try:
            magic, blocktype, sequence = struct.unpack_from("<III", raw, 0)
        except struct.error:
            return None

        if magic != JBD2_MAGIC:
            return None

        if blocktype != JBD2_BLOCKTYPE_COMMIT:
            return None

        # commit block timestamp is at offset 0x0C
        timestamp = struct.unpack_from("<I", raw, 0x0C)[0]

        log_debug(f"Commit block found at {block_number}, seq={sequence}, ts={timestamp}")

        return {
            "block_number": block_number,
            "sequence": sequence,
            "timestamp": timestamp,
        }
