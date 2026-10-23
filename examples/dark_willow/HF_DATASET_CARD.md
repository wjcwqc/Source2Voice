---
license: other
language:
- zh
tags:
- tts
- voice-cloning
- speech
- dota2
task_categories:
- text-to-speech
size_categories:
- n<1K
---

# MireskaVoice-dataset

邪影芳灵（Mireska Sunbreeze / Dark Willow，Dota 2）中文配音数据集，用于训练 [wjcwqc/MireskaVoice](https://huggingface.co/wjcwqc/MireskaVoice)（OmniVoice 语音克隆微调）。

## 内容

- **904 条**中文语音，总时长约 **0.8 小时**（平均 3.2 秒/条，最长 11 秒）
- 采样率 32kHz 单声道 WAV（训练时重采样至 24kHz）
- 覆盖技能、击杀、购买、死亡、对话等游戏内配音场景

## 目录结构

```
audio/       # 904 个 wav 文件，文件名即样本 id（如 sylph_ability1_01.wav）
metadata/
  schinese_dark_willow_vo_pure.list   # 原始清单: <音频路径>|<speaker>|<语言>|<文本>
  train.jsonl                          # OmniVoice 训练格式（884 条）
  dev.jsonl                            # 留出验证集（20 条）
```

JSONL 每行格式：`{"id": ..., "audio_path": ..., "text": ..., "language_id": "zh"}`（`audio_path` 为提取时的原始路径，实际文件在 `audio/` 下按 id 索引）。

## 数据来源与处理

- 音频与文本提取自 Dota 2 游戏客户端（`pak01_dir.vpk`），英文有官方字幕、中文台词由 Whisper 批量转写 + 人工校对规则修正
- 剔除了静音过长、转写置信度低的样本；文本保留了角色语气（标点按转写结果）

## 免责声明

角色“邪影芳灵”版权归 Valve Corporation 所有。本数据集仅供个人学习与研究使用，**禁止商业用途**。
