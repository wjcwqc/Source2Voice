# Source2Voice · 六阶段详细工作流

每阶段末尾都有 **✅ 验收项**，命令输出与验收项不符就别往下走。
所有路径都来自 `scripts/s2v_config.py`（环境变量驱动），命令里的
`<...>` 是占位符，请替换成实际路径。

```bash
# 全局一次性配置
export S2V_ROOT=D:/dwvits
export S2V_GAME_DIR="D:/SteamLibrary/steamapps/common/dota 2 beta"
export S2V_DATASET_DIR=D:/DarkWillow_VoiceDataset
export S2V_WHISPER_MODEL=D:/dwvits/models/faster-whisper-large-v3
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

### 0.2 找英雄内部代号

**这是最容易卡住的一步**。显示名「邪影芳灵」在资源里是 `dark_willow`，
音频文件名是 `helmet_sylph_*` / `sylph_*`，字幕 token 又是另一套。
最可靠的办法是**先扫 VPK 目录索引**：

```bash
python scripts/extract/extract.py '{"vpk":"<游戏>/game/dota/pak01_dir.vpk",
  "prefixes":["sounds/vo/"],"exts":[".vsnd_c"],"out":"/tmp/vo_scan"}'
```

然后在 `/tmp/vo_scan/sounds/vo/` 下找英雄目录名。**每个英雄一个目录**，
名字就是内部代号。找到后：

```bash
# 该英雄的所有资源 + 相关字幕
python scripts/extract/extract.py '{"vpk":"<游戏>/game/dota/pak01_dir.vpk",
  "prefixes":["sounds/vo/dark_willow/","resource/subtitles/"],
  "exts":[".vsnd_c",".txt"],"out":"/tmp/dw_scan"}'
```

### 0.3 判断有没有字幕

```bash
# 列出所有字幕文件
ls /tmp/dw_scan/resource/subtitles/ | grep -i dark_willow
```

- 有 `subtitles_<hero>_english.txt` → 英文台词有官方来源（token 精确匹配）
- **中文通常没有** → 阶段 2 要用 ASR 生成
- 部分英雄有 `hero_chat_wheel_<lang>.txt`（聊天轮盘），是**少量**官方中文

### 0.4 写英雄档案

复制 `configs/hero_dark_willow.json` 改成 `configs/hero_<name>.json`，改 4 处：

```json
{
  "hero_key": "<内部代号>",
  "asset_prefixes": ["<音频文件前缀>_", ...],
  "groups": { "<组名>": "sounds/vo/<组路径>/", ... },
  "subtitle_files": ["resource/subtitles/subtitles_<hero>_english.txt", ...],
  "token_rules": { "<组名>": ["<前缀>{stem}", ...], ... }
}
```

`token_rules` 是模板列表，按顺序取第一个在字幕表命中的候选：
- `{stem}` = 完整文件名主干，如 `helmet_sylph_spawn_01`
- `{rest_<资产前缀去掉下划线>}` = 去掉该资产前缀后的主干，如 `spawn_01`

> 举例（邪影芳灵）：音频 `sylph_ability1_01.wav` → token `dark_willow_sylph_ability1_01`
> → 规则 `dark_willow_{stem}`。旧的 `sylph_sylph_*` 命名表是
> `sylph_sylph_{rest_sylph}`。

**✅ 验收**：`scripts/extract/pipeline.py` 跑完后，
`[lang/group] N clips, M matched subtitle` 里 **M == N**（或 M/N > 0.95）。

---

## 阶段 1 · 提取音频（5 min）

```bash
python scripts/extract/pipeline.py \
    --hero configs/hero_dark_willow.json \
    --out  "$S2V_DATASET_DIR"
```

产出：
```
$DATASET_DIR/
├── english/dark_willow/{vo,announcer}/   *.wav  32kHz/16bit/mono
├── schinese/dark_willow/{vo,announcer}/   *.wav
├── raw_mp3/                                原始 MP3（可溯源/换采样率）
└── metadata/manifest.json                  token/text/path 三元组
```

**✅ 验收**
1. `manifest.json` 条数 = 英文 + 中文之和
2. 随机抽 3 个 wav 用播放器听：**是语音不是噪音**
3. `raw_mp3/` 与 `metadata/manifest.json` 的 mp3 字段一一对应

### 1.2 生成 CSV 与 .list 清单

```bash
python scripts/extract/make_outputs.py --root "$S2V_DATASET_DIR"
```

产出 `metadata/darkwillow_dataset.csv`（含 text/language/duration/token 列）
和 `<lang>_dark_willow_<group>.list`（GPT-SoVITS 格式 `wav|speaker|lang|text`）。

### 1.3 术语表（可选但强烈建议）

从游戏本地化文件里扒官方译名，供阶段 2 修正专有名词：

```bash
python scripts/extract/build_names.py
```

**✅ 验收**：`manifest.json` 中 `text` 非空率 ≥ 90%（英文应 100%）。

---

## 阶段 2 · 中英分离 + 中文 ASR（2–4 h，最耗时）

### 2.1 英文（免费）

英文台词已经在 manifest 里（官方字幕 token 精确匹配），无需 ASR。

### 2.2 中文（Whisper）

**核心难点**：Valve 不提供中文字幕，中文文本要靠 ASR 生成。

**提速关键**：Whisper 固定编码 30 秒窗口，逐条识别 1–3 秒短句浪费 ~95% 算力。
把短句按 ~28 秒打包成窗口 + `word_timestamps=True` + 按词中点回切，
int8 CPU 速度从 0.16x 提到 **4.25x 实时**。

```bash
# 窗口打包版（主力，快）
python scripts/asr/asr_zh_windows.py \
    --root "$S2V_DATASET_DIR" \
    --model "$S2V_WHISPER_MODEL" \
    --group vo
```

或拼接版：
```bash
python scripts/asr/asr_zh_concat.py --root "$S2V_DATASET_DIR" --model "$S2V_WHISPER_MODEL"
```

两者都会把结果缓存到 `metadata/asr_cache.json`（键 = 去掉扩展名的文件名），
**可随时中断重跑**。

> ⚠️ 直接把所有短句拼成一个大文件会被 VAD 合并成单段，无法切分。
> 必须用「1 秒静音间隔」让 VAD 正确切分。

**✅ 验收**：`asr_cache.json` 中非空条目数 / 应识别总数 > 0.95。

### 2.3 边界粘连修正（必做）

窗口打包会把**下一条的开头粘到上一条末尾**（Whisper 中文"词"是多字块，
跨边界时整个划给一侧）。实测 2400 条里约 732 条受影响。

修法：把可疑条目**单独再识别一次**（无邻居可粘），单独识别的**长度可信**
但字词会退化（large-v3 漂成繁体），于是只取它的长度去裁剪窗口版文本。

```bash
# 1) 标记并单独识别可疑条目
python scripts/asr/asr_refine.py --root "$S2V_DATASET_DIR" --model "$S2V_WHISPER_MODEL"

# 2) 融合裁剪 + 术语修正（先自测！）
python scripts/asr/asr_tail_merge.py --selftest
python scripts/asr/asr_tail_merge.py --apply
```

融合规则（`asr_tail_merge.py` 里的 `core()` 忽略标点后比较）：
- `len(core(iso)) >= len(core(old))` → 保留窗口版
- 前缀对齐（相同前缀 ≥ 2 字）→ 按单独识别的字数裁剪窗口版
- 前缀不一致 → 判定为「开头被拉走」→ 用单独识别结果

**✅ 验收**：
```bash
python scripts/asr/verify_zh.py --root "$S2V_DATASET_DIR"
```
剩余截断数、繁体残留数、被裁空条目数都应为 0 或极小。

### 2.4 幻觉与非语言条目（必做）

两类问题**不是"改文本"能解决的**：
1. **幻觉**：非语音音频上 Whisper 吐出 YouTube 字幕模板
   （`优优独播剧场` / `请不吝点赞` / `明镜与点点栏目`）
2. **非语言**：喊声/笑声/惨叫（英文行是 `Ugh!` / `Hahahaha!`），
   Whisper 会硬产出一串拟声字 —— 作为「文本→语音」训练对是**有害**的

```bash
python scripts/asr/mark_nonverbal.py --root "$S2V_DATASET_DIR"
```

产出 `metadata/nonverbal.json`（标注原因），并清空幻觉条目的文本。

> 重复检测规则有个关键细节：`(.{1,3})\1{5,}` 重复 ≥6 次 **且** 该行英文
> 不是纯喊声时才判幻觉。否则真笑声「哈哈哈哈」会被误杀。

### 2.5 专有名词修正

用英文官方台词 + 官方译名表做**拼音级**匹配（不比较字符）：

```bash
python scripts/asr/asr_names.py --report     # 先看建议，不改
python scripts/asr/asr_names.py --apply      # 确认后写入
```

> 为什么用拼音：这类错误是**同音**错误。「灰药/辉耀」「杯梅城/悲玫城」
> 逐字完全不同但读音一致，字符级匹配完全无效。

### 2.6 合并 + 生成 .list

```bash
python scripts/asr/merge_asr.py --root "$S2V_DATASET_DIR"
python scripts/extract/make_outputs.py --root "$S2V_DATASET_DIR"
```

**✅ 验收**：
1. `asr_cache.json` 覆盖率 > 0.95
2. `nonverbal.json` 里标注的条目**不在**训练清单里
3. 随机抽 10 条中文文本，与对应英文台词语义一致

---

## 阶段 3 · 数据清洗（1–2 h）

### 3.1 挑选训练子集

通常只用**英雄游戏内语音**（`vo`），播音包单独训练/评估：

```bash
python scripts/clean/filter_by_list.py \
    --csv  "$S2V_DATASET_DIR/metadata/darkwillow_dataset_new.csv" \
    --list "$S2V_DATASET_DIR/metadata/<lang>_<hero>_vo_pure.list" \
    --out  "$S2V_DATASET_DIR/metadata/dataset.csv"
```

### 3.2 人工/规则纠错

```bash
# 只读体检：专有名词残留 / 繁体 / 幻觉 / 异常
python scripts/asr/full_check.py

# 逐条修正（示例脚本，按实际错误改 FIXES 字典）
python scripts/clean/jingjiao_vo_pure.py
```

修正要**可确证**：官方译文对齐 / 官方术语表 / 同音错字 / 语法标点。
**不要重译**。

### 3.3 响度与质量分桶

```bash
python scripts/clean/refine_dataset.py \
    --input "$S2V_DATASET_DIR/metadata/<lang>_<hero>_vo_pure.list" \
    --out   "$S2V_WORK/clean_dataset"
```

产出 `report.csv`，分三桶：
| 桶 | 含义 | 用途 |
|---|---|---|
| `core` | 干净标准 | **先训音色** |
| `style` | 语气夸张/重复 | 后续语气增强候选 |
| `review` | 声学离群 | 需人工听审 |

> 响度离群判断**必须按来源分组做**（播音包与英雄语音母带增益不同，
> 全局阈值会整包误杀）。

### 3.4 精修清单定稿

最终交给阶段 4 的是**精修后的 `.list`**：

```
$DATASET_DIR/metadata/schinese_dark_willow_vo_pure.list
```

**✅ 验收**
1. 清单条目数 > 0 且每行 4 段（`wav|speaker|lang|text`）
2. 每条的 wav 文件都存在（脚本会校验）
3. `full_check.py` 体检 0 残留
4. 文本里没有繁体、没有 YouTube 模板

---

## 阶段 4 · 训练数据准备（15 min）

### 4.1 生成 JSONL 并划分

```bash
python scripts/train/prep_omnivoice_data.py \
    --list "$S2V_DATASET_DIR/metadata/<lang>_<hero>_vo_pure.list" \
    --out_dir "$S2V_WORK/data/omnivoice_<hero>" \
    --dev_count 20
```

划分是**确定性**的（seed=42 洗牌后取前 20 条做 dev），重跑结果一致。

### 4.2 Audio tokenize + 生成 data_config

```bash
python scripts/train/make_data_config.py \
    --data_dir "$S2V_WORK/data/omnivoice_<hero>"
```

这一步会：
1. 调 `tokenize_single.py` 把 JSONL 转成 WebDataset shards（24 kHz 音频 token）
2. 生成 `data_config.json`，**tar 路径自动写成 `file:///D:/...`** ← 关键

**✅ 验收**
1. `tokens/train/audios/*.tar` 与 `tokens/train/txts/*.jsonl` 数量匹配
2. `data_config.json` 里的路径以 `file:///` 开头

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
bash scripts/train/run_train.sh \
    "$REPO/configs/train_config_lora.json" \
    "$S2V_WORK/data/omnivoice_<hero>/data_config.json"
```

### 5.3 关键超参

| 参数 | 值 | 说明 |
|---|---|---|
| `use_lora` / `lora_r` / `lora_alpha` | true / 16 / 32 | 可训练参数 4.2% |
| `learning_rate` | 1e-4 | |
| `steps` | 600 | 904 条数据 ≈ 69 epoch |
| `batch_tokens` × `gradient_accumulation_steps` | 1024 × 8 | ≈ 8192 tokens/步 |
| `mixed_precision` | bf16 | |
| `attn_implementation` | sdpa | 省显存 |
| `num_workers` | 0 | Windows 多进程 spawn 会炸 |
| `save_steps` / `eval_steps` | 150 | 存 300/450/600 |
| `OMNIVOICE_CPU_OFFLOAD` | 1 | **核心**：内存当显存 |

**✅ 验收**：
- 600 步跑完，final loss 从 ~4.5 降到 ~3.96
- `checkpoint-300/450/600` 都在
- 单步耗时稳定（4GB 卡约 29s/步）

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
| spk-sim ↑ | campplus 嵌入与真人留出片段的余弦相似度 | **超过真人基线**（本项目 0.644） |

> 相似度要看基线，不是看绝对值。生成相似度 0.66 可能是「学好了」也可能是
> 「大家听起来都像」—— 只有和真人互相相似度比才有意义。

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
一起放进 HF 仓库。参考 `examples/dark_willow/REPORT.md`。
