#!/usr/bin/env python3
"""Source2Voice · 阶段 4a：把清洗后的 .list 清单转成 OmniVoice 训练用 JSONL。

输入（GPT-SoVITS 风格 .list，每行）:
    <audio_path>|<speaker>|<lang>|<text>

输出（每行一个 JSON）:
    {"id": ..., "audio_path": ..., "text": ..., "language_id": "zh"}

划分是**确定性**的（固定 seed 洗牌后取前 N 条做 dev），
因此重跑一定得到同样的划分，评估结果可复现。

用法
----
    python prep_omnivoice_data.py --list <path.list> --out_dir <data_dir> --dev_count 20
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402

DEFAULT_LIST = os.path.join(s2v_config.META_DIR, "schinese_dark_willow_vo_pure.list")
DEFAULT_OUT = os.path.join(s2v_config.DATA_DIR, "omnivoice_dark_willow")
SEED = 42

# OmniVoice 的 language_id 只认 LANG_IDS（"en" / "zh" / "ja" ...）。
# 清单里可能出现各种写法，统一归一。
LANG_ALIASES = {
    "english": "en",
    "en-us": "en",
    "en_us": "en",
    "schinese": "zh",
    "chinese": "zh",
    "cn": "zh",
    "zh-cn": "zh",
    "zh_cn": "zh",
    "japanese": "ja",
    "korean": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "russian": "ru",
    "portuguese": "pt",
    "italian": "it",
}


def normalize_lang(raw: str) -> str:
    """把清单里的语言写法归一成 OmniVoice 的 language_id。"""
    v = (raw or "").strip().lower().replace("_", "-")
    if not v:
        return "en"
    if v in LANG_ALIASES:
        return LANG_ALIASES[v]
    if v.startswith("zh"):
        return "zh"
    if v.startswith("en"):
        return "en"
    return v


def load_entries(list_path: str) -> list:
    entries = []
    with open(list_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            audio_path, speaker, lang, text = parts[0], parts[1], parts[2], "|".join(parts[3:])
            if not os.path.exists(audio_path.strip()):
                print("WARN: 音频不存在，跳过: %s" % audio_path)
                continue
            sid = os.path.splitext(os.path.basename(audio_path))[0]
            entries.append({
                "id": sid,
                "audio_path": os.path.abspath(audio_path.strip()).replace("\\", "/"),
                "text": text.strip(),
                "language_id": normalize_lang(lang),
            })
    return entries


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段4a 生成 OmniVoice JSONL")
    ap.add_argument("--list", default=DEFAULT_LIST, help="输入 .list 清单")
    ap.add_argument("--out_dir", default=DEFAULT_OUT)
    ap.add_argument("--dev_count", type=int, default=20)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    entries = load_entries(a.list)
    if not entries:
        print("ERROR: 清单为空或音频路径全部失效", file=sys.stderr)
        raise SystemExit(2)

    rng = random.Random(a.seed)
    order = list(range(len(entries)))
    rng.shuffle(order)
    dev_idx = set(order[:a.dev_count])

    train_lines, dev_lines = [], []
    for i, e in enumerate(entries):
        (dev_lines if i in dev_idx else train_lines).append(json.dumps(e, ensure_ascii=False))

    out_train = os.path.join(a.out_dir, "train.jsonl")
    out_dev = os.path.join(a.out_dir, "dev.jsonl")
    with open(out_train, "w", encoding="utf-8") as f:
        f.write("\n".join(train_lines) + "\n")
    with open(out_dev, "w", encoding="utf-8") as f:
        f.write("\n".join(dev_lines) + "\n")

    print("total=%d train=%d dev=%d" % (len(entries), len(train_lines), len(dev_lines)))
    print("train ->", out_train)
    print("dev   ->", out_dev)


if __name__ == "__main__":
    main()
