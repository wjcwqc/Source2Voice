---
name: source2voice
description: 从 Source 2 游戏（Dota 2 / Deadlock / CS2 等）的 VPK 资源包提取英雄语音，剥离 .vsnd_c 容器转 MP3/WAV，用官方字幕对齐台词（缺失语言才用 Whisper ASR 生成并做边界/术语修正），清洗成可训练数据集，最后用 OmniVoice LoRA 微调音色、量化评估（CER + 说话人相似度）、导出合并模型并上传 HuggingFace。当用户要求「提取游戏英雄语音做 TTS 音色」「用游戏语音微调 TTS 模型」「把 Dota 2 / Deadlock 语音做成训练集」「复现 Source2Voice 流程」时使用本技能。
agent_created: true
---

# Source2Voice：游戏语音 → 音色 TTS 全流程

从「本机装好了 Source 2 游戏」到「HuggingFace 上有一个能用的英雄音色模型」，
一条端到端可复现的流水线。**六个阶段，每阶段有验收项**。

本技能不是「写代码示范」，而是**已跑通并验证过**的流程：
Dota 2 邪影芳灵（中文）与 Deadlock Paige / Violet（英文）两个完整实例，
所有脚本在本机真实数据上跑过，输出数字在 references/REQUIREMENTS.md 里可查。

## 适用场景

- 「帮我把 XX 英雄的游戏语音提取出来做 TTS 音色」
- 「Valve 没出中文字幕，怎么给中文语音配台词」
- 「低显存显卡（4GB）怎么微调 0.6B 的 TTS 模型」
- 「微调完了怎么量化评估效果」
- 「把训练过程和数据集一起传到 HuggingFace」

## 六个阶段

| 阶段 | 内容 | 脚本 | 关键产出 | 参考耗时 |
|---|---|---|---|---|
| 0 | **定位资源**：找游戏目录、英雄内部代号、台词文件、VPK 布局 | — | 英雄档案 JSON | 10 min |
| 1 | **提取音频**：解 VPK → 剥 `.vsnd_c` → MP3 → WAV | `scripts/extract/` | `<lang>/<hero>/*.wav` + `manifest.json` | 5 min |
| 2 | **台词对齐**：官方字幕直用 / 缺失语言走 ASR | `scripts/asr/` | `asr_cache.json` + `.list` 清单 | **0 或 2–4 h** |
| 3 | **数据清洗**：体检、文本纠错、响度分桶 | `scripts/clean/` | 精修 `.list` + `report.csv` | 20 min |
| 4 | **训练数据准备**：JSONL 划分 + audio tokenize + data_config | `scripts/train/` | `train.jsonl` / `dev.jsonl` / `data.lst` | 15 min |
| 5 | **LoRA 微调**：OmniVoice 0.6B，4GB 显存可跑 | `scripts/train/run_train.sh` | `checkpoint-300/450/600` | **5–6 h** |
| 6 | **评估 + 发布**：CER/相似度评估 → 合并 LoRA → 传 HF | `scripts/eval/` `scripts/publish/` | 合并模型 + HF 仓库 | 1 h |

**总耗时**：Dota 2 中文约 10–14 h（70% 在 ASR 与训练）；Deadlock 英文约 6–7 h（无 ASR）。

## 铁律（违反必踩坑）

1. **`.vsnd_c` 前 4 字节小端 uint32 = MP3 流起始偏移**，剥离头部即得 MP3。
   偏移处必须是 `0xFF`（MP3 帧同步字），否则说明这个英雄的资源格式不同。
2. **显示名 ≠ 内部代号**。Dota 2「邪影芳灵」= `dark_willow`；
   Deadlock「Paige」= **`bookworm`**、「Violet」= **`artist`**、「Billy」= `punkgoat`。
   **永远扫 VPK 目录或读 `hero_presence_cache.json` 确认，不要按显示名猜。**
3. **台词来源可能不在 VPK 里**。Deadlock 的台词在磁盘未打包目录
   `game/citadel/resource/localization/citadel_generated_vo/`。
   `subtitle_sources` 用 `vpk:` / `file:` / `inline:` 三种前缀区分。
4. **先确认有没有官方字幕**。有官方英文字幕就**不要跑 ASR** ——
   省掉 2–4 小时且文本质量完美（实测 0 CJK 混入、0 超短句）。
5. **Valve 通常不给中文字幕**。Dota 2 中文只能靠 Whisper 生成，
   这是该路径最耗时的一环，别指望有捷径。
6. **Whisper 固定编码 30 秒窗口**，逐条识别 1–3 秒短句会浪费 ~95% 算力。
   必须用「窗口打包 + 词级时间戳回切」，否则 2400 条要跑一天。
7. **窗口打包会引入边界粘连**（下一条开头粘到上一条末尾）。
   必须做「单独识别 + 融合裁剪」修正，否则中文文本全是脏数据。
8. **Whisper 幻觉**：非语音音频上会吐出 YouTube 字幕模板（「优优独播剧场」等）。
   必须用关键词表 + 重复检测过滤，并把这些条目从训练清单剔除。
9. **路径前缀的两种形态不能互换**：
   - `data_config.json` 的 `manifest_path` = **普通绝对路径**
     （`os.path.isfile()` 校验，写 `file:///` 直接报 `AssertionError`）
   - `data.lst` **内部**的 tar 路径 = **`file:///D:/...`**（webdataset gopen）
   - `data.lst` **内部**的 jsonl 路径 = **普通绝对路径**（`open()` 读）
10. **PEFT state dict 键名是 `.lora_A.default.weight`（带 `.default`）**。
    手写合并脚本极易漏；直接用 `python -m omnivoice.cli.merge_lora` 最稳。
11. **CER 计算前必须繁转简**（whisper 会输出繁体），用 `zhconv` 转 `zh-hans`。
    英文侧不做这步，只需统一标点与大小写。
12. **相似度要看真人基线**。生成音频与真人的余弦相似度，只有超过
    「真人片段互相之间的相似度」才算真学到了（本项目邪影芳灵基线 0.644）。
13. **HF 上传必须装 `hf_transfer`**：不开只有 ~150KB/s（3GB 要 4.5 小时），
    开了 30+MB/s。**代理要从 Windows 注册表读**，别手写端口号。
14. **多英雄并行跑 pipeline 会互相覆盖 manifest**。已修为按
    `manifest_<hero_key>.json` 分开存储 + 自动合并去重。

## 目录结构

```
Source2Voice/
├── SKILL.md                  本文件：技能入口
├── README.md                 GitHub 首页
├── configs/
│   ├── hero_dark_willow.json    英雄档案（Dota 2 邪影芳灵）
│   ├── hero_deadlock_paige.json 英雄档案（Deadlock Paige）
│   ├── hero_deadlock_violet.json 英雄档案（Deadlock Violet）
│   ├── train_config_lora.json LoRA 训练配置
│   └── data_config.json       训练数据清单
├── scripts/
│   ├── s2v_config.py         全局路径配置 + GAME_REGISTRY 多游戏注册表
│   ├── extract/              阶段 1
│   ├── asr/                  阶段 2
│   ├── clean/                阶段 3
│   ├── train/                阶段 4-5
│   ├── eval/                 阶段 6
│   └── publish/              阶段 7
├── references/
│   ├── WORKFLOW.md           通用工作流 + 各游戏差异
│   ├── REQUIREMENTS.md       硬件/时间/算力要求（实测）
│   └── TROUBLESHOOTING.md    全部已知坑与解法
├── patches/                  OmniVoice 低显存训练补丁
└── examples/
    ├── dark_willow/          邪影芳灵完整实战记录（REPORT.md）
    └── deadlock_paige/       Paige 完整实战记录
```

## 快速开始

```bash
# 1. 配好路径（一次性的事）
export S2V_ROOT=/path/to/work
export S2V_GAME=deadlock          # dota2 / deadlock / cs2
export S2V_GAME_DIR="/path/to/Steam/steamapps/common/Deadlock"
export S2V_DATASET_DIR=/path/to/Hero_VoiceDataset
python scripts/s2v_config.py       # 打印所有路径 + 检查项

# 2. 按 references/WORKFLOW.md 走六个阶段
```

## AI 执行指引

如果你是在 WorkBuddy / Claude Code 里跑这个技能：

- **先读 `references/WORKFLOW.md`**，里面有每阶段的完整命令和验收标准。
- **先做阶段 0 的台词来源确认**，这一步决定要不要跑 ASR（能省 2–4 小时）。
- **每阶段结束必须验收入口**：命令行有明确输出行数/条数，对不上就别进下一阶段。
- **换英雄时**：`configs/hero_<game>_<name>.json` 是唯一要改的入口；
  `token_rules` 用模板描述字幕 token 的命名规则
  （`{stem}` / `{rest_<前缀>}` / `{stem}_*` 通配），
  `token_priority` 决定同一 stem 匹配到多个 token 时选哪个。
- **不要跳过阶段 3 的体检**。文本脏了，模型学到的就是脏发音，后面所有阶段都白做。
- **训练前先跑 `--steps 20` 的 smoke test**，确认 offload 通路正常再上完整配置。
- **一个 GPU 只能同时训一个音色**。多英雄排队，不要并发。
