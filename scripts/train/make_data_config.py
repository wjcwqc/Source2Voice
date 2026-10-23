#!/usr/bin/env python3
"""Source2Voice · 阶段 4b：生成 OmniVoice 的 data_config.json。

**关键坑（务必照抄）**：data.lst 里的 tar 路径必须写成 `file:///D:/...`，
webdataset 的 gopen 不认 Windows 盘符路径（`D:/...` 会被当成相对路径或 URL 失败）。

本脚本做两件事：
1. 调用 tokenize_single.py 把 train/dev JSONL 转成 WebDataset shards（audios/*.tar + txts/*.jsonl）
2. 生成 data_config.json，指向产出的 data.lst

用法
----
    python make_data_config.py \
        --data_dir  <work>/data/omnivoice_dark_willow \
        --out       <work>/data/omnivoice_dark_willow/data_config.json
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402


def to_file_url(path: str) -> str:
    """Windows 路径 -> file:/// URL（webdataset gopen 要求）。"""
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + p


def normalize_data_lst(path: str) -> int:
    """把 data.lst 里的 tar 路径规范成 file:/// URL，jsonl 路径保持普通路径。

    webdataset gopen 读 tar 时把 "D:/xxx" 当 URL scheme 解析会失败；
    omnivoice 的 LabelDataset 用 open()/os.path.exists() 读 jsonl，
    必须保持普通文件系统路径。两种路径形式不能互换。

    返回被修正的行数。
    """
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    fixed = 0
    out = []
    for ln in lines:
        parts = ln.split()
        if len(parts) != 4:
            out.append(ln)
            continue
        tar, jl, c, d = parts
        if tar.startswith("file://"):
            new_tar = tar
        elif re.match(r"^[A-Za-z]:[\\/]", tar) or tar.startswith("/"):
            new_tar = to_file_url(tar)
        else:
            new_tar = tar
        if new_tar != tar:
            fixed += 1
        out.append(f"{new_tar} {jl} {c} {d}")
    if fixed:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    return fixed


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段4b tokenize + 生成 data_config")
    ap.add_argument("--data_dir", default=os.path.join(s2v_config.DATA_DIR, "omnivoice_dark_willow"))
    ap.add_argument("--out", default=None, help="输出的 data_config.json 路径")
    ap.add_argument("--tokenizer", default=os.path.join(s2v_config.MODEL, "audio_tokenizer"))
    ap.add_argument("--samples_per_shard", type=int, default=100)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--skip_tokenize", action="store_true", help="已有 shards 时跳过 tokenize")
    a = ap.parse_args()

    data_dir = os.path.abspath(a.data_dir)
    out = a.out or os.path.join(data_dir, "data_config.json")
    python = s2v_config.PYTHON

    for split in ("train", "dev"):
        jsonl = os.path.join(data_dir, "%s.jsonl" % split)
        tokens = os.path.join(data_dir, "tokens", split)
        lst = os.path.join(tokens, "data.lst")
        if not a.skip_tokenize:
            if not os.path.exists(jsonl):
                print("ERROR: 缺少 %s（先跑 prep_omnivoice_data.py）" % jsonl, file=sys.stderr)
                raise SystemExit(2)
            print("=== tokenize %s ===" % split)
            subprocess.run([
                python, os.path.join(HERE, "tokenize_single.py"),
                "--input_jsonl", jsonl,
                "--out_dir", tokens,
                "--tokenizer_path", a.tokenizer,
                "--samples_per_shard", str(a.samples_per_shard),
                "--device", a.device,
            ], check=True)
        if not os.path.exists(lst):
            print("ERROR: 缺少 %s（tokenize 未产出 data.lst）" % lst, file=sys.stderr)
            raise SystemExit(2)
        n_fixed = normalize_data_lst(lst)
        if n_fixed:
            print("  已修正 %d 行 tar 路径 -> file:/// URL" % n_fixed)

    # 注意：manifest_path 必须是**普通文件系统路径**。
    # omnivoice/data/dataset.py:143 用 os.path.isfile() 校验它，
    # 写成 file:///D:/... 会直接抛 AssertionError "<path> is not a file."。
    # file:/// 前缀只出现在 data.lst **内部**的 tar 路径上（webdataset gopen 需要）。
    cfg = {
        "train": [{"manifest_path": [os.path.join(data_dir, "tokens", "train", "data.lst")]}],
        "dev": [{"manifest_path": [os.path.join(data_dir, "tokens", "dev", "data.lst")]}],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print("data_config ->", out)
    print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
