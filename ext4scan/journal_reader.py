# ext4scan/journal_reader.py

import mmap
import struct
from pathlib import Path
from .logger import log_debug

EXT4_SUPERBLOCK_OFFSET = 1024
EXT4_SUPERBLOCK_SIZE = 1024

class JournalReader:
    """
    Minimal reader for ext4 journal blocks.
    Reads:
    - superblock
    - journal inode
    - journal block range
    """

    def __init__(self, device_path: str):
        self.device_path = Path(device_path)
        self.fd = None
        self.mm = None
        self.block_size = None
        self.journal_block_start = None
        self.journal_block_count = None

        self._open()
        self._read_superblock()
        self._locate_journal()

    def _open(self):
        log_debug(f"Opening device/image: {self.device_path}")
        self.fd = self.device_path.open("rb")
        # self.mm = mmap.mmap(self.fd.fileno(), 0, access=mmap.ACCESS_READ)
        self.mm = self.fd.read()

    def _read_superblock(self):
        log_debug("Reading ext4 superblock...")

        sb = self.mm[EXT4_SUPERBLOCK_OFFSET : EXT4_SUPERBLOCK_OFFSET + EXT4_SUPERBLOCK_SIZE]

        # offset 0x18 = log_block_size
        log_block_size = struct.unpack_from("<I", sb, 0x18)[0]
        self.block_size = 1024 << log_block_size

        # offset 0x38 = journal inode number
        journal_inode = struct.unpack_from("<I", sb, 0x38)[0]

        log_debug(f"Block size: {self.block_size}")
        log_debug(f"Journal inode: {journal_inode}")

        self.journal_inode = journal_inode

    def _locate_journal(self):
        """
        MVP: assume journal is at fixed location (common for many ext4 systems)
        Later: read inode table to get exact journal location.
        """
        log_debug("Locating journal (MVP: fixed offset assumption)...")

        # MVP: assume journal starts at block 0x10000 (typical for many ext4)
        # Later: read inode table to get exact location
        self.journal_block_start = 0x10000
        self.journal_block_count = 1024  # MVP: arbitrary small range

        log_debug(f"Journal start block: {self.journal_block_start}")
        log_debug(f"Journal block count: {self.journal_block_count}")

    def read_journal_blocks(self):
        """
        Generator: yields raw journal blocks.
        """
        for i in range(self.journal_block_count):
            block_num = self.journal_block_start + i
            offset = block_num * self.block_size
            data = self.mm[offset : offset + self.block_size]

            yield {
                "block_number": block_num,
                "raw": data,
            }

    def close(self):
        if self.mm:
            self.mm.close()
        if self.fd:
            self.fd.close()
