"""Extract matching entries from a Dota 2 VPK set."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vpk import Vpk


def extract(vpk_path, prefixes, out_dir, exts=None, verbose=True):
    v = Vpk(vpk_path)
    picked = []
    for e in v.entries:
        if exts and not any(e.path.endswith(x) for x in exts):
            continue
        if any(e.path.startswith(p) for p in prefixes):
            picked.append(e)
    if verbose:
        print("%s -> %d files" % (vpk_path, len(picked)))
    for e in picked:
        dest = os.path.join(out_dir, e.path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(v.data(e))
    return picked


if __name__ == "__main__":
    import json

    cfg = json.loads(sys.argv[1])
    extract(cfg["vpk"], cfg["prefixes"], cfg["out"], cfg.get("exts"))
