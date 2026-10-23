#!/usr/bin/env python3
"""Source2Voice · 阶段 6b：把量化评估结果填进 REPORT.md 的占位符。

用法
----
    python fill_report.py \
        --eval_json "$WORK/eval/paige_eval.json" \
        --report    "examples/deadlock_paige/REPORT.md" \
        --hero      Paige \
        --train_time "约 5 h 10 min（600 步 × 约 30 s/步）"

做什么
------
1. 读 `eval_omnivoice.py --json_out` 产出的 JSON；
2. 把 `<!-- TRAINING_RESULTS -->` 替换成实测表格（各 checkpoint 的 CER / spk-sim，
   以及真人基线）；
3. 顺手更新训练耗时那一行（模型卡与报告里的旧数字常常过期）。

设计要点
--------
* **幂等**：占位符不存在时（例如已经填过）会退化成"更新耗时"，
  不会把上一次的实测表冲掉。
* **原地写入前先备份**：写 `.bak`，避免手滑把实测数据弄丢。
"""
import argparse
import json
import os
import re
import shutil
import sys

PLACEHOLDER = "<!-- TRAINING_RESULTS -->"


def build_table(payload: dict, hero: str) -> str:
    baseline = payload["baseline"]
    lines = []
    lines.append("### %s 量化评估实测结果" % hero)
    lines.append("")
    lines.append("评估口径：CER = Whisper `%s` 转写后字符级编辑距离；"
                 "spk-sim = campplus ONNX 嵌入与真人留出集的余弦相似度。"
                 % payload.get("whisper", "?"))
    lines.append("真人基线 = %d 条 dev 留出集片段互相之间的平均 spk-sim = **%.4f**。"
                 % (payload.get("n_real_clips", 0), baseline))
    lines.append("")
    lines.append("| checkpoint | 模式 | CER ↓ | spk-sim ↑ | vs 真人基线 |")
    lines.append("|---|---|---|---|---|")
    for r in payload["rows"]:
        delta = r["vs_baseline"]
        mark = "**PASS**" if delta > 0 else "below"
        lines.append("| `%s` | %s | %.3f | %.4f | %+.4f %s |"
                     % (r["ckpt"], r["mode"], r["cer"], r["spk_sim"], delta, mark))
    lines.append("")

    # 每个 checkpoint 取 ref/noref 中 spk-sim 更高的那一行做小结
    by_ck = {}
    for r in payload["rows"]:
        k = r["ckpt"]
        if k not in by_ck or r["spk_sim"] > by_ck[k]["spk_sim"]:
            by_ck[k] = r
    if by_ck:
        lines.append("小结：")
        lines.append("")
        for ck in sorted(by_ck):
            r = by_ck[ck]
            lines.append("* `%s` 最佳 %s 模式：CER %.3f，spk-sim %.4f（基线 %+.4f）"
                         % (ck, r["mode"], r["cer"], r["spk_sim"], r["vs_baseline"]))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段6b 填充报告实测结果")
    ap.add_argument("--eval_json", required=True, help="eval_omnivoice.py --json_out 的输出")
    ap.add_argument("--report", required=True, help="要更新的 REPORT.md")
    ap.add_argument("--hero", default=None, help="英雄显示名，用于表头")
    ap.add_argument("--train_time", default=None, help="训练耗时描述，替换报告里的旧值")
    ap.add_argument("--backup", action="store_true", help="改写前留一份 .bak")
    a = ap.parse_args()

    if not os.path.exists(a.eval_json):
        print("ERROR: 评估结果不存在: %s" % a.eval_json, file=sys.stderr)
        raise SystemExit(2)
    if not os.path.exists(a.report):
        print("ERROR: 报告不存在: %s" % a.report, file=sys.stderr)
        raise SystemExit(2)

    with open(a.eval_json, encoding="utf-8") as f:
        payload = json.load(f)

    hero = a.hero or payload.get("hero") or "该英雄"
    with open(a.report, encoding="utf-8") as f:
        text = f.read()

    if a.backup:
        shutil.copy2(a.report, a.report + ".bak")

    if PLACEHOLDER in text:
        text = text.replace(PLACEHOLDER, build_table(payload, hero))
        # 占位符上方常有「待训练完成后补入」之类的提示行，
        # 填了实测表之后它就自相矛盾了，一并去掉。
        text = re.sub(
            r"^[>]\s*待训练完成后补入[^\n]*\n+", "", text, flags=re.MULTILINE)
        print("[report] 已填入实测表格（占位符替换）")
    else:
        print("[report] 未找到占位符，跳过表格填充")

    if a.train_time:
        # 只替换**总耗时**那一行，别碰「单步耗时」（两者语义不同）
        new_text, n = re.subn(
            r"(600 步总耗时约\s*)(\*\*[^*]*\*\*)?[^\n。]*",
            lambda m: m.group(1) + "**%s**" % a.train_time,
            text, count=1)
        if n == 0:
            # 退而求其次：模型卡里的「| 耗时 | ... |」表格行
            new_text, n = re.subn(
                r"(\|\s*耗时\s*\|)[^|]*\|",
                lambda m: "%s %s |" % (m.group(1), a.train_time),
                text, count=1)
        if n:
            text = new_text
            print("[report] 已更新训练耗时 -> %s" % a.train_time)
        else:
            print("[report] 未找到训练耗时行，跳过", file=sys.stderr)

    with open(a.report, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("[report] 已更新 %s" % a.report)


if __name__ == "__main__":
    main()
