---
license: mit
base_model: k2-fsa/OmniVoice
language:
- en
tags:
- tts
- voice-clone
- lora
- omnivoice
- deadlock
- paige
---

# PaigeVoice — Deadlock「Paige」音色模型

用 [OmniVoice](https://github.com/k2-fsa/OmniVoice) 0.6B 做 LoRA 微调得到的
**Deadlock 英雄 Paige** 音色模型。

## 来源

- 游戏：Deadlock（Valve / Citadel，Source 2 引擎）
- 英雄：**Paige**，游戏内内部代号 `bookworm`，语音目录 `sounds/vo/bookworm/`
- 语料：官方英文字幕（`citadel_generated_vo_english.txt`），**未经 ASR 改写**
- 提取 1615 clips / 45.8 min → 清洗分桶后 **1001 条**进训练集（train 981 / dev 20）

> Deadlock **没有中文语音包**（`citadel_schinese/` 仅含 panorama UI 资源），
> 因此本模型是**英文音色**。

## 用法

### 1. 独立模型（推荐）

```python
from omnivoice.models.omnivoice import OmniVoice
import soundfile as sf, torch

model = OmniVoice.from_pretrained(
    "wjcwqc/PaigeVoice", device_map="cuda:0", dtype=torch.float16
)
audios = model.generate(text="Let's steal their farm.", language="en")
sf.write("out.wav", audios[0], model.sampling_rate)
```

### 2. 命令行

```bash
python -m omnivoice.cli.infer \
    --model wjcwqc/PaigeVoice \
    --text "Let's steal their farm." \
    --language en \
    --output out.wav
```

### 3. 两种生成模式

| 模式 | 说明 |
|---|---|
| `ref` | 带参考音频 + 参考文本，音色最稳 |
| `noref` | 纯文本，音色已内化进 LoRA 参数，日常使用推荐 |

> 本仓库的评估脚本 `scripts/eval/test_infer.py` 会同时生成两种模式，
> 便于对比音色是否真的学进去了。

## 目录结构

```
PaigeVoice/
├── merged/        合并模型（独立可用，约 3.2 GB）
├── lora/          LoRA adapter（adapter_config.json + adapter_model.safetensors）
├── training/      训练配置、data_config、train.log
└── README.md
```

## 训练

| 项 | 值 |
|---|---|
| 基座 | OmniVoice 0.6B（Qwen3-0.6B） |
| 方法 | LoRA r=16 / alpha=32（4.2% 参数可训练）+ `audio_embeddings`/`audio_heads` 全训 |
| 超参 | lr 1e-4，600 步，batch_tokens 1024 × grad_accum 8，bf16，sdpa |
| 硬件 | RTX 3050 Ti 4 GB + `OMNIVOICE_CPU_OFFLOAD=1`（冻结权重常驻内存逐层流转 GPU） |
| 耗时 | 约 5 h 6 min（600 步 × 约 31 s/步，RTX 3050 Ti 4 GB） |

完整报告见 [`examples/deadlock_paige/REPORT.md`](https://github.com/wjcwqc/Source2Voice/blob/main/examples/deadlock_paige/REPORT.md)。

## 数据集

配套数据集仓库：[`wjcwqc/PaigeVoice-dataset`](https://huggingface.co/datasets/wjcwqc/PaigeVoice-dataset)

## 许可与声明

本仓库发布的是**模型权重与训练脚本**（MIT）。游戏语音资源的版权归
Valve / Valve Corporation 所有，本仓库仅供研究与个人学习使用，
**请勿用于商业分发**，并遵守 Deadlock 的最终用户许可协议（EULA）。
