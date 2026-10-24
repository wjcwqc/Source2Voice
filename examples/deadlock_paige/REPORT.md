# OmniVoice 微调 Deadlock 英雄音色 — 训练与评估报告（Paige / Violet）

日期：2026-10-24 | 游戏：Deadlock（Valve / Citadel）| 数据：官方英文字幕（**无需 ASR**）

## 关键背景：为什么这轮比 Dota 2 那轮快

| 维度 | Dota 2 邪影芳灵 | Deadlock Paige / Violet |
|---|---|---|
| 台词来源 | VPK 内 `resource/subtitles/`（英文）+ **Whisper ASR 生成中文** | 磁盘 `citadel_generated_vo_english.txt`（**官方英文**） |
| ASR 阶段 | 2–4 h CPU + **~2 h 人工校对** | **完全跳过** |
| 语料质量 | 需逐条校对（繁简、术语、同音错字） | **0 CJK 混入 / 0 超短句 / 无需人工修正** |
| 全流程耗时 | 10–14 h | **6–7 h** |

> **Deadlock 没有中文语音包**：`citadel_schinese/pak01_dir.vpk` 仅 50 条 panorama UI
> 资源，0 个 `.vsnd_c`。这是游戏本身的状态，不是配置问题。

## 英雄代号映射（最容易踩的坑）

| 显示名 | 内部代号 | 语音目录 |
|---|---|---|
| **Paige** | `bookworm` | `sounds/vo/bookworm/` |
| **Violet** | `artist` | `sounds/vo/artist/` |
| Billy | `punkgoat` | `sounds/vo/punkgoat/` |

映射来源：磁盘上的 `hero_presence_cache.json`（56 条）。
**Paige = `punkgoat` 是错的**（那是 Billy）。

## 提取与语料体检

| 指标 | Paige | Violet |
|---|---|---|
| 提取 clips | 1615（45.8 min） | 2111（50.8 min） |
| 台词覆盖率（token 命中） | 1547 / 1615 = **95.8%** | 2033 / 2111 = **96.3%** |
| 唯一台词 | 1524 | 2009 |
| 重复台词 | 23 | 20 |
| 超短文本（< 2 词） | 0 | 0 |
| CJK 混入 | **0** | **0** |
| 未匹配项 | 纯音效（无台词） | 纯音效（无台词） |

## 清洗分桶

| 英雄 | core | style | review | 最终训练集 |
|---|---|---|---|---|
| Paige | 1001 | 522 | 24 | 1001 → train 981 / dev 20 |
| Violet | 1289 | 594 | 150 | 1289 → train 1269 / dev 20 |

`core` 用于首轮音色训练；`style`（语气夸张/重复）留作后续语气增强；
`review`（声学离群）需人工听审，不进首轮。

## Token 映射规则（Deadlock 特有）

Deadlock 的字幕 token 命名是 `<音频stem>_<后缀>`：

```
bookworm_spawn_01.vsnd_c  →  token "bookworm_spawn_01_hero_3d"
```

后缀集合：`hero_3d` / `ability_3d` / `ult_3d` / `zipline_3d` / `ping_2d` /
`hero_announcer`，且存在 `_alt` 一对多变体。因此英雄档案用
**前缀通配 + 显式优先级**：

```json
"token_rules": { "vo": ["{stem}_*"] },
"token_priority": ["hero_3d","ability_3d","ult_3d","zipline_3d","ping_2d","hero_announcer"]
```

## 训练配置

与 Dota 2 那轮**完全一致**（同一套超参，只换数据）：

| 参数 | 值 |
|---|---|
| 模型 | OmniVoice 0.6B（Qwen3-0.6B 底座）LoRA，r=16 / alpha=32（4.2% 参数可训练） |
| lr / steps | 1e-4 / 600 |
| batch_tokens × grad_accum | 1024 × 8（≈8192 tokens/步） |
| mixed_precision / attn | bf16 / sdpa |
| num_workers | 0（Windows 多进程 spawn 会炸） |
| save_steps / eval_steps | 150 / 150 |
| `OMNIVOICE_CPU_OFFLOAD` | **1**（4 GB 显存的关键：冻结权重常驻内存逐层流转 GPU） |

单步耗时 **约 31 s/步**（RTX 3050 Ti 4 GB），与 Dota 2 那轮几乎一致。
600 步总耗时约 **5 h 6 min**。

## 训练结果

### Paige 量化评估实测结果

评估口径：CER = Whisper `medium` 转写后字符级编辑距离；spk-sim = campplus ONNX 嵌入与真人留出集的余弦相似度。
真人基线 = 20 条 dev 留出集片段互相之间的平均 spk-sim = **0.5522**。

| checkpoint | 模式 | CER ↓ | spk-sim ↑ | vs 真人基线 |
|---|---|---|---|---|
| `checkpoint-300` | ref | 0.019 | 0.5809 | +0.0287 **PASS** |
| `checkpoint-300` | noref | 0.019 | 0.5617 | +0.0095 **PASS** |
| `checkpoint-450` | ref | 0.019 | 0.5655 | +0.0133 **PASS** |
| `checkpoint-450` | noref | 0.019 | 0.5500 | -0.0022 below |
| `checkpoint-600` | ref | 0.019 | 0.5782 | +0.0260 **PASS** |
| `checkpoint-600` | noref | 0.019 | 0.5571 | +0.0049 **PASS** |

小结：

* `checkpoint-300` 最佳 ref 模式：CER 0.019，spk-sim 0.5809（基线 +0.0287）
* `checkpoint-450` 最佳 ref 模式：CER 0.019，spk-sim 0.5655（基线 +0.0133）
* `checkpoint-600` 最佳 ref 模式：CER 0.019，spk-sim 0.5782（基线 +0.0260）


## 交付物

| 内容 | 路径 |
|---|---|
| 合并模型 | `D:/dwvits/exp/omnivoice_deadlock_paige_merged` / `..._violet_merged` |
| LoRA checkpoint | `D:/dwvits/exp/omnivoice_deadlock_{paige,violet}_lora/checkpoint-{300,450,600}` |
| 数据集 | `D:/dwvits/data/deadlock_{paige,violet}_core/` |
| 训练数据 | `D:/dwvits/work/data/omnivoice_deadlock_{paige,violet}/` |
| HF 模型仓 | `wjcwqc/PaigeVoice`、`wjcwqc/VioletVoice` |
| HF 数据集仓 | `wjcwqc/PaigeVoice-dataset`、`wjcwqc/VioletVoice-dataset` |

## 本轮踩到并修复的坑

1. **`file:///` 前缀加错位置** —— 训练启动即报
   `AssertionError: file:///D:/... is not a file.`。
   `manifest_path` 必须是**普通绝对路径**（`os.path.isfile` 校验），
   `file:///` 只出现在 data.lst **内部**的 tar 路径（webdataset gopen）。
   已修复 `make_data_config.py` + `tokenize_single.py`，并加 `normalize_data_lst()` 自愈。
2. **多英雄 manifest 互相覆盖** —— 已改为 `manifest_<hero_key>.json` 分开存储 +
   自动合并去重。
3. **评估脚本硬编码 Dota 2 路径** —— `eval_omnivoice.py` / `test_infer.py`
   已参数化（`--ckpt_root` / `--real_dir` / `--texts` / `--lang`），
   且英文侧**不做繁转简**（`zhconv` 是中文专用）。
