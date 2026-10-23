#!/usr/bin/env python3
"""Source2Voice · 阶段 7a：整理 HuggingFace 上传暂存目录。

产出两个目录：
    <stage>/model/      模型仓库内容（merged + lora + training + README）
    <stage>/dataset/    数据集仓库内容（audio + metadata + README）

用法
----
    python stage_hf.py --hero paige \
        --merged   "$WORK/exp/omnivoice_deadlock_paige_merged" \
        --lora     "$WORK/exp/omnivoice_deadlock_paige_lora/checkpoint-600" \
        --trainlog "$WORK/exp/omnivoice_deadlock_paige_lora/train.log" \
        --dataset_root "$WORK/data/omnivoice_deadlock_paige" \
        --audio_root "D:/dwvits/data/deadlock_paige_core/core" \
        --stage    "$WORK/stage/paige" \
        --model_card   examples/deadlock_paige/HF_MODEL_CARD.md \
        --dataset_card examples/deadlock_paige/HF_DATASET_CARD.md
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402


def copytree(src, dst, skip_dirs=(), skip_exts=()):
    """复制目录，跳过指定子目录与扩展名。"""
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = os.path.relpath(root, src)
        out = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out, exist_ok=True)
        for f in files:
            if os.path.splitext(f)[1].lower() in skip_exts:
                continue
            s = os.path.join(root, f)
            d = os.path.join(out, f)
            shutil.copy2(s, d)
            n += 1
    return n


def human_size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段7a 暂存目录")
    ap.add_argument("--hero", required=True)
    ap.add_argument("--merged", default=None, help="合并模型目录")
    ap.add_argument("--lora", default=None, help="LoRA adapter 目录")
    ap.add_argument("--trainlog", default=None, help="训练日志")
    ap.add_argument("--train_config", default=None, help="训练配置 JSON")
    ap.add_argument("--dataset_root", default=None,
                    help="OmniVoice 训练数据目录（含 train.jsonl/dev.jsonl/data_config.json）")
    ap.add_argument("--audio_root", default=None,
                    help="清洗后的音频根目录（含 wavs/ 与 .list）")
    ap.add_argument("--stage", required=True, help="暂存根目录")
    ap.add_argument("--model_card", default=None, help="模型卡 Markdown")
    ap.add_argument("--dataset_card", default=None, help="数据集卡 Markdown")
    ap.add_argument("--clean", action="store_true", help="清空暂存目录后重建")
    a = ap.parse_args()

    stage = os.path.abspath(a.stage)
    mdir = os.path.join(stage, "model")
    ddir = os.path.join(stage, "dataset")
    if a.clean and os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(mdir, exist_ok=True)
    os.makedirs(ddir, exist_ok=True)

    # ---------------- 模型仓库 ----------------
    if a.merged:
        dst = os.path.join(mdir, "merged")
        n = copytree(a.merged, dst, skip_dirs=("__pycache__", ".git"))
        print("model/merged       : %d files" % n)
    if a.lora:
        dst = os.path.join(mdir, "lora")
        n = copytree(a.lora, dst, skip_dirs=("__pycache__",))
        print("model/lora         : %d files" % n)
    training = os.path.join(mdir, "training")
    os.makedirs(training, exist_ok=True)
    if a.trainlog and os.path.exists(a.trainlog):
        shutil.copy2(a.trainlog, os.path.join(training, "train.log"))
        print("model/training     : train.log")
    if a.train_config and os.path.exists(a.train_config):
        shutil.copy2(a.train_config, os.path.join(training, "train_config.json"))
        print("model/training     : train_config.json")
    if a.dataset_root and os.path.exists(os.path.join(a.dataset_root, "data_config.json")):
        shutil.copy2(os.path.join(a.dataset_root, "data_config.json"),
                     os.path.join(training, "data_config.json"))

    # ---------------- 数据集仓库 ----------------
    if a.audio_root:
        dst = os.path.join(ddir, "audio")
        n = copytree(a.audio_root, dst)
        print("dataset/audio      : %d files" % n)
    md = os.path.join(ddir, "metadata")
    os.makedirs(md, exist_ok=True)
    if a.dataset_root:
        for f in ("train.jsonl", "dev.jsonl"):
            p = os.path.join(a.dataset_root, f)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(md, f))
        for f in os.listdir(a.dataset_root):
            if f.endswith(".list"):
                shutil.copy2(os.path.join(a.dataset_root, f), os.path.join(md, f))
    if a.audio_root:
        for f in os.listdir(a.audio_root):
            if f.endswith(".list"):
                shutil.copy2(os.path.join(a.audio_root, f), os.path.join(md, f))

    # ---------------- 模型卡 ----------------
    for card, target in ((a.model_card, os.path.join(mdir, "README.md")),
                         (a.dataset_card, os.path.join(ddir, "README.md"))):
        if card and os.path.exists(card):
            shutil.copy2(card, target)
            print("card               : %s" % os.path.basename(target))

    # ---------------- 摘要 ----------------
    summary = {
        "hero": a.hero,
        "model_dir": mdir,
        "dataset_dir": ddir,
        "model_size_mb": round(human_size(mdir) / 1e6, 1),
        "dataset_size_mb": round(human_size(ddir) / 1e6, 1),
    }
    with open(os.path.join(stage, "stage_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
