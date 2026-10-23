"""Minimal Source1 VPK (v1/v2) reader for Dota 2.

Provides listing of entries and extraction of file data from the multi-chunk
`pak01_XXX.vpk` archive set indexed by `pak01_dir.vpk`.
"""
import os
import struct
import sys

VPK_SIGNATURE = 0x55AA1234


class VpkEntry:
    __slots__ = ("path", "crc", "preload", "archive_index", "offset", "length")

    def __init__(self, path, crc, preload, archive_index, offset, length):
        self.path = path
        self.crc = crc
        self.preload = preload
        self.archive_index = archive_index
        self.offset = offset
        self.length = length


class Vpk:
    def __init__(self, dir_path):
        self.dir_path = dir_path
        self.dir_dir = os.path.dirname(dir_path)
        self.base = os.path.basename(dir_path)
        # "pak01_dir.vpk" -> "pak01"
        self.prefix = self.base[:-8] if self.base.endswith("_dir.vpk") else self.base[:-4]
        self.entries = []
        self._parse()

    def _read_cstring(self, f):
        buf = bytearray()
        while True:
            c = f.read(1)
            if not c or c == b"\x00":
                break
            buf += c
        return buf.decode("utf-8", "replace")

    def _parse(self):
        with open(self.dir_path, "rb") as f:
            sig, version = struct.unpack("<II", f.read(8))
            if sig != VPK_SIGNATURE:
                raise ValueError("not a VPK file: %s" % self.dir_path)
            if version == 1:
                (tree_size,) = struct.unpack("<I", f.read(4))
            elif version == 2:
                tree_size, _file_data_size, _archive_md5_size, _other_md5_size, _sig_size = struct.unpack(
                    "<IIIII", f.read(20)
                )
            else:
                raise ValueError("unsupported VPK version %d" % version)

            end = f.tell() + tree_size
            while f.tell() < end:
                ext = self._read_cstring(f)
                if ext == "":
                    break
                while True:
                    folder = self._read_cstring(f)
                    if folder == "":
                        break
                    while True:
                        name = self._read_cstring(f)
                        if name == "":
                            break
                        crc, preload, archive_index, offset, length, term = struct.unpack(
                            "<IHHIIH", f.read(18)
                        )
                        if term != 0xFFFF:
                            raise ValueError("bad entry terminator")
                        if folder == " ":
                            full = "%s.%s" % (name, ext)
                        else:
                            full = "%s/%s.%s" % (folder, name, ext)
                        self.entries.append(
                            VpkEntry(full, crc, preload, archive_index, offset, length)
                        )
            self.preload_start = f.tell()

    def data(self, entry):
        """Return raw bytes for an entry (preload + archive data)."""
        out = bytearray()
        if entry.preload:
            with open(self.dir_path, "rb") as f:
                f.seek(self.preload_start)
                # preload section is laid out in entry order; recompute offset
                off = 0
                for e in self.entries:
                    if e is entry:
                        break
                    off += e.preload
                f.seek(self.preload_start + off)
                out += f.read(entry.preload)
        if entry.archive_index == 0x7FFF:
            with open(self.dir_path, "rb") as f:
                f.seek(entry.offset)
                out += f.read(entry.length)
        else:
            chunk = os.path.join(
                self.dir_dir, "%s_%03d.vpk" % (self.prefix, entry.archive_index)
            )
            with open(chunk, "rb") as f:
                f.seek(entry.offset)
                out += f.read(entry.length)
        return bytes(out)


if __name__ == "__main__":
    v = Vpk(sys.argv[1])
    pat = sys.argv[2] if len(sys.argv) > 2 else ""
    n = 0
    for e in v.entries:
        if pat in e.path:
            print(e.path)
            n += 1
    print("total matched: %d / %d" % (n, len(v.entries)), file=sys.stderr)
