"""Merge sharded ASR caches into metadata/asr_cache.json."""
import glob
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

ROOT = s2v_config.DATASET_DIR
meta = os.path.join(ROOT, "metadata")

merged = {}
for p in sorted(glob.glob(os.path.join(meta, "asr_cache*.json"))
                 + glob.glob(os.path.join(meta, "asr_retry*.json"))):
    d = json.load(open(p, encoding="utf-8"))
    for k, v in d.items():
        if v.strip() or k not in merged:
            merged[k] = v
    print("%-40s %d entries" % (os.path.basename(p), len(d)))

out = os.path.join(meta, "asr_cache.json")
json.dump(merged, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
filled = sum(1 for v in merged.values() if v.strip())
print("merged -> %s : %d entries, %d with text" % (out, len(merged), filled))

for p in glob.glob(os.path.join(meta, "asr_cache.part*.json")) + \
        glob.glob(os.path.join(meta, "asr_retry*.json")):
    os.remove(p)
    print("removed", os.path.basename(p))
