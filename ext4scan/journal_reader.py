# ext4scan/journal_reader.py

import struct
import fcntl
from pathlib import Path
from .logger import log_debug

EXT4_SUPERBLOCK_OFFSET = 1024
EXT4_SUPERBLOCK_SIZE = 1024
BLKGETSIZE64 = 0x80081272


class JournalReader:
    """
    Minimal reader for ext4 journal blocks.
    Reads only necessary ranges:
    - superblock
    - journal inode
    - journal block range
    """

    def __init__(self, device_path: str):
        self.device_path = Path(device_path)
        self.fd = None
        self.block_size = None
        self.journal_inode = None
        self.journal_blocks = []

        self._open()
        self._read_superblock()
        self._locate_journal_inode()
        self._read_journal_inode()
        self._collect_journal_blocks()

    def _open(self):
        log_debug(f"Opening device/image: {self.device_path}")
        self.fd = self.device_path.open("rb")

    def read_range(self, offset, size):
        """Read only the required range."""
        self.fd.seek(offset)
        return self.fd.read(size)

    def _read_superblock(self):
        log_debug("Reading ext4 superblock...")

        sb = self.read_range(EXT4_SUPERBLOCK_OFFSET, EXT4_SUPERBLOCK_SIZE)

        log_block_size = struct.unpack_from("<I", sb, 0x18)[0]
        self.block_size = 1024 << log_block_size

        self.journal_inode = struct.unpack_from("<I", sb, 0x38)[0]

        log_debug(f"Block size: {self.block_size}")
        log_debug(f"Journal inode: {self.journal_inode}")

    def _locate_journal_inode(self):
        """
        Read group descriptor 0 to locate inode table.
        """
        gd_offset = self.block_size * 2
        gd = self.read_range(gd_offset, 32)

        self.inode_table_block = struct.unpack_from("<I", gd, 8)[0]
        log_debug(f"Inode table block: {self.inode_table_block}")

    def _read_journal_inode(self):
        """Read the journal inode to get i_block[]"""
        inode_size = 256  # ext4 default
        inode_index = self.journal_inode - 1

        inode_offset = (
            self.inode_table_block * self.block_size
            + inode_index * inode_size
        )

        inode = self.read_range(inode_offset, inode_size)

        # i_block[] = 15 * 4 bytes = 60 bytes
        self.i_block = struct.unpack_from("<15I", inode, 40)

        log_debug(f"i_block[]: {self.i_block}")

    def _collect_journal_blocks(self):
        """Collect journal block numbers from i_block[]"""
        for block in self.i_block:
            if block != 0:
                self.journal_blocks.append(block)

        log_debug(f"Journal blocks: {self.journal_blocks}")

    def read_journal_blocks(self):
        """Yield only journal blocks"""
        for block in self.journal_blocks:
            offset = block * self.block_size
            data = self.read_range(offset, self.block_size)

            yield {
                "block_number": block,
                "raw": data,
            }

    def close(self):
        if self.fd:
            self.fd.close()
