# Source2Voice

**从 Source 2 游戏语音到可发布的 TTS 音色模型 —— 一条端到端、可复现的流水线。**

以 Dota 2 英雄「邪影芳灵 / Dark Willow」为实例，完整跑通了：

```
游戏 VPK 资源 → 音频提取 → 中英分离 + ASR 生成中文台词 → 数据清洗
    → OmniVoice LoRA 微调 → 量化评估 → 合并导出 → HuggingFace 发布
```

> 实测：904 条中文语音（0.8 h）→ 4 GB 显存笔记本卡训练 4 h 52m →
> CER 0.000、说话人相似度 0.664（**超过真人基线 0.644**）→ 3.2 GB 模型上 HF。

---

## 为什么需要这个技能

从游戏里"偷"英雄音色做 TTS，有几个反直觉的障碍：

1. **Valve 通常不给中文字幕。** 英文有官方字幕（token 精确匹配），中文只能靠 ASR。
   而 ASR 是整个流程里最贵的一环（纯 CPU，2400 条要 1.5–10 小时）。
2. **Whisper 对 1–3 秒短句极不友好** —— 固定 30 秒窗口，不打包就得跑一整天。
3. **窗口打包会引入边界粘连**，中文文本会脏，不修的话模型学到的是脏发音。
4. **4 GB 显存的笔记本根本跑不动 0.6B 模型的常规微调** —— Windows 没 NCCL，FSDP 不可用。
5. **不知道怎么判断"学到了没有"** —— 相似度 0.6 是好是坏？没有基线就没有答案。

这个仓库把上面每一步都踩过一遍，把可复现的部分固化成脚本，把不可复现的
部分（ASR 文本修正、术语表、评估基线）写成文档。

---

## 六阶段流水线

| 阶段 | 内容 | 脚本 | 参考耗时 |
|---|---|---|---|
| 0 | 定位资源：游戏目录 / 英雄代号 / 字幕 / VPK 布局 | — | 10 min |
| 1 | 提取音频：解 VPK → 剥 `.vsnd_c` → MP3 → WAV | `scripts/extract/` | 5 min |
| 2 | **中英分离 + ASR**：英文用官方字幕，中文 Whisper 生成 + 修正 | `scripts/asr/` | **2–4 h** |
| 3 | 数据清洗：纠错 / 剔幻觉 / 响度分桶 | `scripts/clean/` | 1–2 h |
| 4 | 训练数据：JSONL 划分 + audio tokenize + data_config | `scripts/train/` | 15 min |
| 5 | **LoRA 微调**：OmniVoice 0.6B，4 GB 显存可跑 | `scripts/train/run_train.sh` | **5–6 h** |
| 6 | 评估 + 合并 + 发布 HF | `scripts/eval/` `scripts/publish/` | 1 h |

详细命令与验收项见 **[references/WORKFLOW.md](references/WORKFLOW.md)**。

---

## 核心设计

### 1. 英雄档案驱动，换英雄只改一个 JSON

```json
{
  "hero_key": "dark_willow",
  "asset_prefixes": ["helmet_sylph_", "sylph_"],
  "groups": { "vo": "sounds/vo/dark_willow/" },
  "subtitle_files": ["resource/subtitles/subtitles_dark_willow_english.txt"],
  "token_rules": { "vo": ["dark_willow_{stem}", "sylph_sylph_{rest_sylph}"] }
}
```

`token_rules` 用模板描述字幕 token 的命名规则，按优先级取第一个命中的候选。
Valve 的命名有多套并存（显示名 / 内部代号 / 旧命名表），这个抽象把它们收拢了。

### 2. 所有路径环境变量化

```bash
export S2V_ROOT=D:/dwvits
export S2V_GAME_DIR="D:/SteamLibrary/steamapps/common/dota 2 beta"
export S2V_DATASET_DIR=D:/DarkWillow_VoiceDataset
python scripts/s2v_config.py   # 打印全部路径 + 存在性检查
```

脚本源码里没有一个硬编码的 `D:/` 绝对路径。

### 3. 低显存训练：把内存当显存

Windows PyTorch 无 NCCL → FSDP 不可用。方案是**单进程 + 逐层 CPU offload**：
冻结的 fp32 基座权重（2.4 GB）常驻系统 RAM，每个 decoder 层用前才流转到 GPU，
LoRA adapter 与 `audio_embeddings`/`audio_heads` 常驻显存。

**4 GB 显存 + 16 GB 内存**即可训 0.6B 模型。补丁见 [`patches/`](patches/)。

### 4. 每阶段都有验收项

不是「跑完就算」，而是命令输出必须对得上：
`matched subtitle` 数、`asr_cache` 覆盖率、繁体残留数、CER、相似度 vs 基线。
详见 WORKFLOW.md 各阶段的 ✅ 验收项。

---

## 效果

| checkpoint | 模式 | CER ↓ | 相似度 ↑ |
|---|---|---|---|
| **ckpt-600** | ref | **0.000** | 0.664 |
| ckpt-600 | noref | 0.060 | 0.636 |
| ckpt-300 | ref | 0.042 | **0.694** |
| ckpt-300 | noref | 0.045 | 0.660 |

**真人片段互相相似度基线 = 0.644。** ckpt-600 的 0.664 已超过基线 ——
这是判断「音色真的学到了」的依据，而不是看绝对值。

推理速度（RTX 3050 Ti 4G，24 字中文）：**3.36 s/句，RTF 0.71**（快于实时）。

完整报告：[examples/dark_willow/REPORT.md](examples/dark_willow/REPORT.md)

---

## 快速开始

```bash
git clone https://github.com/<user>/Source2Voice.git
cd Source2Voice

# 1. 配置路径
export S2V_ROOT=/path/to/work
export S2V_GAME_DIR="/path/to/Steam/steamapps/common/dota 2 beta"
export S2V_DATASET_DIR=/path/to/Hero_VoiceDataset
python scripts/s2v_config.py

# 2. 走六阶段（详细命令见 references/WORKFLOW.md）
python scripts/extract/pipeline.py --hero configs/hero_dark_willow.json --out "$S2V_DATASET_DIR"
# ... 阶段 2~6 见 WORKFLOW.md
```

### 环境准备

```bash
# 训练环境
python -m venv envs/omnivoice
envs/omnivoice/Scripts/pip install "setuptools<81"
envs/omnivoice/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cu128
envs/omnivoice/Scripts/pip install transformers accelerate peft soundfile scipy webdataset audioop-lts
envs/omnivoice/Scripts/pip install -e <OmniVoice源码> --no-build-isolation

# ASR 环境
pip install faster-whisper ctranslate2
pip install hf_transfer huggingface_hub   # HF 上传加速，缺了会慢 200×
```

---

## 目录结构

```
Source2Voice/
├── SKILL.md                    技能入口（AI 可复现的工作流说明）
├── configs/
│   ├── hero_dark_willow.json   英雄档案（换英雄只改这个）
│   ├── train_config_lora.json  LoRA 训练配置
│   └── data_config.json        训练数据清单
├── scripts/
│   ├── s2v_config.py           全局路径配置
│   ├── extract/                阶段 1：VPK 解析、vsnd_c 剥离、清单生成
│   ├── asr/                    阶段 2：窗口打包 ASR、边界修正、术语校正、幻觉检测
│   ├── clean/                  阶段 3：子集筛选、文本纠错、响度分桶
│   ├── train/                  阶段 4-5：JSONL、tokenize、data_config、训练、合并
│   ├── eval/                   阶段 6：推理冒烟、CER + 说话人相似度评估
│   └── publish/                阶段 7：HF 上传、HTTP 推理服务
├── references/
│   ├── WORKFLOW.md             六阶段详细命令 + 验收项
│   ├── REQUIREMENTS.md         硬件 / 时间 / 算力要求（实测数据）
│   └── TROUBLESHOOTING.md      全部已知坑与解法
├── patches/                    OmniVoice 低显存训练补丁
└── examples/dark_willow/       邪影芳灵完整实战记录
```

---

## 踩过的坑（节选）

| 坑 | 解法 |
|---|---|
| `.vsnd_c` 前 4 字节小端 uint32 = MP3 起始偏移 | 剥离头部即得 MP3 |
| Whisper 固定 30 秒窗口，逐条识别浪费 95% 算力 | 窗口打包 + 词级时间戳回切（**40× 提速**） |
| 窗口打包导致下一条开头粘到上一条末尾 | 单独重识别 + 按长度融合裁剪 |
| Whisper 在非语音上吐 YouTube 字幕模板 | 关键词表 + 重复检测，标注后剔除 |
| 专有名词同音错字（灰药/辉耀） | **拼音级**匹配，不是字符级 |
| 4 GB 显存 OOM | 逐层 CPU offload（内存当显存） |
| Windows 无 NCCL → FSDP 不可用 | 单进程 + 自研 offload |
| data.lst 的 tar 路径 | 必须 `file:///D:/...` |
| PEFT 键名带 `.default` 导致合并失效 | 用官方 `merge_lora` CLI |
| CER 虚高 | whisper 输出繁体 → CER 前 `zhconv` 转简体 |
| HF 上传 150 KB/s | 装 `hf_transfer`（**34 MB/s**） |
| 代理端口猜错连不上 HF | 从 Windows 注册表读 `ProxyServer` |

完整清单见 [references/TROUBLESHOOTING.md](references/TROUBLESHOOTING.md)。

---

## 适用边界

- **只适用于 Source 2 引擎的游戏**（Dota 2 / CS2 等），依赖 `.vsnd_c` 容器格式与 VPK 打包
- 中文台词靠 ASR 生成，**准确率不保证 100%**，必须人工/规则校对
- 本仓库脚本针对 Dota 2 验证；换游戏需要重做阶段 0（英雄档案）和字幕 token 映射
- 训练数据 < 200 条时音色不稳定；> 5000 条需要更大显存

## 致谢

- [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) — TTS 基座
- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) — ASR
- [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice) — campplus 说话人验证
- Valve / Dota 2 — 语音资源与官方字幕

## 许可

本仓库的**脚本与文档**以 MIT 许可发布。
游戏语音资源的版权归 Valve 所有，请勿用于商业分发；
请遵守 Dota 2 最终用户许可协议（EULA）。
