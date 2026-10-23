# -*- coding: utf-8 -*-
"""对比 dataset.csv 的 text 列 与 schinese_dark_willow_vo_pure.list 的文本，列出差异。"""
import os
import csv
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

CSV_PATH = os.path.join(s2v_config.META_DIR, "dataset.csv")
LIST_PATH = os.path.join(s2v_config.META_DIR, "schinese_dark_willow_vo_pure.list")

# list: path -> text
list_text = {}
with open(LIST_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        parts = line.split("|")
        path = parts[0].strip()
        text = parts[3] if len(parts) >= 4 else ""
        list_text[path] = text

rows = list(csv.reader(open(CSV_PATH, encoding="utf-8-sig", newline="")))
header = rows[0]
wav_idx = header.index("wav")
txt_idx = header.index("text")

same, diff, missing = 0, 0, 0
diff_pairs = []
for row in rows[1:]:
    if not row:
        continue
    path = row[wav_idx].strip()
    csv_txt = row[txt_idx]
    if path not in list_text:
        missing += 1
        continue
    lt = list_text[path]
    if csv_txt == lt:
        same += 1
    else:
        diff += 1
        diff_pairs.append((path, csv_txt, lt))

print(f"相同: {same}  不同: {diff}  清单缺失: {missing}")
print("=" * 70)
for path, csv_txt, lt in diff_pairs:
    name = path.split("/")[-1]
    print(f"{name}")
    print(f"  CSV : {csv_txt}")
    print(f"  list: {lt}")
