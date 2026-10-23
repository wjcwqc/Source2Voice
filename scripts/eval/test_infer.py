#!/usr/bin/env python3
"""Source2Voice · 阶段 6b：推理冒烟测试（验证音色是否学到）。

用法:
    # adapter 模式（免合并）
    python test_infer.py \
        --lora_adapter <exp>/omnivoice_paige_lora/checkpoint-600 \
        --ref_audio <ref.wav> --ref_text "参考音频对应台词" \
        --texts <eval_texts.json> --lang en

    # 合并模型模式（独立可用）
    python test_infer.py --model <exp>/omnivoice_paige_merged ...

测试文本是**留出**的 dev 文本（不在训练集里）。每条生成两次：
一次带该英雄参考音频（ref），一次不带（noref）——
noref 也能出对音色，说明音色已内化进模型参数。

--texts 是 JSON：{"t01": "第一句台词", ...}
--ref_audio / --ref_text 指定参考音频及其文本（ref 模式用）。
"""
import argparse
import json
import os
import sys

import soundfile as sf
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402

from omnivoice.models.omnivoice import OmniVoice  # noqa: E402
from omnivoice.utils.lora import load_lora_adapter  # noqa: E402

BASE_MODEL = s2v_config.MODEL

# OmniVoice generate() 接受的语言标识
LANG_MAP = {
    "en": "en", "english": "en",
    "zh": "zh", "schinese": "zh", "chinese": "zh",
    "ja": "ja", "ko": "ko", "fr": "fr", "de": "de", "es": "es",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=BASE_MODEL)
    ap.add_argument("--lora_adapter", default=None)
    ap.add_argument("--out_dir", default=os.path.join(s2v_config.OUT_DIR, "omnivoice_eval"))
    ap.add_argument("--num_step", type=int, default=32)
    ap.add_argument("--texts", required=True,
                    help="评估文本 JSON：{tid: text}")
    ap.add_argument("--lang", default="en", help="en / zh")
    ap.add_argument("--ref_audio", default=None, help="参考音频（ref 模式）")
    ap.add_argument("--ref_text", default="", help="参考音频对应文本")
    args = ap.parse_args()

    with open(args.texts, encoding="utf-8") as f:
        test_lines = json.load(f)
    if not test_lines:
        print("ERROR: 评估文本为空: %s" % args.texts, file=sys.stderr)
        raise SystemExit(2)

    lang = LANG_MAP.get(args.lang.lower(), args.lang)
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"loading {args.model} on {device} ...")
    model = OmniVoice.from_pretrained(args.model, device_map=device, dtype=torch.float16)
    if args.lora_adapter:
        print(f"applying adapter {args.lora_adapter}")
        model = load_lora_adapter(model, args.lora_adapter)

    for tid, text in test_lines.items():
        for mode, kwargs in [
            ("ref", dict(ref_audio=args.ref_audio, ref_text=args.ref_text)),
            ("noref", dict()),
        ]:
            if mode == "ref" and not args.ref_audio:
                continue
            out = os.path.join(out_dir, f"{tid}_{mode}.wav")
            print(f"[{tid}/{mode}] {text}")
            audios = model.generate(
                text=text,
                language=lang,
                num_step=args.num_step,
                **kwargs,
            )
            sf.write(out, audios[0], model.sampling_rate)
            print(f"  -> {out} ({len(audios[0])/model.sampling_rate:.1f}s)")

    print("ALL DONE ->", out_dir)


if __name__ == "__main__":
    main()
