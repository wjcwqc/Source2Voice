#!/usr/bin/env python3
"""Source2Voice · 阶段 6b：推理冒烟测试（验证音色是否学到）。

用法:
    # adapter 模式（免合并）
    python test_infer.py --lora_adapter <exp>/omnivoice_dark_willow_lora/checkpoint-600
    # 合并模型模式（独立可用）
    python test_infer.py --model <exp>/omnivoice_dark_willow_merged

测试文本是**留出**的 dev 文本（不在训练集里）。每条生成两次：
一次带该英雄参考音频（ref），一次不带（noref）——
noref 也能出对音色，说明音色已内化进模型参数。
"""
import argparse
import os
import sys

import soundfile as sf
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402

from omnivoice.models.omnivoice import OmniVoice  # noqa: E402
from omnivoice.utils.lora import load_lora_adapter  # noqa: E402

OUT_DIR = os.path.join(s2v_config.OUT_DIR, "omnivoice_dark_willow")
BASE_MODEL = s2v_config.MODEL

# held-out dev lines
TEST_LINES = [
    ("t01", "我想你在哪儿,你就在哪儿。"),
    ("t02", "天,我爱死钱了!"),
    ("t03", "跟我计划的不太一样"),
    ("t04", "相信自然的力量,它总会找到出路。"),  # generic line, unseen style
]
# reference clip from dev set (held out from training)
REF_AUDIO = os.path.join(
    s2v_config.DATASET_DIR, "schinese", "dark_willow", "vo", "sylph_bounty_02.wav"
)
REF_TEXT = "天,我爱死钱了!"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=BASE_MODEL)
    ap.add_argument("--lora_adapter", default=None)
    ap.add_argument("--out_dir", default=OUT_DIR)
    ap.add_argument("--num_step", type=int, default=32)
    ap.add_argument("--ref_audio", default=REF_AUDIO, help="参考音频（ref 模式）")
    ap.add_argument("--ref_text", default=REF_TEXT, help="参考音频对应文本")
    args = ap.parse_args()

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    device = "cuda:0"
    print(f"loading {args.model} ...")
    model = OmniVoice.from_pretrained(args.model, device_map=device, dtype=torch.float16)
    if args.lora_adapter:
        print(f"applying adapter {args.lora_adapter}")
        model = load_lora_adapter(model, args.lora_adapter)

    for tid, text in TEST_LINES:
        for mode, kwargs in [
            ("ref", dict(ref_audio=REF_AUDIO, ref_text=REF_TEXT)),
            ("noref", dict()),
        ]:
            out = os.path.join(out_dir, f"{tid}_{mode}.wav")
            print(f"[{tid}/{mode}] {text}")
            audios = model.generate(
                text=text,
                language="zh",
                num_step=args.num_step,
                **kwargs,
            )
            sf.write(out, audios[0], model.sampling_rate)
            print(f"  -> {out} ({len(audios[0])/model.sampling_rate:.1f}s)")

    print("ALL DONE ->", out_dir)


if __name__ == "__main__":
    main()
