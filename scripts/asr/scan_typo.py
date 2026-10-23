# -*- coding: utf-8 -*-
"""只读扫描 dataset.csv 中文 text 列中残留的专有名词错字。
复用 asr_names.py 的拼音匹配逻辑（官方译名表 + 英文字幕定位实体），
输出所有候选修改（不改动文件）。"""
import csv
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import asr_names  # noqa: E402  复用 name_table / find_slot / core / TIER
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

CSV_PATH = os.path.join(s2v_config.META_DIR, "dataset.csv")


def main():
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig", newline="")))
    rows = [r for r in rows if r.get("language") == "schinese"]
    by_fn = {r["filename"]: r for r in rows}
    table = sorted(asr_names.name_table().items(), key=lambda kv: -len(kv[0]))

    import re
    applied = []
    for r in rows:
        fn = r["filename"]
        text = r["text"]
        c = asr_names.core(text)
        if not c:
            continue
        en = r["text_en_reference"] or ""
        used = set()
        for enn, z in table:
            m = None
            for cand in re.finditer(r"(?<![A-Za-z])" + re.escape(enn) + r"(?![A-Za-z])", en):
                if any(i in used for i in range(cand.start(), cand.end())):
                    continue
                m = cand
                break
            if not m:
                continue
            used.update(range(m.start(), m.end()))
            if z in c:
                continue
            hit = asr_names.find_slot(c, z)
            if not hit:
                # 孪生录音回退
                new, tier, wrong = None, None, None
                twin = None
                if fn.startswith("helmet_sylph_"):
                    twin = "sylph_" + fn[len("helmet_sylph_"):]
                elif fn.startswith("sylph_"):
                    twin = "helmet_sylph_" + fn[len("sylph_"):]
                if twin and twin in by_fn and z in asr_names.core(by_fn[twin]["text"]):
                    new, tier, wrong = by_fn[twin]["text"], "twin", c
            else:
                i, L, target, tier, _, _ = hit
                wrong = c[i:i + L]
                pos = [k for k, ch in enumerate(text) if ch.isalnum()]
                s, e = pos[i], pos[i + L - 1] + 1
                new = text[:s] + target + text[e:]
            if new is None or new == text:
                continue
            applied.append({
                "fn": fn, "name": enn, "expected": z, "wrong": wrong,
                "tier": tier, "kind": asr_names.TIER.get(tier, tier),
                "old": text, "new": new,
            })

    print(f"扫描 {len(rows)} 条, 检出残留专有名词错字 {len(applied)} 处")
    print("=" * 78)
    for a in applied:
        print(f"{a['fn']:30s} [{a['name']:16s}] {a['kind']:16s}")
        print(f"   错: {a['old']}   (应为 {a['expected']}, 错写成 {a['wrong']})")
        print(f"   改: {a['new']}")


if __name__ == "__main__":
    main()
