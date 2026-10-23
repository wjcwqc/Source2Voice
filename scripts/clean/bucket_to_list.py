#!/usr/bin/env python3
"""Source2Voice · 把 Kaldi 桶（wav.scp + text）转成 GPT-SoVITS 风格 .list。

    wav|utt path
    text|utt transcript

->  wav_path|speaker|lang|text

用途：refine_dataset.py 产出的 core/style/review 桶是 Kaldi 格式，
训练侧（prep_omnivoice_data.py）需要 .list，用本脚本桥接。

用法
----
    python bucket_to_list.py --bucket <clean_dir>/core --out <list> \
        --speaker paige --lang en
"""
import argparse
import os
import sys


def read_kv(path):
    """读 Kaldi 的 `key value` 两列文件。"""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                out[parts[0]] = parts[1].strip()
    return out


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · Kaldi 桶 -> .list")
    ap.add_argument("--bucket", required=True, help="桶目录（含 wav.scp / text）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--speaker", default="speaker")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()

    wavs = read_kv(os.path.join(a.bucket, "wav.scp"))
    texts = read_kv(os.path.join(a.bucket, "text"))
    if not wavs:
        sys.exit("找不到 %s" % os.path.join(a.bucket, "wav.scp"))

    n = 0
    skipped = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for utt in sorted(wavs):
            wav = wavs[utt]
            text = texts.get(utt, "").strip()
            if not text or not os.path.exists(wav):
                skipped += 1
                continue
            f.write("%s|%s|%s|%s\n" % (wav.replace("\\", "/"), a.speaker, a.lang, text))
            n += 1
    print("wrote %s (%d lines, skipped %d)" % (a.out, n, skipped))


if __name__ == "__main__":
    main()
