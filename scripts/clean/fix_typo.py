# -*- coding: utf-8 -*-
"""修复 dataset.csv 中确凿的专有名词错字：囚尸岭 -> 求师岭（Quoidge 官方译名，语料 4 票）。
仅替换 text 列中的目标词，并把该行 text_corrected 标记为 name-homophone。
保存回 dataset.csv（utf-8-sig，保持表头/列序/引号风格）。"""
import csv
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

CSV_PATH = os.path.join(s2v_config.META_DIR, "dataset.csv")
REPL = [("囚尸岭", "求师岭")]  # (错误词, 正确词)


def main():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    fi = header.index("filename")
    ti = header.index("text")
    ci = header.index("text_corrected")

    changed = []
    for row in rows[1:]:
        if not row:
            continue
        text = row[ti]
        orig = text
        for wrong, right in REPL:
            if wrong in text:
                text = text.replace(wrong, right)
        if text != orig:
            row[ti] = text
            row[ci] = "name-homophone"
            changed.append((row[fi], orig, text))

    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"修复 {len(changed)} 条 -> {os.path.basename(CSV_PATH)}")
    for fn, old, new in changed:
        print(f"  {fn}")
        print(f"    旧: {old}")
        print(f"    新: {new}")

    # 校验：不应再有 囚尸岭
    left = [r[fi] for r in rows[1:] if r and "囚尸岭" in (r[ti] or "")]
    print(f"\n残留 囚尸岭: {len(left)} 条 {'[FAIL]' if left else '[OK]'}")
    print(f"求师岭 条数: {sum(1 for r in rows[1:] if r and '求师岭' in (r[ti] or ''))}")


if __name__ == "__main__":
    main()
