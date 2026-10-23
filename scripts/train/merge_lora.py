#!/usr/bin/env python3
"""Export a standalone OmniVoice checkpoint from an FSDP/LoRA training checkpoint.

The training checkpoint (from accelerator.save_state with FULL_STATE_DICT)
contains the full model state dict: base weights + LoRA deltas + fully-trained
audio_embeddings/audio_heads, keyed under the PEFT "base_model.model." prefix.

This script merges LoRA deltas into the base weights and writes a self-contained
OmniVoice checkpoint (config + merged weights + tokenizer + audio tokenizer)
usable by omnivoice-infer / OmniVoice.from_pretrained.
"""
import argparse
import json
import os
import sys
import shutil

import torch
from safetensors.torch import load_file, save_file

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

BASE_MODEL = s2v_config.MODEL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True,
                    help="training checkpoint dir, e.g. exp/.../checkpoint-1200")
    ap.add_argument("--output", required=True, help="standalone output dir")
    ap.add_argument("--lora_alpha", type=float, default=32.0)
    ap.add_argument("--lora_r", type=int, default=16)
    args = ap.parse_args()

    ckpt = args.checkpoint
    sd_path = os.path.join(ckpt, "model.safetensors")
    if not os.path.exists(sd_path):
        sd_path = os.path.join(ckpt, "pytorch_model.bin")
    assert os.path.exists(sd_path), f"no model state in {ckpt}"

    if sd_path.endswith(".safetensors"):
        sd = load_file(sd_path)
    else:
        sd = torch.load(sd_path, map_location="cpu", weights_only=True)

    # strip PEFT prefix
    merged = {}
    for k, v in sd.items():
        nk = k
        if nk.startswith("base_model.model."):
            nk = nk[len("base_model.model."):]
        merged[nk] = v

    # collect lora pairs: xxx.lora_A.weight / xxx.lora_B.weight
    lora_pairs = {}
    for k in list(merged.keys()):
        if k.endswith(".lora_A.weight"):
            base_key = k[: -len(".lora_A.weight")]
            b_key = base_key + ".lora_B.weight"
            if b_key in merged:
                lora_pairs[base_key] = (merged.pop(k), merged.pop(b_key))

    scale = args.lora_alpha / args.lora_r
    n_merged = 0
    for base_key, (a, b) in lora_pairs.items():
        # PEFT: W += scale * B @ A   (a: [r, in], b: [out, r])
        w_key = base_key + ".weight"
        if w_key in merged:
            delta = (b.float() @ a.float()) * scale
            merged[w_key] = (merged[w_key].float() + delta).to(merged[w_key].dtype)
            n_merged += 1
        else:
            print(f"WARN: no base weight for {w_key}, skipping")

    print(f"merged {n_merged} LoRA targets into base weights")

    os.makedirs(args.output, exist_ok=True)
    # copy config + tokenizer + audio tokenizer from base model
    for name in ["config.json", "tokenizer.json", "tokenizer_config.json",
                 "chat_template.jinja", "generation_config.json"]:
        src = os.path.join(BASE_MODEL, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(args.output, name))
    tok_src = os.path.join(BASE_MODEL, "audio_tokenizer")
    if os.path.isdir(tok_src):
        dst = os.path.join(args.output, "audio_tokenizer")
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(tok_src, dst)

    save_file(merged, os.path.join(args.output, "model.safetensors"),
              metadata={"format": "pt"})
    print(f"standalone checkpoint written to {args.output}")


if __name__ == "__main__":
    main()
