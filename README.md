# Source2Voice

**从 Source 2 游戏语音到可发布的 TTS 音色模型 —— 一条端到端、可复现的流水线。**

已跑通两个实例：

| 实例 | 游戏 | 数据 | 结果 |
|---|---|---|---|
| **MireskaVoice**（邪影芳灵） | Dota 2 | 904 条中文（0.8 h） | CER 0.000、相似度 0.664（**超真人基线 0.644**） |
| **PaigeVoice / VioletVoice** | Deadlock | 1001 / 1289 条英文（0.9 / 1.1 h） | 见 `examples/deadlock_paige/` |

```
游戏 VPK 资源 → 音频提取 → 台词对齐（官方字幕 / ASR）→ 数据清洗分桶
    → OmniVoice LoRA 微调 → 量化评估 → 合并导出 → HuggingFace 发布
```

> 实测：4 GB 显存笔记本卡训练 4 h 52m → 3.2 GB 模型上 HF。

---

## 为什么需要这个技能

从游戏里"偷"英雄音色做 TTS，有几个反直觉的障碍：

1. **显示名 ≠ 内部代号。** Dota 2 的「邪影芳灵」在资源里是 `dark_willow`、
   音频是 `helmet_sylph_*`；Deadlock 的「Paige」是 **`bookworm`**，
   「Violet」是 **`artist`**，「Billy」是 **`punkgoat`**。猜错就全盘找不到。
2. **Valve 通常不给中文字幕。** 英文有官方字幕（token 精确匹配），中文只能靠 ASR。
   而 ASR 是整个流程里最贵的一环（纯 CPU，2400 条要 1.5–10 小时）。
3. **Whisper 对 1–3 秒短句极不友好** —— 固定 30 秒窗口，不打包就得跑一整天。
4. **窗口打包会引入边界粘连**，中文文本会脏，不修的话模型学到的是脏发音。
5. **4 GB 显存的笔记本根本跑不动 0.6B 模型的常规微调** —— Windows 没 NCCL，FSDP 不可用。
6. **不知道怎么判断"学到了没有"** —— 相似度 0.6 是好是坏？没有基线就没有答案。

这个仓库把上面每一步都踩过一遍，把可复现的部分固化成脚本，把不可复现的
部分（ASR 文本修正、术语表、评估基线）写成文档。

---

## 通用流水线

| 阶段 | 内容 | 脚本 | 参考耗时 |
|---|---|---|---|
| 0 | 定位资源：游戏目录 / 英雄代号 / 台词来源 / VPK 布局 | — | 10 min |
| 1 | 提取音频：解 VPK → 剥 `.vsnd_c` → MP3 → WAV | `scripts/extract/` | 5 min |
| 2 | 台词对齐：官方字幕直用 / 缺失语言走 ASR | `scripts/asr/` | **0 或 2–4 h** |
| 3 | 数据清洗：体检 / 纠错 / 响度分桶 | `scripts/clean/` | 20 min |
| 4 | 训练数据：JSONL 划分 + audio tokenize + data_config | `scripts/train/` | 15 min |
| 5 | **LoRA 微调**：OmniVoice 0.6B，4 GB 显存可跑 | `scripts/train/run_train.sh` | **5–6 h** |
| 6 | 评估 + 合并 + 发布 HF | `scripts/eval/` `scripts/publish/` | 1 h |

详细命令与验收项见 **[references/WORKFLOW.md](references/WORKFLOW.md)**。

---

## 已支持的游戏

| 游戏 | `S2V_GAME` | 语言包 | 台词来源 | 是否需要 ASR |
|---|---|---|---|---|
| Dota 2 | `dota2` | `dota` + `dota_schinese` | VPK 内 `resource/subtitles/` | 中文需要，英文不用 |
| Deadlock | `deadlock` | `citadel`（**仅英文**） | **磁盘未打包目录** `citadel_generated_vo/` | **完全不需要** |
| CS2 | `cs2` | `csgo` + `csgo_schinese` | VPK 内 | 未验证 |

> **选游戏前先确认台词来源。** Deadlock 只有英文语音，但英文台词是官方
> 本地化文件 → 阶段 2 整段跳过，全流程从 10–14 h 缩到 6–7 h，
> 且文本质量极高（实测 0 CJK 混入、0 超短句、无需人工修正）。

---

## 核心设计

### 1. 英雄档案驱动，换英雄只改一个 JSON

```json
{
  "game": "deadlock",
  "hero_key": "paige",
  "asset_code": "bookworm",
  "asset_prefixes": ["bookworm_"],
  "groups": { "vo": "sounds/vo/bookworm/" },
  "subtitle_sources": ["file:<游戏>/game/citadel/resource/localization/citadel_generated_vo/citadel_generated_vo_english.txt"],
  "token_rules": { "vo": ["{stem}_*"] },
  "token_priority": ["hero_3d", "ability_3d", "ult_3d", "zipline_3d", "ping_2d", "hero_announcer"]
}
```

`token_rules` 用模板描述字幕 token 的命名规则（`{stem}` / `{rest_<前缀>}` / `{stem}_*` 通配），
按优先级取第一个命中的候选。Valve 的命名有多套并存（显示名 / 内部代号 / 旧命名表），
这个抽象把它们收拢了。

`subtitle_sources` 支持三种来源：
- `vpk:<相对路径>` —— 台词在 VPK 内（Dota 2）
- `file:<绝对路径 glob>` —— 台词在磁盘未打包目录（Deadlock）
- `inline:<json>` —— 直接内联少量台词

### 2. 所有路径环境变量化

```bash
export S2V_ROOT=D:/dwvits
export S2V_GAME=deadlock
export S2V_GAME_DIR="D:/SteamLibrary/steamapps/common/Deadlock"
export S2V_DATASET_DIR=D:/Deadlock_VoiceDataset
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

### Dota 2 · 邪影芳灵（中文）

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
git clone https://github.com/wjcwqc/Source2Voice.git
cd Source2Voice

# 1. 配置路径
export S2V_ROOT=/path/to/work
export S2V_GAME=deadlock          # 或 dota2 / cs2
export S2V_GAME_DIR="/path/to/Steam/steamapps/common/Deadlock"
export S2V_DATASET_DIR=/path/to/Hero_VoiceDataset
python scripts/s2v_config.py

# 2. 走六阶段（详细命令见 references/WORKFLOW.md）
python scripts/extract/pipeline.py --hero configs/hero_deadlock_paige.json --out "$S2V_DATASET_DIR"
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

# ASR 环境（仅当游戏缺官方字幕时需要，如 Dota 2 中文）
pip install faster-whisper ctranslate2
pip install hf_transfer huggingface_hub   # HF 上传加速，缺了会慢 200×
```

---

## 目录结构

```
Source2Voice/
├── SKILL.md                    技能入口（AI 可复现的工作流说明）
├── configs/
│   ├── hero_dark_willow.json   英雄档案（Dota 2）
│   ├── hero_deadlock_paige.json   英雄档案（Deadlock Paige）
│   ├── hero_deadlock_violet.json  英雄档案（Deadlock Violet）
│   ├── train_config_lora.json  LoRA 训练配置
│   └── data_config.json        训练数据清单
├── scripts/
│   ├── s2v_config.py           全局路径配置 + 游戏注册表
│   ├── extract/                阶段 1：VPK 解析、vsnd_c 剥离、清单生成
│   ├── asr/                    阶段 2：窗口打包 ASR、边界修正、术语校正、幻觉检测
│   ├── clean/                  阶段 3：体检、子集筛选、文本纠错、响度分桶
│   ├── train/                  阶段 4-5：JSONL、tokenize、data_config、训练、合并
│   ├── eval/                   阶段 6：推理冒烟、CER + 说话人相似度评估
│   └── publish/                阶段 7：合并校验、暂存目录、HF 上传、HTTP 推理服务
├── references/
│   ├── WORKFLOW.md             通用工作流 + 各游戏差异
│   ├── REQUIREMENTS.md         硬件 / 时间 / 算力要求（实测数据）
│   └── TROUBLESHOOTING.md      全部已知坑与解法
├── patches/                    OmniVoice 低显存训练补丁
└── examples/
    ├── dark_willow/            邪影芳灵完整实战记录
    └── deadlock_paige/         Paige 完整实战记录
```

---

## 踩过的坑（节选）

| 坑 | 解法 |
|---|---|
| `.vsnd_c` 前 4 字节小端 uint32 = MP3 起始偏移 | 剥离头部即得 MP3 |
| 英雄显示名 ≠ 内部代号（Paige = `bookworm`） | 扫 VPK 目录 / 读 `hero_presence_cache.json` |
| 台词不在 VPK 里（Deadlock） | 找磁盘未打包的 `resource/localization/` |
| `data_config.json` 的 `manifest_path` 写成 `file:///` | **必须是普通路径**（`os.path.isfile` 校验） |
| `data.lst` 的 tar 路径写普通路径 | **必须 `file:///D:/...`**（webdataset gopen） |
| 两个英雄并发跑 pipeline 互相覆盖 manifest | 按 `manifest_<hero>.json` 分开 + 自动合并 |
| Whisper 固定 30 秒窗口，逐条识别浪费 95% 算力 | 窗口打包 + 词级时间戳回切（**40× 提速**） |
| 窗口打包导致下一条开头粘到上一条末尾 | 单独重识别 + 按长度融合裁剪 |
| Whisper 在非语音上吐 YouTube 字幕模板 | 关键词表 + 重复检测，标注后剔除 |
| 专有名词同音错字（灰药/辉耀） | **拼音级**匹配，不是字符级 |
| 4 GB 显存 OOM | 逐层 CPU offload（内存当显存） |
| Windows 无 NCCL → FSDP 不可用 | 单进程 + 自研 offload |
| PEFT 键名带 `.default` 导致合并失效 | 用官方 `merge_lora` CLI |
| CER 虚高 | whisper 输出繁体 → CER 前 `zhconv` 转简体 |
| HF 上传 150 KB/s | 装 `hf_transfer`（**34 MB/s**） |
| 代理端口猜错连不上 HF | 从 Windows 注册表读 `ProxyServer` |

完整清单见 [references/TROUBLESHOOTING.md](references/TROUBLESHOOTING.md)。

---

## 适用边界

- **只适用于 Source 2 引擎的游戏**（Dota 2 / Deadlock / CS2 等），
  依赖 `.vsnd_c` 容器格式与 VPK 打包
- 中文台词靠 ASR 生成，**准确率不保证 100%**，必须人工/规则校对；
  走官方英文字幕路线则无此问题
- 本仓库脚本在 Dota 2 与 Deadlock 上验证；换游戏需重做阶段 0
  （英雄代号 + 台词来源 + token 规则）
- 训练数据 < 200 条时音色不稳定；> 5000 条需要更大显存

## 致谢

- [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) — TTS 基座
- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) — ASR
- [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice) — campplus 说话人验证
- Valve / Dota 2 / Deadlock — 语音资源与官方字幕

## 许可

本仓库的**脚本与文档**以 MIT 许可发布。
游戏语音资源的版权归 Valve / 各游戏发行商所有，请勿用于商业分发；
请遵守对应游戏的最终用户许可协议（EULA）。
