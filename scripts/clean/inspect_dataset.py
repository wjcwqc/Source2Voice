#!/usr/bin/env python3
"""Source2Voice · 台词质量体检（官方字幕场景）。

在拿到官方字幕、跳过 ASR 之后，先跑这个体检脚本确认语料质量，
再决定要不要人工/规则修正。

检查项
------
1. 空文本 / 纯符号文本
2. 重复台词（同一句多音频 —— 训练时会让模型对该句过度加权）
3. 极短文本（<= N 字符）
4. 非 ASCII 字符混入（正常英文也会用 … ’ 这类 Unicode 标点）
5. 语言混杂（英文语料里混入大量 CJK 字 = 文本错配）

用法
----
    python inspect_dataset.py --root <dataset_root> [--min-chars 2]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

RE_CJK = re.compile(r"[㐀-䶿一-鿿぀-ヿ]")
RE_ONLY_SYMBOL = re.compile(r"^[\W_]+$", re.UNICODE)


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 台词质量体检")
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", default=None,
                    help="默认读 <root>/metadata/manifest.json")
    ap.add_argument("--min-chars", type=int, default=2)
    ap.add_argument("--top", type=int, default=15, help="重复台词显示条数")
    a = ap.parse_args()

    mpath = a.manifest or os.path.join(a.root, "metadata", "manifest.json")
    if not os.path.exists(mpath):
        sys.exit("找不到 %s" % mpath)
    manifest = json.load(open(mpath, encoding="utf-8"))

    # 按英雄分组
    by_hero = collections.defaultdict(list)
    for m in manifest:
        by_hero[m.get("hero_key", "?")].append(m)

    total_problems = 0
    for hero in sorted(by_hero):
        rows = by_hero[hero]
        with_text = [m for m in rows if (m.get("text") or "").strip()]
        no_text = [m for m in rows if not (m.get("text") or "").strip()]

        tc = collections.Counter(m["text"].strip() for m in with_text)
        dups = [(t, c) for t, c in tc.items() if c > 1]
        dup_rows = sum(c for _, c in dups)

        short = [m for m in with_text if len(m["text"].strip()) <= a.min_chars]
        symbol_only = [m for m in with_text if RE_ONLY_SYMBOL.match(m["text"].strip())]
        cjk = [m for m in with_text if RE_CJK.search(m["text"])]
        nonascii = [m for m in with_text if not m["text"].isascii()]

        print("=" * 66)
        print("英雄 %s：%d clips，%d 有文本，%d 无文本（纯音效）"
              % (hero, len(rows), len(with_text), len(no_text)))
        print("-" * 66)
        print("  唯一台词数        : %d" % len(tc))
        print("  重复台词（种）    : %d（涉及 %d 行）" % (len(dups), dup_rows))
        print("  超短文本 (<=%d)    : %d" % (a.min_chars, len(short)))
        print("  纯符号文本        : %d" % len(symbol_only))
        print("  含 CJK 字符       : %d  ← 非中文语料里出现 = 文本错配" % len(cjk))
        print("  含 Unicode 标点   : %d  ← 正常（… ’ “ ”）" % len(nonascii))

        if dups:
            print("\n  重复台词 Top %d：" % a.top)
            for t, c in sorted(dups, key=lambda x: -x[1])[:a.top]:
                print("    %2dx  %s" % (c, t[:76]))
        if short:
            print("\n  超短文本样例：")
            for m in short[:8]:
                print("    %-58s %r" % (m["filename"][:58], m["text"][:30]))
        if cjk:
            print("\n  CJK 混入样例：")
            for m in cjk[:8]:
                print("    %-58s %r" % (m["filename"][:58], m["text"][:40]))
        if no_text:
            print("\n  无文本条目（前缀分组统计）：")
            pref = collections.Counter(
                re.sub(r"\d+$", "#", m["filename"]) for m in no_text)
            for p, c in pref.most_common(8):
                print("    %4d  %s" % (c, p[:66]))

        problems = (dup_rows + len(short) + len(symbol_only) + len(cjk))
        total_problems += problems
        print("\n  => 该英雄需关注条目：%d" % problems)

    print("=" * 66)
    print("合计需关注条目：%d" % total_problems)
    if total_problems == 0:
        print("结论：语料质量良好，可直接进入阶段 3 清洗。")
    else:
        print("结论：先看上面的样例，判断是「重复/纯音效（可忽略）」"
              "还是「文本错配（必须修）」。")


if __name__ == "__main__":
    main()
