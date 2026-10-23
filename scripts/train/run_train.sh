#!/bin/bash
# Source2Voice · 阶段 5：LoRA 微调 OmniVoice
#
# 本项目验证过的配置（RTX 3050 Ti Laptop 4GB + Windows，无 NCCL）：
#   - 冻结的 fp32 基座权重常驻系统内存，逐 decoder 层流转到 GPU
#     （OMNIVOICE_CPU_OFFLOAD=1）=> 「内存当显存」
#   - LoRA adapter + audio_embeddings/audio_heads 常驻 GPU（bf16 autocast）
#   - 单进程，不需要 NCCL / FSDP
#
# 用法:
#   ./run_train.sh [train_config.json] [data_config.json]
#
# 环境变量（见 scripts/s2v_config.py）:
#   S2V_ROOT      工作根目录（默认 D:/dwvits）
#   S2V_REPO      OmniVoice 源码目录
#   S2V_MODEL     OmniVoice 基座模型目录
#   S2V_PYTHON    训练用 Python
#   S2V_WORK      工作目录（data/exp/out 都在其下）
set -euo pipefail

S2V_ROOT="${S2V_ROOT:-D:/dwvits}"
S2V_REPO="${S2V_REPO:-$S2V_ROOT/src/OmniVoice}"
S2V_MODEL="${S2V_MODEL:-$S2V_ROOT/models/omnivoice}"
S2V_PYTHON="${S2V_PYTHON:-$S2V_ROOT/envs/omnivoice/Scripts/python.exe}"
S2V_WORK="${S2V_WORK:-$S2V_ROOT/work}"
S2V_DATA="${S2V_DATA:-$S2V_WORK/data/omnivoice_dark_willow}"
S2V_EXP="${S2V_EXP:-$S2V_WORK/exp/omnivoice_dark_willow_lora}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HERE/../../configs"

TRAIN_CONFIG="${1:-$CONFIG_DIR/train_config_lora.json}"
DATA_CONFIG="${2:-$CONFIG_DIR/data_config.json}"

export PYTHONPATH="$S2V_REPO:${PYTHONPATH:-}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
# 关键：逐层 CPU offload，让 4GB 显存也能训 0.6B 模型
export OMNIVOICE_CPU_OFFLOAD=1

echo "REPO=$S2V_REPO"
echo "MODEL=$S2V_MODEL"
echo "DATA=$S2V_DATA"
echo "EXP=$S2V_EXP"
echo "CONFIG=$TRAIN_CONFIG"

"$S2V_PYTHON" -m omnivoice.cli.train \
    --train_config "$TRAIN_CONFIG" \
    --data_config "$DATA_CONFIG" \
    --output_dir "$S2V_EXP"
