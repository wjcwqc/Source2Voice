# OmniVoice 邪影芳灵微调 — 音频样本清单

日期：2026-10-24 | 模型：OmniVoice LoRA 微调（600 步训练完成）

## 一、同文本对比（compare/ 目录）—— 同一句话「天,我爱死钱了!」

| 文件 | 模型 | 模式 | 说明 |
|---|---|---|---|
| `compare/00_真人原声_参考.wav` | — | — | 游戏原声（留出集，未参与训练） |
| `compare/ckpt300_ref.wav` | checkpoint-300 | ref | 300 步 + 参考音频 |
| `compare/ckpt300_noref.wav` | checkpoint-300 | noref | 300 步，纯文本 |
| `compare/ckpt450_ref.wav` | checkpoint-450 | ref | 450 步 + 参考音频 |
| `compare/ckpt450_noref.wav` | checkpoint-450 | noref | 450 步，纯文本 |
| `compare/ckpt600_ref.wav` | checkpoint-600 | ref | 600 步 + 参考音频 |
| `compare/ckpt600_noref.wav` | checkpoint-600 | noref | 600 步，纯文本 |
| `compare/merged_ref.wav` | 合并模型(600) | ref | 官方 merge-lora 合并后 |
| `compare/merged_noref.wav` | 合并模型(600) | noref | 官方 merge-lora 合并后 |

ref = 带参考音频（sylph_bounty_02.wav）；noref = 不给参考音频，纯文本合成。

## 二、分模型样本（ckpt-300 / ckpt-450 / ckpt-600 / merged 目录）

每个目录 8 条：4 条留出文本 × ref/noref。命名 `{tid}_{mode}.wav`：

| tid | 文本 |
|---|---|
| t01 | 我想你在哪儿,你就在哪儿。 |
| t02 | 天,我爱死钱了! |
| t03 | 跟我计划的不太一样 |
| t04 | 相信自然的力量,它总会找到出路。 |

`merged/` 目录另有 m1/m2/m3 三条新文本样本。

## 三、评估汇总（详见 REPORT.md）

真人 DW 片段互相相似度基线 0.644：

| 模型 | 模式 | CER ↓ | spk-sim ↑ |
|---|---|---|---|
| ckpt-300 | ref | 0.042 | 0.694 |
| ckpt-300 | noref | 0.045 | 0.660 |
| ckpt-450 | ref | 0.045 | 0.614 |
| ckpt-450 | noref | 0.063 | 0.657 |
| ckpt-600 | ref | **0.000** | 0.664 |
| ckpt-600 | noref | 0.060 | 0.636 |

**推荐：ckpt-600（或 merged 合并模型）+ ref 模式**——内容零错误、相似度超真人基线；日常使用 noref 也可（音色已内化）。
