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

    def __init__(self, device_path: str, debug=False):
        if debug:
            from .logger import enable_debug
            enable_debug()

        self.device_path = Path(device_path)
        self.fd = None
        self.block_size = None
        self.journal_inode = None
        self.journal_blocks = []

        self._open()
        log_debug("Opened")
        self._read_superblock()
        log_debug("Read super block")
        # self._locate_journal_inode()
        # log_debug("Inode located")
        self._read_journal_inode()
        log_debug("Inode read")

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
        self.blocks_per_group = struct.unpack_from("<I", sb, 0x20)[0]
        self.log_groups_per_flex = struct.unpack_from("<B", sb, 0x7C)[0]
        self.groups_per_flex = 1 << self.log_groups_per_flex
        
        self.inodes_per_group = struct.unpack_from("<I", sb, 0x28)[0]
        log_debug(f"Inodes per group: {self.inodes_per_group}")

        self.journal_inode = struct.unpack_from("<I", sb, 0x38)[0]
        self.inode_size = struct.unpack_from("<H", sb, 0x58)[0]
        
        self.gd_size = struct.unpack_from("<H", sb, 0xFE)[0]
        if self.gd_size == 0:
            self.gd_size = 32
        log_debug(f"Group desc size: {self.gd_size}")
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

        gd = self.read_range(gd_offset, self.gd_size)

        # # まずは下位32bitだけを使う（多くの環境でこれで十分）
        # inode_table_lo = struct.unpack_from("<I", gd, 8)[0]
        # self.inode_table_block = inode_table_lo

        log_debug(f"GD offset: {gd_offset}")
        # log_debug(f"inode_table_lo={inode_table_lo}")
        log_debug(f"Inode table block: {self.inode_table_block}")
        

    def _parse_extent_leaf(self, inode, entries):
        """Parse ext4_extent structures in a leaf node."""
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

    def _get_inode_table_block(self, group: int) -> int:
        flex_group = group // self.groups_per_flex
        first_gd_block = 1  # block_size > 1024 の場合

        gd_offset = (
            first_gd_block * self.block_size
            + flex_group * self.groups_per_flex * self.gd_size
            + (group % self.groups_per_flex) * self.gd_size
        )

        gd = self.read_range(gd_offset, self.gd_size)

        inode_table_lo = struct.unpack_from("<I", gd, 8)[0]
        inode_table_hi = 0
        if self.gd_size >= 64:
            inode_table_hi = struct.unpack_from("<I", gd, 0x28)[0]

        inode_table_block = inode_table_lo | (inode_table_hi << 32)

        log_debug(f"Group {group}: flex_group={flex_group}, GD offset={gd_offset}, inode_table_block={inode_table_block}")
        return inode_table_block

    def _read_journal_inode(self):
        """Read the journal inode and extract journal block ranges via extents."""
        self.journal_blocks = []

        inode_num = self.journal_inode
        group = (inode_num - 1) // self.inodes_per_group
        index = (inode_num - 1) % self.inodes_per_group

        inode_table_block = self._get_inode_table_block(group)

        inode_offset = (
            inode_table_block * self.block_size
            + index * self.inode_size
        )

        log_debug(f"inode_num={inode_num}, group={group}, index={index}")
        log_debug(f"inode_offset={inode_offset}")

        # ここで必ず inode_offset を使って inode を読む
        inode = self.read_range(inode_offset, self.inode_size)
        inode = self.read_range(inode_offset, self.inode_size)

        # i_mode が 0 なら「未使用 inode」
        i_mode = struct.unpack_from("<H", inode, 0x0)[0]
        i_blocks = struct.unpack_from("<I", inode, 0x1C)[0]

        if i_mode == 0 or i_blocks == 0:
            log_debug("Journal inode is unused or has no blocks (no internal journal).")
            self.journal_blocks = []
            return

        # ---- i_flags を確認して extents かどうか判定 ----
        i_flags = struct.unpack_from("<I", inode, 0x20)[0]
        log_debug(f"i_flags=0x{i_flags:08x}")

        EXT4_EXTENTS_FL = 0x00080000

        # ---- Non-extents (legacy block map) ----
        if not (i_flags & EXT4_EXTENTS_FL):
            log_debug("Journal inode uses legacy block map (not extents).")

            # i_block は offset 40 から 60 bytes
            blocks = struct.unpack_from("<15I", inode, 40)
            log_debug(f"i_block entries: {blocks}")

            # 直接ブロック 0〜11 を読む
            for b in blocks[:12]:
                if b != 0:
                    self.journal_blocks.append(b)

            # 1段間接ブロック（必要なら後で実装）
            indirect = blocks[12]
            if indirect != 0:
                log_debug(f"Indirect block at {indirect} (not yet implemented)")
                # TODO: implement reading indirect block

            return

        # ---- Parse extent header ----
        # i_block starts at offset 40
        eh_magic, eh_entries, eh_max, eh_depth, eh_generation = struct.unpack_from(
            "<HHHHI", inode, 40
        )
        log_debug(f"eh_magic=0x{eh_magic:04x}, entries={eh_entries}, depth={eh_depth}")

        if eh_magic != 0xF30A:
            raise ValueError("Invalid extent header magic. Not an ext4 extent inode.")

        log_debug(f"Extent header: entries={eh_entries}, depth={eh_depth}")

        # ---- Case 1: extent tree depth = 0 (leaf node) ----
        if eh_depth == 0:
            self._parse_extent_leaf(inode, eh_entries)
            return

        # ---- Case 2: depth > 0 (internal nodes) ----
        self._parse_extent_internal(inode, eh_depth)


    def read_journal_blocks(self):
        """Yield only journal blocks"""
        for block in self.journal_blocks:
            offset = block * self.block_size
            data = self.read_range(offset, self.block_size)

            yield {
                "block_number": block,
                "raw": data,
            }
        log_debug(f"journal_blocks={self.journal_blocks}")

    def close(self):
        if self.fd:
            self.fd.close()
