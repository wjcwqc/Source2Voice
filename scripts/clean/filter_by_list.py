# -*- coding: utf-8 -*-
"""按 schinese_dark_willow_vo_pure.list 过滤 darkwillow_dataset_new.csv，
保留清单中的条目，其余删除，另存为 dataset.csv（匹配字段：wav 路径）。"""
import os
import csv
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

CSV_PATH = os.path.join(s2v_config.META_DIR, "darkwillow_dataset_new.csv")
LIST_PATH = os.path.join(s2v_config.META_DIR, "schinese_dark_willow_vo_pure.list")
OUT_PATH = os.path.join(s2v_config.META_DIR, "dataset.csv")


def main():
    # 1. 读取清单：path|speaker|lang|text
    keep_paths = set()
    with open(LIST_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            path = line.split("|", 1)[0].strip()
            keep_paths.add(path)
    print(f"清单条目数: {len(keep_paths)}")

    # 2. 过滤 CSV（保留 BOM 与原引号风格）
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    wav_idx = header.index("wav")
    kept = [header]
    for row in rows[1:]:
        if not row:
            continue
        if row[wav_idx].strip() in keep_paths:
            kept.append(row)
    print(f"CSV 原始数据行: {len(rows) - 1}, 保留行: {len(kept) - 1}, 删除行: {len(rows) - len(kept)}")

    # 3. 校验：清单中有但 CSV 未匹配到的条目
    csv_paths = {row[wav_idx].strip() for row in rows[1:] if row}
    missing = keep_paths - csv_paths
    if missing:
        print(f"[警告] 清单中有 {len(missing)} 条未在 CSV 中找到，示例:", file=sys.stderr)
        for p in sorted(missing)[:10]:
            print("  " + p, file=sys.stderr)
    else:
        print("校验通过：清单所有条目均已在 CSV 中匹配")

    # 4. 写出
    with open(OUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(kept)
    print(f"已写出: {OUT_PATH} ({len(kept) - 1} 条数据)")


if __name__ == "__main__":
    main()
