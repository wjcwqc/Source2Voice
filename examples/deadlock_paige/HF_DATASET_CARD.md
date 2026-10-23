---
license: mit
language:
- en
tags:
- dataset
- tts
- voice-clone
- deadlock
- paige
- game-voice
---

# PaigeVoice Dataset — Deadlock「Paige」英文语音数据集

从 Deadlock（Valve / Citadel）游戏资源中提取的 **Paige** 英雄英文语音，
配套 [`wjcwqc/PaigeVoice`](https://huggingface.co/wjcwqc/PaigeVoice) 音色模型。

## 概况

| 项 | 值 |
|---|---|
| 英雄 | **Paige**（内部代号 `bookworm`，语音目录 `sounds/vo/bookworm/`） |
| 语言 | 英文（**en**） |
| 台词来源 | 官方本地化文件 `citadel_generated_vo_english.txt`，**未经 ASR 改写** |
| 提取总量 | 1615 clips / 45.8 min |
| 台词覆盖率 | 1547 / 1615 = **95.8%**（未匹配项为纯音效） |
| 唯一台词 | 1524（23 句重复） |
| 语料质量 | 0 超短句 / 0 CJK 混入 / 无需人工校对 |
| 发布版本 | `core` 桶 **1001 条**（另有 style 522 / review 24 未发布） |

## 数据来源与提取方式

- 音频：`<Steam>/steamapps/common/Deadlock/game/citadel/pak01_dir.vpk`
  里的 `sounds/vo/bookworm/*.vsnd_c`
- 容器格式：`.vsnd_c` 前 4 字节小端 uint32 = MP3 流起始偏移，剥离即得裸 MP3
- 字幕：`<Steam>/.../game/citadel/resource/localization/citadel_generated_vo/citadel_generated_vo_english.txt`
  （KV 风格 `"token" "text"`，5.8 MB / 78453 行）
- 转码：ffmpeg → 32 kHz / 16 bit / mono WAV
- 清洗：RMS 归一到 -20 dBFS、削波检测、按 group 分组的响度离群判定，
  三桶划分（core / style / review）

## 目录结构

```
PaigeVoice-dataset/
├── audio/
│   └── wavs/           1001 条 WAV（22.05 kHz / 16 bit / mono）
├── metadata/
│   ├── core.list       GPT-SoVITS 格式：wav|speaker|lang|text
│   ├── train.jsonl     OmniVoice 训练用（981 条）
│   └── dev.jsonl       留出集（20 条，不参与训练）
└── README.md
```

`.list` 格式：

```
D:/.../wavs/spk_0002_87c1bff0.wav|paige|en|Good luck sheriff
```

## 用途

- 训练 / 微调 TTS 音色模型（OmniVoice LoRA、GPT-SoVITS、CosyVoice 等）
- 说话人验证（campplus 等）
- TTS 效果评测的真人基线

## 许可与声明

数据集内容是 **Valve 的游戏语音资源**，版权归 Valve / Valve Corporation 所有。
本仓库仅供研究与个人学习使用，**请勿用于商业分发**，
并遵守 Deadlock 的最终用户许可协议（EULA）。
