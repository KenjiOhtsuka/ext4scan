# ext4scan/jbd2_parser.py

import struct
from .logger import log_debug

JBD2_MAGIC = 0xC03B3998

JBD2_BLOCKTYPE_DESCRIPTOR = 1
JBD2_BLOCKTYPE_COMMIT     = 2
JBD2_BLOCKTYPE_REVOKE     = 3
JBD2_BLOCKTYPE_SUPER_V2   = 4
JBD2_BLOCKTYPE_SUPER_V3   = 5


class JBD2Parser:
    """
    JBD2 parser (ext4 internal journal, big-endian on disk).

    共通ヘッダ (big endian):
      u32 magic      (0xC03B3998)
      u32 blocktype  (1=desc, 2=commit, 3=revoke, 4/5=super)
      u32 sequence

    blocktype ごとの最低限のパースだけ行い、
    タイムライン構築に使えそうな情報を dict で返す。
    """

    def _unpack_u32(self, raw, offset):
        return struct.unpack_from(">I", raw, offset)[0]

    def _unpack_u16(self, raw, offset):
        return struct.unpack_from(">H", raw, offset)[0]

    def parse_block(self, block):
        raw = block["raw"]
        block_number = block["block_number"]

        if len(raw) < 12:
            return None

        # JBD2 header (big endian)
        magic = self._unpack_u32(raw, 0)
        blocktype = self._unpack_u32(raw, 4)
        sequence = self._unpack_u32(raw, 8)

        if magic != JBD2_MAGIC:
            return None

        # ---- commit block ----
        if blocktype == JBD2_BLOCKTYPE_COMMIT:
            # commit header:
            #   u32 magic
            #   u32 blocktype
            #   u32 sequence
            #   u32 sec
            #   u32 nsec (optional, checksum v3 では後ろに checksum 等)
            if len(raw) >= 16:
                sec = self._unpack_u32(raw, 12)
            else:
                sec = 0

            log_debug(
                f"JBD2 COMMIT: block={block_number}, seq={sequence}, ts={sec}"
            )

            return {
                "block_number": block_number,
                "blocktype": "commit",
                "sequence": sequence,
                "timestamp": sec,
            }

        # ---- descriptor block ----
        if blocktype == JBD2_BLOCKTYPE_DESCRIPTOR:
            # descriptor block:
            #   header(12) の後ろに tag が並ぶ
            #   tag (v3 相当をかなり簡略化して読む):
            #     u32 blocknr
            #     u16 flags
            #     u16 checksum (無視)
            #   実際には 16 bytes 単位だが、ここでは先頭 8 bytes だけ使う
            tags = []
            offset = 12
            while offset + 8 <= len(raw):
                blocknr = self._unpack_u32(raw, offset)
                flags   = self._unpack_u16(raw, offset + 4)

                # blocknr==0 はパディングとみなして終了
                if blocknr == 0:
                    break

                tags.append(
                    {
                        "blocknr": blocknr,
                        "flags": flags,
                    }
                )
                # JBD2 の tag は 16 bytes 単位が多いので 16 ずつ進める
                offset += 16

            log_debug(
                f"JBD2 DESC: block={block_number}, seq={sequence}, tags={len(tags)}"
            )

            return {
                "block_number": block_number,
                "blocktype": "descriptor",
                "sequence": sequence,
                "tags": tags,
            }

        # ---- revoke block ----
        if blocktype == JBD2_BLOCKTYPE_REVOKE:
            # revoke block:
            #   header(12) の後ろに revoke ヘッダ + blocknr 群
            #   ここでは単純に u32 の配列として読む
            revoked = []
            offset = 12
            while offset + 4 <= len(raw):
                blocknr = self._unpack_u32(raw, offset)
                if blocknr == 0:
                    break
                revoked.append(blocknr)
                offset += 4

            log_debug(
                f"JBD2 REVOKE: block={block_number}, seq={sequence}, revoked={len(revoked)}"
            )

            return {
                "block_number": block_number,
                "blocktype": "revoke",
                "sequence": sequence,
                "revoked": revoked,
            }

        # ---- superblock v2/v3 ----
        if blocktype in (JBD2_BLOCKTYPE_SUPER_V2, JBD2_BLOCKTYPE_SUPER_V3):
            # journal superblock:
            #   header(12) の後ろに jbd2 super 情報
            #   ここではごく一部だけ拾う
            #   u32 blocksize
            #   u32 maxlen
            #   u32 first
            blocksize = self._unpack_u32(raw, 12) if len(raw) >= 16 else 0
            maxlen    = self._unpack_u32(raw, 16) if len(raw) >= 20 else 0
            first     = self._unpack_u32(raw, 20) if len(raw) >= 24 else 0

            log_debug(
                f"JBD2 SUPER: block={block_number}, type={blocktype}, "
                f"blocksize={blocksize}, maxlen={maxlen}, first={first}"
            )

            return {
                "block_number": block_number,
                "blocktype": "super",
                "sequence": sequence,
                "journal_blocksize": blocksize,
                "journal_maxlen": maxlen,
                "journal_first": first,
                "super_version": 3 if blocktype == JBD2_BLOCKTYPE_SUPER_V3 else 2,
            }

        # 未対応の blocktype はスキップ
        log_debug(
            f"JBD2 UNKNOWN: block={block_number}, type={blocktype}, seq={sequence}"
        )
        return None
