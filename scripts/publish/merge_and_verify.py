#!/usr/bin/env python3
"""Source2Voice · 阶段 6c：合并 LoRA 并验证合并结果。

用法
----
    python merge_and_verify.py --hero paige \
        --base_model  D:/dwvits/models/omnivoice \
        --adapter     D:/dwvits/exp/omnivoice_deadlock_paige_lora/checkpoint-600 \
        --output      D:/dwvits/exp/omnivoice_deadlock_paige_merged
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402


def dir_size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 合并 LoRA")
    ap.add_argument("--hero", required=True)
    ap.add_argument("--base_model", default=s2v_config.MODEL)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--python", default=s2v_config.PYTHON)
    a = ap.parse_args()

    if not os.path.isdir(a.adapter):
        print("ERROR: adapter 目录不存在: %s" % a.adapter, file=sys.stderr)
        raise SystemExit(2)

    os.makedirs(a.output, exist_ok=True)
    print("=== merge_lora ===")
    print("  base   :", a.base_model)
    print("  adapter:", a.adapter)
    print("  output :", a.output)

    # 优先用官方 CLI（PEFT 键名带 .default，手写脚本极易漏）
    cmd = [
        a.python, "-m", "omnivoice.cli.merge_lora",
        "--base_model", a.base_model,
        "--adapter", a.adapter,
        "--output", a.output,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = s2v_config.REPO + os.pathsep + env.get("PYTHONPATH", "")
    env["HF_HUB_OFFLINE"] = "1"
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        print("官方 merge_lora 失败，回退到 scripts/train/merge_lora.py", file=sys.stderr)
        fallback = [
            a.python, os.path.join(HERE, "..", "train", "merge_lora.py"),
            "--checkpoint", a.adapter,
            "--output", a.output,
        ]
        r = subprocess.run(fallback, env=env)
        if r.returncode != 0:
            raise SystemExit("合并失败")

    # 校验产物
    print("\n=== 校验 ===")
    need = ["config.json"]
    ok = True
    for f in need:
        p = os.path.join(a.output, f)
        exists = os.path.exists(p)
        print("  %-28s %s" % (f, "OK" if exists else "缺失"))
        ok = ok and exists
    st = [f for f in os.listdir(a.output) if f.endswith(".safetensors")]
    print("  safetensors: %s" % (", ".join(st) if st else "缺失"))
    if st:
        total = sum(os.path.getsize(os.path.join(a.output, f)) for f in st)
        print("  权重总大小: %.2f GB" % (total / 1e9))
    print("  目录总大小: %.2f GB" % (dir_size(a.output) / 1e9))
    # tokenizer / audio_tokenizer 是否被带出来
    for sub in ("audio_tokenizer", "tokenizer"):
        p = os.path.join(a.output, sub)
        print("  %-28s %s" % (sub + "/", "OK" if os.path.isdir(p) else "缺失"))
    if not ok:
        raise SystemExit("合并产物不完整")
    print("\nMERGE_OK ->", a.output)


if __name__ == "__main__":
    main()
