---
license: apache-2.0
language:
- zh
tags:
- tts
- voice-cloning
- omnilingual
- lora
- finetune
- dota2
base_model: k2-fsa/OmniVoice
pipeline_tag: text-to-speech
---

# MireskaVoice

邪影芳灵（Mireska Sunbreeze / Dark Willow，Dota 2 英雄）中文音色的 **OmniVoice 微调模型**。

基于小米开源的 [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)（0.6B Qwen3 底座 + 离散扩散语言模型，639M 参数），使用 904 条游戏内中文配音（0.8 小时）进行 LoRA 微调（r=16，约 4.2% 参数可训练）。音色已内化到模型参数：**纯文本合成即可获得角色音色，无需参考音频**。

## 目录结构

| 路径 | 内容 |
|---|---|
| `merged/` | 合并后的独立模型（LoRA 已合并进权重，直接加载即用） |
| `lora/` | LoRA adapter（可挂到原版 OmniVoice 上使用，107MB） |
| `training/` | 训练配置、数据准备与 tokenize 脚本、完整训练日志 |
| `REPORT.md` / `MANIFEST.md` | 评估报告与样本清单 |

## 使用方法

### 方式一：合并模型（推荐）

```python
import torch
from omnivoice.models.omnivoice import OmniVoice

model = OmniVoice.from_pretrained(
    "wjcwqc/MireskaVoice",  # 或本地 merged/ 目录
    device_map="cuda:0", dtype=torch.float16)
audio = model.generate(text="待着吧,哪儿也别想去。", language="zh")
```

### 方式二：base + LoRA adapter

```python
from omnivoice.utils.lora import load_lora_adapter

model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
model = load_lora_adapter(model, "wjcwqc/MireskaVoice/lora")
```

### 命令行

```bash
omnivoice-infer --model wjcwqc/MireskaVoice --text "天,我爱死钱了!" --language zh --output out.wav
```

### HTTP 服务

`D:/dwvits/deploy/` 提供了 FastAPI 服务（`/tts` 端点，支持参考音频克隆），详见随附文档。

## 效果评估（4 条留出文本，真人片段互相相似度基线 0.644）

| 模式 | CER（字错率）↓ | spk-sim（音色相似度）↑ |
|---|---|---|
| 纯文本 | 0.028 | 0.758 |
| 带参考音频 | 0.028 | 0.767 |

与 CosyVoice3 零样本（CER 0.056 / sim 0.706）和 VITS 微调（CER 0.306 / sim 0.572）的同文本对比中，本模型三项指标均最优，详见 `REPORT.md`。

推理速度（RTX 3050 Ti 4G，fp16）：约 3.4 秒/句（RTF 0.71，快于实时）。

## 训练信息

- **数据**：904 条 / 0.8 小时（884 训练 + 20 留出），32kHz 原始音频重采样至 24kHz；数据集见 [wjcwqc/MireskaVoice-dataset](https://huggingface.co/datasets/wjcwqc/MireskaVoice-dataset)
- **方法**：LoRA r=16 alpha=32 dropout=0.05，目标层 q/k/v/o/gate/up/down_proj + 全量训练 audio_embeddings/audio_heads
- **超参**：lr 1e-4（warmup 3%），600 步，batch_tokens 1024 × grad_accum 8，bf16 混合精度
- **硬件**：单卡 RTX 3050 Ti Laptop 4GB——Windows 无 NCCL，冻结的 fp32 基座权重常驻系统内存、按 decoder 层流转到 GPU（自研逐层 offload），4 小时 52 分完成
- **过程**：loss 4.5 → 3.96；配置、脚本与完整日志见 `training/`

## 免责声明

本模型为个人学习/研究用途的语音克隆作品。角色“邪影芳灵”版权归 Valve Corporation 所有，原始配音数据提取自游戏文件。**请勿用于商业用途**。模型权重继承 OmniVoice 的 Apache-2.0 许可。
