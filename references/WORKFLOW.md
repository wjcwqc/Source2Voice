# Source2Voice · 通用工作流（Source 2 引擎）

每阶段末尾都有 **✅ 验收项**，命令输出与验收项不符就别往下走。
所有路径都来自 `scripts/s2v_config.py`（环境变量驱动），命令里的
`<...>` 是占位符，请替换成实际路径。

## 已验证的游戏

| 游戏 | `S2V_GAME` | 资源根 | 语言包 | 台词来源 | 状态 |
|---|---|---|---|---|---|
| Dota 2 | `dota2` | `game/dota/` | `dota` + `dota_schinese` | VPK 内 `resource/subtitles/` | ✅ 全流程验证 |
| Deadlock | `deadlock` | `game/citadel/` | `citadel`（**仅英文**） | **磁盘未打包目录** `citadel_generated_vo/` | ✅ 全流程验证 |
| CS2 | `cs2` | `game/csgo/` | `csgo` + `csgo_schinese` | VPK 内 | ⚠️ 未验证 |

**关键差异**：Dota 2 官方**不给中文字幕**（中文要靠 ASR 生成，是全流程最贵的一环）；
Deadlock **只有英文**，但英文台词是官方本地化文件 → **完全不需要 ASR**，
流程从 10–14 小时缩到 6–7 小时。选游戏前先确认这一条。

---

```bash
# 全局一次性配置
export S2V_ROOT=D:/dwvits
export S2V_GAME=deadlock                                    # dota2 / deadlock / cs2
export S2V_GAME_DIR="D:/SteamLibrary/steamapps/common/Deadlock"
export S2V_DATASET_DIR=D:/Deadlock_VoiceDataset
export S2V_WHISPER_MODEL=D:/dwvits/models/faster-whisper-large-v3   # 仅 Dota 2 需要
python scripts/s2v_config.py    # 打印全部路径 + 存在性检查
```

---

## 阶段 0 · 定位资源（10 min）

### 0.1 找游戏目录

Windows Steam 默认：`C:\Program Files (x86)\Steam\steamapps\common\<游戏>`
或自定义库：`<库盘>\steamapps\common\<游戏>`

```bash
ls "$S2V_GAME_DIR/game" | head
```

### 0.2 找英雄内部代号 —— **最容易卡住的一步**

显示名 ≠ 内部代号。Dota 2 的「邪影芳灵」在资源里是 `dark_willow`，
音频文件名是 `helmet_sylph_*`；Deadlock 的「Paige」在资源里是 **`bookworm`**，
「Violet」是 **`artist`**。

**办法 A：扫 VPK 目录索引**（通用，最可靠）

```bash
python scripts/extract/extract.py '{"vpk":"<游戏>/game/<root>/pak01_dir.vpk",
  "prefixes":["sounds/vo/"],"exts":[".vsnd_c"],"out":"/tmp/vo_scan"}'
```

然后在 `/tmp/vo_scan/sounds/vo/` 下找英雄目录名。**每个英雄一个目录**，
名字就是内部代号。

**办法 B：读磁盘上的英雄缓存**（Deadlock 专用，秒出）

```bash
# Deadlock 的显示名↔内部代号映射在磁盘上，直接可读
python - <<'PY'
import json, glob
for p in glob.glob(r"<游戏>/game/citadel/**/hero_presence_cache.json", recursive=True):
    for k, v in json.load(open(p, encoding="utf-8")).items():
        print(k, "->", v)
PY
```

Deadlock 实测输出（节选）：

| 显示名 | 内部代号 |
|---|---|
| Paige | `bookworm` |
| Violet | `artist` |
| Billy | `punkgoat` |
| Infernus | `infernal` |
| Grey Talon | `shrouded` |

> ⚠️ 常见误判：Deadlock 的 Billy 内部代号是 `punkgoat`，不是 `billy`。
> **永远以资源目录名为准，不要按显示名猜。**

### 0.3 判断台词来源

```bash
# Dota 2：台词在 VPK 内
python scripts/extract/extract.py '{"vpk":"<游戏>/game/dota/pak01_dir.vpk",
  "prefixes":["resource/subtitles/"],"exts":[".txt"],"out":"/tmp/sub_scan"}'
ls /tmp/sub_scan/resource/subtitles/ | grep -i <hero>

# Deadlock：台词在磁盘未打包目录，VPK 里找不到
ls "<游戏>/game/citadel/resource/localization/citadel_generated_vo/"
# -> citadel_generated_vo_english.txt   (5.8 MB / 78453 行)
```

| 情况 | 处理 |
|---|---|
| VPK 内有 `subtitles_<hero>_english.txt` | `subtitle_sources: ["vpk:..."]` |
| 磁盘上有 `*_english.txt` 本地化文件 | `subtitle_sources: ["file:..."]` |
| 有中文台词文件 | 直接用，中文步骤整个跳过 |
| 只有英文 | **做英文即可**，跳过阶段 2 的 ASR |

**Deadlock 没有中文语音包**：`citadel_schinese/pak01_dir.vpk` 只有 50 条
panorama UI 资源，0 个 `.vsnd_c`。这不是配置问题，是游戏本身没做中文语音。

### 0.4 写英雄档案

复制 `configs/hero_deadlock_paige.json` 改成 `configs/hero_<game>_<name>.json`：

```json
{
  "game": "deadlock",
  "hero_key": "paige",
  "display_name": "Paige",
  "asset_code": "bookworm",
  "asset_prefixes": ["bookworm_"],
  "languages": ["english"],
  "vpk_overrides": {
    "english": "<游戏>/game/citadel/pak01_dir.vpk"
  },
  "subtitle_sources": [
    "file:<游戏>/game/citadel/resource/localization/citadel_generated_vo/citadel_generated_vo_english.txt"
  ],
  "groups": { "vo": "sounds/vo/bookworm/" },
  "token_rules": { "vo": ["{stem}_*"] },
  "token_priority": ["hero_3d", "ability_3d", "ult_3d", "zipline_3d", "ping_2d", "hero_announcer"]
}
```

### 0.5 `token_rules` 三种模板语法

| 模板 | 含义 | 适用 |
|---|---|---|
| `{stem}` | 完整文件名主干，如 `helmet_sylph_spawn_01` | Dota 2 精确命名 |
| `{rest_<资产前缀去下划线>}` | 去掉资产前缀后的主干，如 `spawn_01` | Dota 2 旧命名表 |
| `{stem}_*` | **前缀通配**：匹配所有以该前缀开头的 token | Deadlock |

`token_priority` 是**同一 stem 匹配到多个 token 时**的排序依据
（Deadlock 的 `bookworm_spawn_01_hero_3d` 与 `bookworm_spawn_01_ability_3d` 并存）。

> 举例（Dota 2）：音频 `sylph_ability1_01.wav` → token `dark_willow_sylph_ability1_01`
> → 规则 `dark_willow_{stem}`。旧的 `sylph_sylph_*` 命名表是 `sylph_sylph_{rest_sylph}`。
>
> 举例（Deadlock）：音频 `bookworm_spawn_01.vsnd_c` → token `bookworm_spawn_01_hero_3d`
> → 规则 `{stem}_*`。

**✅ 验收**：`scripts/extract/pipeline.py` 跑完后，
`[lang/group] N clips, M matched subtitle` 里 **M/N > 0.95**。
实测 Paige 1547/1615（95.8%）、Violet 2033/2111（96.3%）——未匹配项均为纯音效。

---

## 阶段 1 · 提取音频（5 min）

```bash
python scripts/extract/pipeline.py \
    --hero configs/hero_deadlock_paige.json \
    --out  "$S2V_DATASET_DIR"
```

产出：
```
$DATASET_DIR/
├── english/<hero>/<group>/   *.wav  32kHz/16bit/mono
├── raw_mp3/                 原始 MP3（可溯源/换采样率）
└── metadata/
    ├── manifest_<hero>.json  每个英雄一份
    └── manifest.json         自动合并去重（hero_key+language+group+filename）
```

> **多英雄并行注意**：两个英雄同时跑 pipeline 会互相覆盖 manifest。
> 现在按 `manifest_<hero_key>.json` 分开存储 + 自动合并，可以安全并行。

### 1.1 `.vsnd_c` 容器格式（Dota 2 与 Deadlock 实测一致）

前 4 字节小端 uint32 = MP3 流起始偏移，偏移处必须是 `0xFF`（MP3 帧同步字）。
剥离头部即得裸 MP3。

### 1.2 生成 CSV 与 .list 清单

```bash
python scripts/extract/make_outputs.py --root "$S2V_DATASET_DIR" \
    --hero paige --speaker paige
```

产出 `metadata/<lang>_<hero>_<group>.list`（GPT-SoVITS 格式 `wav|speaker|lang|text`）
和 CSV（含 `hero` / `text` / `language` / `duration` / `token` 列）。

**✅ 验收**
1. `manifest.json` 条数 = 各英雄之和
2. 随机抽 3 个 wav 用播放器听：**是语音不是噪音**
3. `raw_mp3/` 与 manifest 的 mp3 字段一一对应

---

## 阶段 2 · 台词文本（分两种路径）

### 路径 A：官方字幕直接可用（Dota 2 英文 / Deadlock 全语言）

台词已在 manifest 里（官方字幕 token 精确匹配），**无需 ASR**。

**✅ 验收**：直接进阶段 3。

### 路径 B：需要 ASR 生成（Dota 2 中文）

> ⚠️ 只有 Dota 2 中文需要这一步。Deadlock 用户可整段跳过。

**核心难点**：Valve 不提供中文字幕，中文文本要靠 ASR 生成。

**提速关键**：Whisper 固定编码 30 秒窗口，逐条识别 1–3 秒短句浪费 ~95% 算力。
把短句按 ~28 秒打包成窗口 + `word_timestamps=True` + 按词中点回切，
int8 CPU 速度从 0.16x 提到 **4.25x 实时**。

```bash
# 窗口打包版（主力，快）
python scripts/asr/asr_zh_windows.py \
    --root "$S2V_DATASET_DIR" --model "$S2V_WHISPER_MODEL" --group vo
```

或拼接版：
```bash
python scripts/asr/asr_zh_concat.py --root "$S2V_DATASET_DIR" --model "$S2V_WHISPER_MODEL"
```

两者都会把结果缓存到 `metadata/asr_cache.json`（键 = 去掉扩展名的文件名），**可随时中断重跑**。

> ⚠️ 直接把所有短句拼成一个大文件会被 VAD 合并成单段，无法切分。
> 必须用「1 秒静音间隔」让 VAD 正确切分。

**✅ 验收**：`asr_cache.json` 中非空条目数 / 应识别总数 > 0.95。

### 2.1 边界粘连修正（路径 B 必做）

窗口打包会把**下一条的开头粘到上一条末尾**（Whisper 中文"词"是多字块，
跨边界时整个划给一侧）。实测 2400 条里约 732 条受影响。

修法：把可疑条目**单独再识别一次**（无邻居可粘），单独识别的**长度可信**
但字词会退化（large-v3 漂成繁体），于是只取它的长度去裁剪窗口版文本。

```bash
python scripts/asr/asr_refine.py --root "$S2V_DATASET_DIR" --model "$S2V_WHISPER_MODEL"
python scripts/asr/asr_tail_merge.py --selftest
python scripts/asr/asr_tail_merge.py --apply
```

融合规则（`asr_tail_merge.py` 里的 `core()` 忽略标点后比较）：
- `len(core(iso)) >= len(core(old))` → 保留窗口版
- 前缀对齐（相同前缀 ≥ 2 字）→ 按单独识别的字数裁剪窗口版
- 前缀不一致 → 判定为「开头被拉走」→ 用单独识别结果

### 2.2 幻觉与非语言条目（路径 B 必做）

两类问题**不是"改文本"能解决的**：
1. **幻觉**：非语音音频上 Whisper 吐出 YouTube 字幕模板
   （`优优独播剧场` / `请不吝点赞` / `明镜与点点栏目`）
2. **非语言**：喊声/笑声/惨叫（英文行是 `Ugh!` / `Hahahaha!`），
   Whisper 会硬产出一串拟声字 —— 作为「文本→语音」训练对是**有害**的

```bash
python scripts/asr/mark_nonverbal.py --root "$S2V_DATASET_DIR"
```

> 重复检测规则有个关键细节：`(.{1,3})\1{5,}` 重复 ≥6 次 **且** 该行英文
> 不是纯喊声时才判幻觉。否则真笑声「哈哈哈哈」会被误杀。

### 2.3 专有名词修正（路径 B）

用英文官方台词 + 官方译名表做**拼音级**匹配（不比较字符）：

```bash
python scripts/asr/asr_names.py --report     # 先看建议，不改
python scripts/asr/asr_names.py --apply      # 确认后写入
```

> 为什么用拼音：这类错误是**同音**错误。「灰药/辉耀」「杯梅城/悲玫城」
> 逐字完全不同但读音一致，字符级匹配完全无效。

### 2.4 合并 + 重新生成 .list

```bash
python scripts/asr/merge_asr.py --root "$S2V_DATASET_DIR"
python scripts/extract/make_outputs.py --root "$S2V_DATASET_DIR" --hero <hero> --speaker <hero>
```

**✅ 验收**
1. `asr_cache.json` 覆盖率 > 0.95
2. `nonverbal.json` 里标注的条目**不在**训练清单里
3. 随机抽 10 条中文文本，与对应英文台词语义一致

---

## 阶段 3 · 数据清洗与分桶（20 min）

### 3.1 台词质量体检

```bash
python scripts/clean/inspect_dataset.py --root "$S2V_DATASET_DIR"
```

检查：空文本 / 纯符号 / 重复台词 / 超短文本 / CJK 混入 / 非 ASCII 标点。

> Deadlock 实测：Paige 1524 唯一台词 / 23 句重复 / 0 超短 / 0 CJK 混入；
> Violet 2009 唯一 / 20 句重复 / 0 超短 / 0 CJK。
> **官方字幕质量优秀，无需人工修正** —— 这是选「做英文即可」的最大收益。

### 3.2 挑选训练子集

通常只用**英雄游戏内语音**（`vo`），播音包单独训练/评估：

```bash
python scripts/clean/filter_by_list.py \
    --csv  "$S2V_DATASET_DIR/metadata/dataset.csv" \
    --list "$S2V_DATASET_DIR/metadata/<lang>_<hero>_vo_pure.list" \
    --out  "$S2V_DATASET_DIR/metadata/dataset.csv"
```

### 3.3 响度与质量分桶

```bash
python scripts/clean/refine_dataset.py \
    --input "$S2V_DATASET_DIR/metadata/<lang>_<hero>_vo_pure.list" \
    --out   "$S2V_WORK/clean_dataset" \
    --speaker <hero> --langs en
```

产出 `report.csv`，分三桶：
| 桶 | 含义 | 用途 |
|---|---|---|
| `core` | 干净标准 | **先训音色** |
| `style` | 语气夸张/重复 | 后续语气增强候选 |
| `review` | 声学离群 | 需人工听审 |

> 响度离群判断**必须按来源分组做**（播音包与英雄语音母带增益不同，
> 全局阈值会整包误杀）。

### 3.4 转成训练清单

`refine_dataset.py` 产出的是 Kaldi 桶格式，训练侧要 GPT-SoVITS `.list`：

```bash
python scripts/clean/bucket_to_list.py \
    --root "$S2V_WORK/clean_dataset" --speaker <hero> --lang en
```

**✅ 验收**
1. 清单条目数 > 0 且每行 4 段（`wav|speaker|lang|text`）
2. 每条的 wav 文件都存在（脚本会校验）
3. 文本里没有繁体、没有 YouTube 模板

---

## 阶段 4 · 训练数据准备（15 min）

### 4.1 生成 JSONL 并划分

```bash
python scripts/train/prep_omnivoice_data.py \
    --list "$S2V_WORK/clean_dataset/core.list" \
    --out_dir "$S2V_WORK/data/omnivoice_<hero>" \
    --dev_count 20
```

划分是**确定性**的（seed=42 洗牌后取前 20 条做 dev），重跑结果一致。
`language_id` 会自动归一成 OmniVoice 的 `LANG_IDS`（`en` / `zh` / ...）。

### 4.2 Audio tokenize + 生成 data_config

```bash
python scripts/train/make_data_config.py \
    --data_dir "$S2V_WORK/data/omnivoice_<hero>"
```

这一步会：
1. 调 `tokenize_single.py` 把 JSONL 转成 WebDataset shards（24 kHz 音频 token）
2. 生成 `data_config.json`
3. **规范化 data.lst 的 tar 路径为 `file:///D:/...`**

> ⚠️ **路径前缀的两种形态不能互换**（踩过，训练直接起不来）：
>
> | 位置 | 形态 | 原因 |
> |---|---|---|
> | `data_config.json` 的 `manifest_path` | **普通绝对路径** `D:\...\data.lst` | `os.path.isfile()` 校验 |
> | `data.lst` **内部**的 tar 路径 | **`file:///D:/...`** | webdataset gopen 解析 URL |
> | `data.lst` **内部**的 jsonl 路径 | **普通绝对路径** | `LabelDataset` 用 `open()` 读 |
>
> 写反了会报 `AssertionError: file:///D:/... is not a file.`

**✅ 验收**
1. `tokens/train/audios/*.tar` 与 `tokens/train/txts/*.jsonl` 数量匹配
2. `data_config.json` 的 `manifest_path` **不以** `file:///` 开头
3. `data.lst` 第一列 **以** `file:///` 开头

### 4.3 Smoke test（必做，5 min）

把 `configs/train_config_lora.json` 的 `steps` 改成 `20`，另存为
`configs/train_config_smoke.json`，然后：

```bash
bash scripts/train/run_train.sh configs/train_config_smoke.json \
    "$S2V_WORK/data/omnivoice_<hero>/data_config.json"
```

**✅ 验收**：20 步跑完不 OOM、loss 在下降、显存没打满。

---

## 阶段 5 · LoRA 微调（5–6 h）

### 5.1 打补丁（低显存必做）

```bash
cd <OmniVoice 源码目录>
git apply /path/to/Source2Voice/patches/omnivoice_cpu_offload.patch
```

venv 内的 3 处 Windows 库补丁见 `patches/README.md`。

### 5.2 起训

```bash
export S2V_DATA="$S2V_WORK/data/omnivoice_<hero>"
export S2V_EXP="$S2V_WORK/exp/omnivoice_<hero>_lora"
bash scripts/train/run_train.sh \
    "$REPO/configs/train_config_lora.json" \
    "$S2V_DATA/data_config.json"
```

### 5.3 关键超参

| 参数 | 值 | 说明 |
|---|---|---|
| `use_lora` / `lora_r` / `lora_alpha` | true / 16 / 32 | 可训练参数 4.2% |
| `learning_rate` | 1e-4 | |
| `steps` | 600 | 900–1300 条数据 ≈ 60–70 epoch |
| `batch_tokens` × `gradient_accumulation_steps` | 1024 × 8 | ≈ 8192 tokens/步 |
| `mixed_precision` | bf16 | |
| `attn_implementation` | sdpa | 省显存 |
| `num_workers` | 0 | Windows 多进程 spawn 会炸 |
| `save_steps` / `eval_steps` | 150 | 存 300/450/600 |
| `OMNIVOICE_CPU_OFFLOAD` | 1 | **核心**：内存当显存 |

**✅ 验收**：
- 600 步跑完，final loss 从 ~4.5 降到 ~3.9
- `checkpoint-300/450/600` 都在
- 单步耗时稳定（4GB 卡约 28s/步）

---

## 阶段 6 · 评估 + 合并 + 发布（1 h）

### 6.1 推理冒烟测试

```bash
python scripts/eval/test_infer.py \
    --lora_adapter "$S2V_WORK/exp/omnivoice_<hero>_lora/checkpoint-600"
```

每条留出文本生成两次：ref（带参考音频）/ noref（纯文本）。
**noref 能出对音色 = 音色已内化进模型参数**。

### 6.2 量化评估

```bash
python scripts/eval/eval_omnivoice.py
```

| 指标 | 含义 | 判据 |
|---|---|---|
| CER ↓ | whisper 转写后与目标文本的字符错误率 | < 0.07 算可用 |
| spk-sim ↑ | campplus 嵌入与真人留出片段的余弦相似度 | **超过真人基线** |

> 相似度要看基线，不是看绝对值。生成相似度 0.66 可能是「学好了」也可能是
> 「大家听起来都像」—— 只有和真人互相相似度比才有意义。

**英文数据集注意**：CER 对英文同样适用，但**不要做繁转简**
（`zhconv` 是中文专用），英文侧只需统一标点与大小写归一。

### 6.3 合并 LoRA → 独立模型

**优先用官方工具**（键名带 `.default`，手写极易漏）：

```bash
python -m omnivoice.cli.merge_lora \
    --base_model "$S2V_MODEL" \
    --adapter "$S2V_WORK/exp/omnivoice_<hero>_lora/checkpoint-600" \
    --output "$S2V_WORK/exp/omnivoice_<hero>_merged"
```

备用（本仓库 `scripts/train/merge_lora.py`）：
```bash
python scripts/train/merge_lora.py \
    --checkpoint "$S2V_WORK/exp/omnivoice_<hero>_lora/checkpoint-600" \
    --output    "$S2V_WORK/exp/omnivoice_<hero>_merged"
```

### 6.4 部署（可选）

```bash
python scripts/publish/omnivoice_server.py --model "$S2V_WORK/exp/omnivoice_<hero>_merged"
```

提供 `/health`、`/tts`、`/tts_file` 三个端点。

### 6.5 上传 HuggingFace

先在本地整理暂存目录：
```
<stage>/model/
  merged/          合并模型 + audio_tokenizer + tokenizer + config
  lora/            adapter_config.json + adapter_model.safetensors
  training/        训练配置 + 数据准备脚本 + train.log
  README.md        模型卡
<stage>/dataset/
  audio/           全部 wav
  metadata/        .list + train/dev jsonl
  README.md
```

然后：

```bash
pip install hf_transfer huggingface_hub
export HF_TOKEN=hf_xxx
python scripts/publish/upload_hf.py \
    --model_repo   <user>/<VoiceName> \
    --model_dir   <stage>/model \
    --dataset_repo <user>/<VoiceName>-dataset \
    --dataset_dir <stage>/dataset
```

脚本会**自动探测 Windows 系统代理**（读注册表 `ProxyServer`），
不用手写端口。也可以 `--proxy http://127.0.0.1:xxxx` 显式指定。

**✅ 验收**：
1. 两个仓库都能打开，文件数正确
2. 反向下载验证：`hf_hub_download(..., local_dir=...)` 拉一个文件下来

> ⚠️ Windows 下 `hf_hub_download` 的默认缓存会因软链接建不出来而报
> FileNotFoundError —— **加 `local_dir=` 参数**即可，仓库本身没问题。

---

## 阶段 7 · 记录

把训练配置、loss 曲线、评估表、生成样本清单写成 REPORT.md / MANIFEST.md，
一起放进 HF 仓库。参考 `examples/dark_willow/REPORT.md` 与
`examples/deadlock_paige/REPORT.md`。
