#!/usr/bin/env python3
"""Single-process audio tokenizer for OmniVoice fine-tuning data.

Equivalent to omnivoice.scripts.extract_audio_tokens but runs in one process
(no DataLoader workers / ProcessPool), avoiding sandbox restrictions on
spawned subprocesses.

Output per split:
    <out>/audios/shard-%06d.tar   (npy: int16 [8, T] audio tokens)
    <out>/txts/shard-%06d.jsonl   (metadata: id, text, language_id, ...)
    <out>/data.lst                ("<tar> <jsonl> <count> <duration>" per shard)
"""
import argparse
import io
import json
import os

import numpy as np
import soundfile as sf
import torch
import webdataset as wds
from transformers import AutoFeatureExtractor, HiggsAudioV2TokenizerModel

SR = 24_000


def load_audio(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    data = data.T  # (C, T)
    if data.shape[0] > 1:
        data = data.mean(axis=0, keepdims=True)
    if sr != SR:
        data = torchaudio.functional.resample(
            torch.from_numpy(data), orig_freq=sr, new_freq=SR
        ).numpy()
    # same normalization as JsonlDatasetReader
    data = (data / (np.abs(data).max() + 1e-7)) * 0.9
    return data


import torchaudio  # noqa: E402


def to_file_url(path: str) -> str:
    """Windows 路径 -> file:/// URL（webdataset gopen 要求）。

    webdataset 的 gopen 把 "D:/xxx" 当成 URL scheme 去解析，会失败；
    必须写成 "file:///D:/xxx"。
    """
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input_jsonl", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--tokenizer_path", required=True)
    ap.add_argument("--samples_per_shard", type=int, default=100)
    ap.add_argument("--device", default="cuda:0")
    args = ap.parse_args()

    os.makedirs(os.path.join(args.out_dir, "audios"), exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "txts"), exist_ok=True)
    # webdataset gopen cannot handle Windows drive-letter paths ("D:/..." is
    # parsed as a URL scheme); run from inside out_dir and use relative paths.
    os.chdir(args.out_dir)

    fe = AutoFeatureExtractor.from_pretrained(args.tokenizer_path)
    tok = HiggsAudioV2TokenizerModel.from_pretrained(
        args.tokenizer_path, device_map=args.device
    )
    tok.eval()

    entries = []
    with open(args.input_jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    print(f"{len(entries)} samples from {args.input_jsonl}")

    tar_writer = None
    jsonl_file = None
    shard_idx = 0
    shard_count = 0
    shard_dur = 0.0
    manifest = []
    n_ok = 0

    def open_shard():
        nonlocal tar_writer, jsonl_file, shard_idx, shard_count, shard_dur
        if tar_writer is not None:
            tar_writer.close()
        if jsonl_file is not None:
            jsonl_file.close()
        if shard_idx > 0 and shard_count > 0:
            # tar 走 webdataset gopen -> 需要 file:/// URL
            # jsonl 走 LabelDataset 的 open()/os.path.exists() -> 必须普通路径
            manifest.append((
                to_file_url(f"audios/shard-{shard_idx-1:06d}.tar"),
                os.path.abspath(f"txts/shard-{shard_idx-1:06d}.jsonl"),
                shard_count, shard_dur,
            ))
        tar_writer = wds.TarWriter(f"audios/shard-{shard_idx:06d}.tar")
        jsonl_file = open(f"txts/shard-{shard_idx:06d}.jsonl", "w", encoding="utf-8")
        shard_idx += 1
        shard_count = 0
        shard_dur = 0.0

    open_shard()
    for i, e in enumerate(entries):
        try:
            audio = load_audio(e["audio_path"])  # (1, T) @24k
            duration = audio.shape[1] / SR
            with torch.inference_mode():
                inputs = fe(raw_audio=audio.squeeze(0), sampling_rate=SR, return_tensors="pt").to(args.device)
                codes = tok.encode(inputs["input_values"]).audio_codes.squeeze(0)  # (8, T)
            assert codes.shape[0] == 8, f"bad codebook dim {codes.shape}"
            n_tok = codes.shape[1]
            buf = io.BytesIO()
            np.save(buf, codes.to(torch.int16).cpu().numpy())
            tar_writer.write({"__key__": e["id"], "npy": buf.getvalue()})
            meta = dict(e)
            meta["num_tokens"] = n_tok
            meta["audio_duration"] = duration
            jsonl_file.write(json.dumps(meta, ensure_ascii=False) + "\n")
            shard_count += 1
            shard_dur += duration
            n_ok += 1
            if shard_count >= args.samples_per_shard:
                open_shard()
        except Exception as ex:
            print(f"FAIL {e['id']}: {ex}")
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(entries)} done, ok={n_ok}")

    tar_writer.close()
    jsonl_file.close()
    if shard_count > 0:
        manifest.append((
            to_file_url(f"audios/shard-{shard_idx-1:06d}.tar"),
            os.path.abspath(f"txts/shard-{shard_idx-1:06d}.jsonl"),
            shard_count, shard_dur,
        ))
    with open("data.lst", "w", encoding="utf-8") as mf:
        for tar, jl, c, d in manifest:
            mf.write(f"{tar} {jl} {c} {d:.3f}\n")
    print(f"DONE ok={n_ok} shards={len(manifest)} -> {os.path.join(args.out_dir, 'data.lst')}")


if __name__ == "__main__":
    main()
