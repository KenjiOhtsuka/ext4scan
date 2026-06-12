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

        self.journal_inode = struct.unpack_from("<I", sb, 0xE0)[0]

        log_debug(f"Block size: {self.block_size}")
        log_debug(f"Journal inode: {self.journal_inode}")

    def _locate_journal_inode(self):
        """
        Read group descriptor 0 to locate inode table.
        """
        if self.block_size == 1024:
            gd_offset = self.block_size * 2
        else:
            gd_offset = self.block_size
        gd = self.read_range(gd_offset, 32)

        self.inode_table_block = struct.unpack_from("<I", gd, 8)[0]
        log_debug(f"Inode table block: {self.inode_table_block}")

    def _parse_extent_leaf(self, inode, entries):
        """Parse ext4_extent structures in a leaf node."""
        self.journal_blocks = []

        # extents start at offset 40 + 12 = 52
        offset = 40 + 12

        for i in range(entries):
            ee_block, ee_len, ee_start_hi, ee_start_lo = struct.unpack_from(
                "<IHHI", inode, offset + i * 12
            )

            phys = (ee_start_hi << 32) | ee_start_lo

            log_debug(f"Extent: logical={ee_block}, len={ee_len}, phys={phys}")

            # Add each physical block in the extent
            for b in range(ee_len):
                self.journal_blocks.append(phys + b)

    def _parse_extent_internal(self, inode, depth):
        """Parse internal extent nodes (rare for journal inode)."""

        # internal nodes contain ext4_extent_idx entries
        # struct ext4_extent_idx {
        #   __le32 ei_block;
        #   __le32 ei_leaf_lo;
        #   __le16 ei_leaf_hi;
        #   __le16 ei_unused;
        # }

        offset = 40 + 12
        entries = struct.unpack_from("<H", inode, 42)[0]

        for i in range(entries):
            ei_block, ei_leaf_lo, ei_leaf_hi, _ = struct.unpack_from(
                "<IIHH", inode, offset + i * 12
            )

            leaf_phys = (ei_leaf_hi << 32) | ei_leaf_lo
            leaf_offset = leaf_phys * self.block_size

            log_debug(f"Internal extent node → leaf at block {leaf_phys}")

            # Read the leaf block and parse it as a leaf node
            leaf = self.read_range(leaf_offset, self.block_size)

            # Parse leaf extent header
            eh_magic, eh_entries, eh_max, eh_depth, eh_generation = struct.unpack_from(
                "<HHHHI", leaf, 0
            )

            if eh_magic != 0xF30A:
                raise ValueError("Invalid extent header in leaf node.")

            self._parse_extent_leaf(leaf, eh_entries)


    def _read_journal_inode(self):
        """Read the journal inode and extract journal block ranges via extents."""

        inode_size = struct.unpack_from("<H", sb, 0x58)[0]
        inode_index = self.journal_inode - 1

        inode_offset = (
            self.inode_table_block * self.block_size
            + inode_index * inode_size
        )

        inode = self.read_range(inode_offset, inode_size)

        # ---- Parse extent header ----
        # i_block starts at offset 40
        eh_magic, eh_entries, eh_max, eh_depth, eh_generation = struct.unpack_from(
            "<HHHHI", inode, 40
        )

        if eh_magic != 0xF30A:
            raise ValueError("Invalid extent header magic. Not an ext4 extent inode.")

        log_debug(f"Extent header: entries={eh_entries}, depth={eh_depth}")

        # ---- Case 1: extent tree depth = 0 (leaf node) ----
        if eh_depth == 0:
            self._parse_extent_leaf(inode, eh_entries)
            return

        # ---- Case 2: depth > 0 (internal nodes) ----
        # For journal inode, depth is usually 0, but handle general case
        self._parse_extent_internal(inode, eh_depth)


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
