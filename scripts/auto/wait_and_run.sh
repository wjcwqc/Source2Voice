#!/usr/bin/env bash
# Source2Voice · 守护脚本：等训练跑完后自动接续流水线
#
# 训练是长任务（4–6 h）。本脚本作为守护进程等 checkpoint 落盘，
# 然后把「合并 → 推理冒烟 → 量化评估 → 暂存 → 上传 → 下一位英雄 → …」
# 一路串下去，不用人工盯着。
#
# 用法
# ----
#     bash scripts/auto/wait_and_run.sh \
#         --ckpt   "$S2V_WORK/exp/omnivoice_<hero>_lora/checkpoint-600" \
#         --log    "$S2V_WORK/exp/<hero>_train.log" \
#         --pipe   ./scripts/auto/pipeline_example.sh
#
# 可选参数：
#     --stale <秒>     日志停更多久判定训练已死（默认 600）
#     --settle <秒>    checkpoint 出现后等多久再启动流水线（默认 60，等 GPU 释放）
#
# 存活性判定：不用 ps（Git Bash 下输出含二进制字符，grep 匹配不可靠），
# 改看**训练日志的 mtime** —— 训练每步都写日志，停更即视为已死。
set -uo pipefail

CKPT_DIR=""
TRAIN_LOG=""
PIPE=""
STALE_SEC=600
SETTLE_SEC=60

while [ $# -gt 0 ]; do
  case "$1" in
    --ckpt)   CKPT_DIR="$2"; shift 2 ;;
    --log)    TRAIN_LOG="$2"; shift 2 ;;
    --pipe)   PIPE="$2"; shift 2 ;;
    --stale)  STALE_SEC="$2"; shift 2 ;;
    --settle) SETTLE_SEC="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$CKPT_DIR" ] || [ -z "$TRAIN_LOG" ] || [ -z "$PIPE" ]; then
  echo "用法: bash wait_and_run.sh --ckpt <ckpt目录> --log <训练日志> --pipe <流水线脚本>" >&2
  exit 2
fi

LOG="$(dirname "$TRAIN_LOG")/wait_and_run.log"

exec >> "$LOG" 2>&1
echo "==== wait_and_run start $(date '+%F %T') ===="
echo "  ckpt : $CKPT_DIR"
echo "  log  : $TRAIN_LOG"
echo "  pipe : $PIPE"

WAITED=0
while [ ! -d "$CKPT_DIR" ]; do
  NOW=$(date +%s)
  if [ -f "$TRAIN_LOG" ]; then
    MT=$(stat -c %Y "$TRAIN_LOG" 2>/dev/null || echo 0)
    AGE=$((NOW - MT))
    if [ "$AGE" -gt "$STALE_SEC" ]; then
      echo "训练日志已停更 $((AGE / 60)) 分钟且 $CKPT_DIR 不存在 —— 训练失败"
      tail -n 40 "$TRAIN_LOG"
      exit 1
    fi
  fi
  if [ $((WAITED % 300)) -eq 0 ]; then
    STEP=$(tail -c 400 "$TRAIN_LOG" 2>/dev/null | tr '\r' '\n' | grep -oE "[0-9]+/[0-9]+" | tail -1)
    echo "$(date '+%T') 等待中... 当前 $STEP"
  fi
  WAITED=$((WAITED + 60))
  sleep 60
done

echo "$(date '+%T') checkpoint 就绪，等待 $SETTLE_SEC 秒让训练进程彻底收尾"
sleep "$SETTLE_SEC"

bash "$PIPE"

echo "==== wait_and_run done $(date '+%F %T') ===="
grep -E "^---- |^=== |MERGE_OK|real clips|ALL_UPLOADS_COMPLETE|SUMMARY" "$LOG" | tail -80
