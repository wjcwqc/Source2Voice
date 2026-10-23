#!/usr/bin/env bash
# Source2Voice · 多英雄全流程流水线（示例：Deadlock Paige + Violet）
#
# 串行执行（一张 4GB 显存卡不能并发训两个模型）：
#   1. 训练 <hero> LoRA
#   2. 合并 + 校验
#   3. 推理冒烟（各 checkpoint，ref + noref）
#   4. 量化评估（CER + spk-sim）
#   5. 暂存 + 上传 HF 模型仓
#   6. 下一位英雄……
#
# 用法
# ----
#     # 按环境改下面的变量，或直接改 HEROES 列表
#     bash scripts/auto/pipeline_example.sh
#
# 评估口径说明：
#   --real_list 用的是 dev 留出集（**必须验证与训练集零重叠**），
#   真人基线 = 这些片段互相之间的平均 spk-sim。
#   用固定清单而不是 glob 采样，是因为基线随选中的片段变化，
#   换机器/换顺序就没法跟历史报告对比了。
set -uo pipefail

# ---------------------------------------------------------------- 路径配置
REPO="${S2V_REPO_ROOT:-D:/dwvits/repos/Source2Voice}"   # 本仓库
ROOT="${S2V_ROOT:-D:/dwvits}"                            # 工作根
WORK="${S2V_WORK:-$ROOT/work}"
EXP="${S2V_EXP_DIR:-$ROOT/exp}"
MODEL="${S2V_MODEL:-$ROOT/models/omnivoice}"
OMNIVOICE_SRC="${S2V_OMNIVOICE_SRC:-$ROOT/src/OmniVoice}"

# 训练 + 推理 + HF 上传用这个环境（有 huggingface_hub / hf_transfer）
PY_TRAIN="${S2V_PYTHON:-$ROOT/envs/omnivoice/Scripts/python.exe}"
# 数据准备 + 评估用这个环境（有 scipy / onnxruntime / whisper / zhconv）
PY_DATA="${S2V_PY_DATA:-$ROOT/envs/train/Scripts/python.exe}"

# 英雄列表：<hero_key> <显示名> <HF 前缀> <core 数据集目录名>
HEROES=(
  "paige  Paige  Paige  deadlock_paige_core"
  "violet Violet Violet deadlock_violet_core"
)

LOG=$EXP/pipeline.log

mkdir -p "$EXP"
exec >> "$LOG" 2>&1
echo "==== pipeline start $(date '+%F %T') ===="

# test_infer.py 需要 import omnivoice.*，所以推理用训练环境 + PYTHONPATH
export PYTHONPATH="$OMNIVOICE_SRC:${PYTHONPATH:-}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

step() { echo ""; echo "---- $* ---- $(date '+%T')"; }

# ---------------------------------------------------------------- 单英雄全流程
run_hero () {
  local hero="$1" display="$2" prefix="$3" dataset_name="$4"
  local data="$WORK/data/omnivoice_${prefix}_${hero}"
  local exp="$EXP/omnivoice_${prefix}_${hero}_lora"
  local merged="$EXP/omnivoice_${prefix}_${hero}_merged"
  local outdir="$WORK/out/omnivoice_${prefix}_${hero}"
  local stage="$WORK/stage/${hero}"
  local evals="$WORK/eval/${hero}_eval_texts.json"
  local reallist="$WORK/eval/${hero}_real_list.txt"
  local modelrepo="${S2V_HF_USER:-wjcwqc}/${display}Voice"

  step "=== $hero : 训练 ==="
  if [ -d "$exp/checkpoint-600" ]; then
    echo "已存在 $exp/checkpoint-600，跳过训练"
  else
    export S2V_ROOT="$ROOT"
    export S2V_REPO="$OMNIVOICE_SRC"
    export S2V_MODEL="$MODEL"
    export S2V_PYTHON="$PY_TRAIN"
    export S2V_WORK="$WORK"
    export S2V_DATA="$data"
    export S2V_EXP="$exp"
    cd "$REPO" || return 1
    bash scripts/train/run_train.sh \
      "$REPO/configs/train_config_lora.json" \
      "$data/data_config.json" || return 1
  fi

  step "=== $hero : 合并 LoRA ==="
  cd "$REPO" || return 1
  "$PY_TRAIN" scripts/publish/merge_and_verify.py --hero "$hero" \
    --base_model "$MODEL" \
    --adapter "$exp/checkpoint-600" \
    --output "$merged" || return 1

  step "=== $hero : 推理冒烟（各 checkpoint，ref + noref）==="
  # ref 音频取 dev 留出集第一条，文本从 dev.jsonl 里按 audio_path 精确配对
  for ck in checkpoint-300 checkpoint-450 checkpoint-600; do
    [ -d "$exp/$ck" ] || continue
    read -r ref reftxt < <("$PY_DATA" - "$data/dev.jsonl" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
r = rows[0]
print(r["audio_path"].replace("\\", "/"), r["text"])
PY
)
    echo "ref_audio=$ref"
    echo "ref_text=$reftxt"
    "$PY_TRAIN" "$REPO/scripts/eval/test_infer.py" \
      --lora_adapter "$exp/$ck" \
      --out_dir "$outdir/$ck" \
      --texts "$evals" --lang en \
      --ref_audio "$ref" --ref_text "$reftxt" || echo "WARN: 推理 $ck 失败"
  done

  step "=== $hero : 量化评估 ==="
  "$PY_DATA" "$REPO/scripts/eval/eval_omnivoice.py" \
    --ckpt_root "$outdir" \
    --real_list "$reallist" \
    --texts "$evals" --lang en || echo "WARN: 评估失败"

  step "=== $hero : 暂存 + 上传 HF ==="
  # --clean：清空暂存目录重建，避免上一轮残留的文件混进上传内容
  "$PY_DATA" "$REPO/scripts/publish/stage_hf.py" --hero "$hero" \
    --merged "$merged" \
    --lora "$exp/checkpoint-600" \
    --trainlog "$exp/train.log" \
    --train_config "$REPO/configs/train_config_lora.json" \
    --dataset_root "$data" \
    --audio_root "$ROOT/data/${dataset_name}/core" \
    --stage "$stage" \
    --clean \
    --model_card "$REPO/examples/deadlock_${hero}/HF_MODEL_CARD.md" || return 1

  # 上传必须联网：huggingface_hub 在 HF_HUB_OFFLINE=1 下会拦截**所有** HTTP 请求
  # （utils/_http.py 的 hf_request_event_hook），create_repo / upload_folder 会直接抛
  # OfflineModeIsEnabled，ALL_UPLOADS_COMPLETE 永远打不出来。
  # 只在这一条命令上解除离线，训练/推理/评估阶段仍然保持离线。
  HF_HUB_OFFLINE=0 HF_XET_HIGH_PERFORMANCE=1 \
    "$PY_TRAIN" "$REPO/scripts/publish/upload_hf.py" \
    --model_repo "$modelrepo" \
    --model_dir "$stage/model" \
    --message "Add ${display} (Deadlock) voice model: OmniVoice 0.6B LoRA, English" || return 1

  echo "=== $hero DONE ==="
}

for row in "${HEROES[@]}"; do
  # shellcheck disable=SC2086
  run_hero $row
done

echo ""; echo "==== pipeline finished $(date '+%F %T') ===="
grep -E "^---- |^=== |ALL_UPLOADS_COMPLETE|MERGE_OK|real clips" "$LOG" | tail -60
