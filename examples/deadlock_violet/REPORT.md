# OmniVoice 微调 Deadlock「Violet」音色 — 训练与评估报告

> Violet 的**完整训练与评估报告**（语料体检、清洗分桶、Token 映射规则、
> 训练配置、CER / spk-sim 实测结果）与 Paige 同属一份文档，
> 因为两者共用同一套管线与超参，只有数据不同。
>
> 👉 见 **[`../deadlock_paige/REPORT.md`](../deadlock_paige/REPORT.md)**

本页只列 Violet 专属的差异项。

## Violet 专属数据

| 指标 | Violet |
|---|---|
| 英雄内部代号 | `artist` |
| 语音目录 | `sounds/vo/artist/` |
| 提取 clips | 2111（50.8 min） |
| 台词覆盖率 | 2033 / 2111 = **96.3%** |
| 清洗分桶 | core 1289 / style 594 / review 150 |
| 最终训练集 | 1289 → **train 1269 / dev 20** |
| HF 模型仓 | [`wjcwqc/VioletVoice`](https://huggingface.co/wjcwqc/VioletVoice) |
| HF 数据集仓 | [`wjcwqc/VioletVoice-dataset`](https://huggingface.co/datasets/wjcwqc/VioletVoice-dataset) |

## 交付物

| 内容 | 路径 |
|---|---|
| 合并模型 | `D:/dwvits/exp/omnivoice_deadlock_violet_merged` |
| LoRA checkpoint | `D:/dwvits/exp/omnivoice_deadlock_violet_lora/checkpoint-{300,450,600}` |
| 数据集 | `D:/dwvits/data/deadlock_violet_core/` |
| 训练数据 | `D:/dwvits/work/data/omnivoice_deadlock_violet/` |

## 评估口径

与 Paige 完全一致：CER = Whisper 转写后字符级编辑距离；spk-sim = campplus
ONNX 嵌入与真人留出集的余弦相似度；真人基线 = 20 条 dev 留出集片段互相之间
的平均 spk-sim（`--real_list` 固定清单，可与历史报告对比）。
