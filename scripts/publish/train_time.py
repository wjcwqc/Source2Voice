#!/usr/bin/env python3
"""Source2Voice · 阶段 6c：实测训练耗时（给报告与模型卡填数字用）。

为什么不用手写数字
------------------
「600 步总耗时约 X」这种数字最容易过期：换机器、换 batch、改
`OMNIVOICE_CPU_OFFLOAD` 都会变。报告里的数字必须能被别人复现，
所以这里**从训练产物里算**，而不是抄一个估计值。

怎么算
------
* 起点：`train.log` 里 `Starting Training Loop` 那一行的时间戳
  （拿不到就退回首行时间戳）；
* 终点：`checkpoint-<steps>` 目录的 mtime，与 `train.log` 末行时间戳
  取较晚者——checkpoint 是训练末尾落盘的，train.log 末行是最后一个
  epoch 的开始，两者取 max 能覆盖「最后一个 epoch 跑完才保存」的时序。

单步耗时 = 总耗时 / 总步数。

用法
----
    python train_time.py --exp_dir D:/dwvits/exp/omnivoice_deadlock_paige_lora \
        --steps 600 --target card

    # 输出示例
    # 约 5 h 12 min（600 步 × 约 31 s/步，RTX 3050 Ti 4 GB）

`--target` 四种取值：
    duration  纯时长            -> 5 h 12 min
    report    报告里的总耗时写法  -> 5 h 12 min（约 31 s/步）
    per_step  报告里的单步耗时    -> 约 31 s
    card      模型卡里的写法      -> 约 5 h 12 min（600 步 × 约 31 s/步，RTX 3050 Ti 4 GB）
"""
import argparse
import os
import re
import sys
import time

# train.log 行首时间戳：10/24/2026 05:20:02 - INFO - ...
TS_RE = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})")
LOOP_MARK = "Starting Training Loop"


def parse_ts(line):
    """把 'MM/DD/YYYY HH:MM:SS' 解析成本地时间 epoch 秒；解析不了返回 None。"""
    m = TS_RE.match(line.strip())
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), "%m/%d/%Y %H:%M:%S"))
    except ValueError:
        return None


def find_start(path):
    """训练起点：优先 'Starting Training Loop' 那行，否则首行时间戳。"""
    first = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = parse_ts(line)
            if ts is None:
                continue
            if first is None:
                first = ts
            if LOOP_MARK in line:
                return ts
    return first


def find_last(path):
    """train.log 末行时间戳。"""
    last = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = parse_ts(line)
            if ts is not None:
                last = ts
    return last


def fmt_hm(seconds):
    """秒 -> '5 h 12 min' / '48 min' / '12 s'。"""
    seconds = int(round(seconds))
    if seconds < 60:
        return "%d s" % seconds
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return "%d h %d min" % (h, m) if m else "%d h" % h
    return "%d min" % m


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 实测训练耗时")
    ap.add_argument("--exp_dir", required=True, help="LoRA 实验目录（含 train.log 与 checkpoint-*）")
    ap.add_argument("--steps", type=int, default=600, help="总步数（用于算单步耗时）")
    ap.add_argument("--target", default="duration", choices=["duration", "report", "per_step", "card"],
                    help="输出格式")
    ap.add_argument("--gpu", default="RTX 3050 Ti 4 GB", help="显卡描述（写进 card 格式）")
    a = ap.parse_args()

    train_log = os.path.join(a.exp_dir, "train.log")
    if not os.path.exists(train_log):
        print("ERROR: 训练日志不存在: %s" % train_log, file=sys.stderr)
        raise SystemExit(2)

    start = find_start(train_log)
    if start is None:
        print("ERROR: 日志里没有可解析的时间戳: %s" % train_log, file=sys.stderr)
        raise SystemExit(2)

    end = find_last(train_log) or start
    ckpt = os.path.join(a.exp_dir, "checkpoint-%d" % a.steps)
    if os.path.isdir(ckpt):
        end = max(end, os.path.getmtime(ckpt))

    total = max(0, end - start)
    hm = fmt_hm(total)
    per_step = total / float(a.steps) if a.steps else 0.0
    per_step_txt = "约 %d s/步" % round(per_step)

    if a.target == "duration":
        print(hm)
    elif a.target == "report":
        print("%s（%s）" % (hm, per_step_txt))
    elif a.target == "per_step":
        print(per_step_txt)
    else:
        print("约 %s（%d 步 × %s，%s）"
              % (hm, a.steps, per_step_txt, a.gpu))


if __name__ == "__main__":
    main()
