# Source2Voice · 已知坑与解法

按「症状 → 原因 → 解法」组织。全部来自本项目真实踩坑。

---

## 换游戏阶段

### 找不到英雄的资源目录（显示名 ≠ 内部代号）
**症状**：VPK 扫描结果里没有「邪影芳灵」「Paige」这种显示名。
**原因**：Valve 的内部代号跟显示名无关。
- Dota 2：邪影芳灵 = `dark_willow`，音频却是 `helmet_sylph_*`
- Deadlock：Paige = `bookworm`，Violet = `artist`，Billy = `punkgoat`
**解法**：扫 VPK 的 `sounds/vo/` 目录，每个英雄一个子目录，目录名即内部代号。
Deadlock 还可以直接读磁盘上的 `hero_presence_cache.json`（56 条映射）：

```bash
python - <<'PY'
import json, glob
for p in glob.glob(r"<游戏>/game/citadel/**/hero_presence_cache.json", recursive=True):
    for k, v in json.load(open(p, encoding="utf-8")).items():
        print(k, "->", v)
PY
```

> ⚠️ 常见误判：Deadlock 的 Billy 内部代号是 `punkgoat`，不是 `billy`。

### VPK 里找不到台词文件
**症状**：`sounds/vo/` 扫得到音频，但 `resource/subtitles/` 里没有对应文件。
**原因**：**Deadlock 的台词不在 VPK 里**，而是解压在磁盘上的未打包目录：
`<游戏>/game/citadel/resource/localization/citadel_generated_vo/citadel_generated_vo_english.txt`
（5.8 MB / 78453 行，KV 风格 `"token" "text"`）。
**解法**：用 `subtitle_sources` 的 `file:` 前缀指向磁盘文件：

```json
"subtitle_sources": [
  "file:<游戏>/game/citadel/resource/localization/citadel_generated_vo/citadel_generated_vo_english.txt"
]
```

### 找不到中文语音包
**症状**：`citadel_schinese/pak01_dir.vpk` 存在但只有 50 条 panorama UI 资源。
**原因**：Deadlock **根本没做中文语音**，不是配置问题。
**解法**：确认后走「做英文即可」路线，阶段 2 的 ASR 整段跳过。

### 同一 stem 匹配到多个 token
**症状**：一个音频能对上好几个字幕 token，选出来的台词不属于这个音频。
**原因**：Deadlock 的 token 命名是 `<stem>_<后缀>`，后缀集合为
`hero_3d` / `ability_3d` / `ult_3d` / `zipline_3d` / `ping_2d` / `hero_announcer`，
且存在 `_alt` 一对多变体。
**解法**：用 `token_rules` 的 `{stem}_*` 前缀通配 + `token_priority` 显式排序：

```json
"token_rules": { "vo": ["{stem}_*"] },
"token_priority": ["hero_3d","ability_3d","ult_3d","zipline_3d","ping_2d","hero_announcer"]
```

实测覆盖率：Paige 1547/1615（95.8%）、Violet 2033/2111（96.3%），
未匹配项均为纯音效（无台词），属正常。

### 两个英雄的 manifest 互相覆盖
**症状**：跑完 Paige 再跑 Violet，manifest 里只剩 Violet。
**原因**：两个英雄写同一个 `metadata/manifest.json`。
**解法**（已修）：pipeline 现在写 `manifest_<hero_key>.json`，
并自动合并去重到 `manifest.json`（键 = `hero_key + language + group + filename`）。
合并旧 manifest 时会 `setdefault("hero_key", ...)` 以兼容历史文件。

---

## 提取阶段

### VPK 解析报签名错误
**症状**：`VPK_SIGNATURE` 校验失败。
**原因**：Source 2 用的是 Source1 v1 格式 VPK（签名 `0x55AA1234`），
但索引文件必须传 `pak01_dir.vpk`，不是 `pak01_000.vpk`。
**解法**：`scripts/extract/vpk.py` 已实现。目录树结构为
`ext → dir → file → 18 字节 entry`。

### `.vsnd_c` 剥不出 MP3
**症状**：`no MP3 sync at offset N`。
**原因**：不是所有 `.vsnd_c` 都是 MP3 —— 可能有其他编码。
**解法**：先检查 `blob[offset] == 0xFF`。若不是，说明该英雄用了别的格式，
需要单独分析容器头。
（Dota 2 与 Deadlock 实测格式一致，前 4 字节小端 uint32 = MP3 偏移。）

### 音频文件名前缀和字幕 token 对不上
**症状**：`matched subtitle` 远小于 `clips`。
**原因**：Valve 的命名有多套并存 —— 显示名、内部代号、旧命名表。
比如邪影芳灵：音频 `sylph_*`，token `dark_willow_sylph_*`，
旧命名表又叫 `sylph_sylph_*`。
**解法**：在 `token_rules` 里把候选模板按优先级列出，
按顺序取第一个命中的。参考 `configs/hero_dark_willow.json`。
用真实数据验证方法：
```python
# 统计每个候选各自能命中多少，挑最优组合
for stem in stems:
    for rule in rules:
        if rule.format(**fields) in table: count[rule] += 1
```

### VPK 里找不到中文资源
**症状**：中文 VPK 存在但目录是空的。
**原因**：不同语言的资源分装在不同 VPK 包：
- 英文 → `game/dota/pak01_*.vpk`（672 分卷）
- 中文 → `game/dota_schinese/pak01_*.vpk`（45 分卷）

**解法**：`scripts/s2v_config.py` 的 `LANG_PACKAGES` 已配好。
`GAME_REGISTRY` 里每个游戏一套 `game_root` + `lang_roots`，用 `S2V_GAME` 环境变量切换。
英雄档案还可以用 `vpk_overrides` 单独覆盖某语言的 VPK 路径。

---

## ASR 阶段

### Whisper 逐条识别太慢
**症状**：2400 条要跑一整天。
**原因**：Whisper 固定编码 30 秒窗口，1–3 秒的短句浪费 ~95% 算力。
**解法**：窗口打包（~28 秒/窗）+ `word_timestamps=True` + 按词中点回切。
实测 0.16× 实时 → **4.25× 实时**（约 40× 提速）。

### 拼接成一个长文件后切不开
**症状**：整段被当成一条。
**原因**：VAD 把连续语音合并了。
**解法**：短句之间插 **≥1 秒静音**，让 VAD 正确切分。

### 边界粘连（下一条开头粘到上一条末尾）
**症状**：`前进中,在`、`轮到天辉禁用,天` 这类。
**原因**：Whisper 中文"词"是多字块，跨音频边界时按时间中点**整个**划给一侧。
**解法**（`asr_tail_merge.py`）：
1. 可疑条目**单独**再识别一次（无邻居可粘，长度可信）
2. 融合裁剪：
   - `len(core(iso)) >= len(core(old))` → 保留窗口版
   - 相同前缀 ≥ 2 字 → 按 `iso` 的字数裁剪窗口版
   - 前缀不一致 → 用 `iso`（判定为开头被拉走）
3. `core()` 忽略标点再比长度，所以 `哦,高水平战略,我就` 会自然收敛成 7 字

### Whisper 幻觉
**症状**：非语音音频上出现「优优独播剧场——YoYo Television Series Exclusive」
「请不吝点赞 订阅 转发 打赏支持明镜与点点栏目」。
**原因**：large-v3 在静音/噪音上会生成训练数据里见过的字幕模板。
**解法**（`mark_nonverbal.py`）：
- 关键词表：优优独播/独播剧场/请不吝/点赞/订阅/转发/打赏/明镜/点点栏目/字幕组/Amara
- 重复检测：`(.{1,3})\1{5,}` 重复 ≥6 次 **且** 该行英文不是纯喊声
  （「且」这个条件很关键，否则真笑声「哈哈哈哈」会被误杀）

### 非语言条目被当成训练对
**症状**：喊声/笑声/惨叫（英文行 `Ugh!` / `Hahahaha!`）也进了训练清单。
**原因**：Whisper 会硬产出拟声字，但那是「噪声的音译」不是语音。
**解法**：**保留音频、标注文本不可用、从训练清单剔除**。
不是「改文本」能解决的。

### 专有名词同音错字
**症状**：`灰药`（辉耀）、`杯梅城`（悲玫城）、`遍体精灵`（变体精灵）。
**原因**：Whisper 按读音转写，遇到专有名词就换成最接近的常用词。
**解法**：**拼音级**匹配（`asr_names.py`），不比较字符 ——
这类错误逐字完全不同但读音一致，字符级匹配完全无效。
原理：每条英文台语句都明确提到了该实体，我们知道**哪个名字必须出现**，
只需找到它在拼音序列里的位置。

### whisper 输出繁体导致 CER 虚高
**症状**：CER 30%+，但听着发音是对的。
**原因**：whisper 会漂成繁体（`天徽` vs `天辉`）。
**解法**：CER 前用 `zhconv` 转 `zh-hans`，并做全角数字归一。
融合判断也必须在简体形态上做（用 `opencc-python-reimplemented`），
否则 `敵方下路兵營已被摧毀` 会被误判成「错位」。

### 术语表匹配到错误的地方
**症状**：`红武军团` / `古铜军团`（Red Mist Horde / Bronze Legion）被误改。
**原因**：这些是**正确**译法；`敌方下塔刚被讨伐` 里的「刚被」是 "just got"。
**解法**：术语表里写**完整词组**（如 `军团全面加固`）而不是单词。

---

## 训练阶段

### Windows 下 DataLoader 报 `prefetch_factor` 错误
**症状**：`ValueError: prefetch_factor option could only be specified in multiprocessing...`
**原因**：`num_workers=0` 时不能传 `prefetch_factor`。
**解法**：补丁 `builder.py` 里 `num_workers=0` 时不传该参数。

### CUDA OOM（4 GB 卡）
**症状**：4 GB 显存直接 OOM，尽管模型只有 0.6B。
**原因**：冻结基座 fp32 权重 2.4 GB 全在显存里。
**解法**：`OMNIVOICE_CPU_OFFLOAD=1` —— 冻结权重常驻内存，
逐 decoder 层流转 GPU。**同时需要 ≥16 GB 系统 RAM**。

### `TCPStore` 崩溃
**症状**：`RuntimeError` 提到 use_libuv 或 TCPStore。
**原因**：Windows 版 PyTorch 不带 libuv，默认 `use_libuv=True` 会崩。
**解法**：改 venv 内 `torch/distributed/rendezvous.py` 和
`elastic/rendezvous/static_tcp_rendezvous.py`，TCPStore 构造加 `use_libuv=False`。

### webdataset 读不到 tar
**症状**：`data.lst` 里的路径找不到文件。
**原因**：webdataset 的 gopen 不认 Windows 盘符路径。
**解法**：**必须**写 `file:///D:/dwvits/.../shard-000000.tar`。
`scripts/train/make_data_config.py` 已自动转换。

### 训练启动即报 `AssertionError: file:///D:/... is not a file.`
**症状**：`omnivoice/data/dataset.py:143` 抛断言，`manifest_path` 被判不是文件。
**原因**：**`file:///` 前缀加错了地方**。三种路径的形态不能互换：

| 位置 | 正确形态 | 校验方式 |
|---|---|---|
| `data_config.json` 的 `manifest_path` | **普通绝对路径** `D:\...\data.lst` | `os.path.isfile()` |
| `data.lst` 内部的 tar 路径 | **`file:///D:/...`** | webdataset gopen 按 URL 解析 |
| `data.lst` 内部的 jsonl 路径 | **普通绝对路径** | `LabelDataset` 用 `open()` |

**解法**：
- `make_data_config.py` 的 `manifest_path` 不要走 `to_file_url()`
- `tokenize_single.py` 写 data.lst 时，tar 路径走 `to_file_url()`、jsonl 路径保持普通路径
- `make_data_config.py` 内置 `normalize_data_lst()` 自愈：已有 shards 时
  跑一次 `--skip_tokenize` 即可批量修正

**✅ 对照速查**（dark willow 成功样本）:
```
file:///D:/dwvits/data/omnivoice_dark_willow/tokens/train/audios/shard-000000.tar D:\dwvits\data\omnivoice_dark_willow\tokens\train\txts\shard-000000.jsonl 100 333.667
```

### `ModuleNotFoundError: No module named 'scipy'`
**症状**：跑数据准备脚本报缺 scipy。
**原因**：OmniVoice 训练环境不一定装了 scipy（纯 CPU offload 训练本身不需要）。
**解法**：数据准备（tokenize / loudness / 评估）脚本改用
装了 scipy + soundfile + numpy 的环境，例如 `envs/train/Scripts/python.exe`。
纯训练任务仍用 `S2V_PYTHON` 指向的环境。

### `NameError: name 'sys' is not defined`
**症状**：`scripts/clean/refine_dataset.py` 报 `sys` 未定义。
**原因**：脚本原本就漏了 `import sys`（既有 bug）。
**解法**：在 `import shutil` 后补 `import sys`。已修。

### 存 checkpoint 时报错中断
**症状**：`save_pretrained` 抛异常，训练直接停。
**原因**：PEFT 的 `save_pretrained` 在这个模型结构上失败，但全量 state dict 是好的。
**解法**：补丁 `checkpoint.py` —— `save_pretrained` 失败不中断，
改走 `save_state`（FULL_STATE_DICT）存全量。**否则几百步白训。**

### prepare 阶段 OOM
**症状**：还没开始训练就 CUDA OOM。
**原因**：prepare 把所有权重搬到了显存。
**解法**：补丁 `trainer.py` —— prepare 之后把 frozen 权重搬回内存。

### 推理时两个合并模型一起加载 → OOM
**症状**：想同时试听/对比两个英雄的 merged 模型（各 2.4 GB safetensors），
`from_pretrained` 第二次直接 CUDA OOM，即使单次只推理一小段。
**原因**：4 GB 卡一次只能驻留一个 0.6B 合并模型；两个一起 `from_pretrained`
会同时占 2.4 GB×2 + 推理激活，远超 4 GB。
**解法**：**逐模型串行**。一个进程内跑完一个英雄后
`del model; torch.cuda.empty_cache()`（或干脆一个进程只装一个模型，
跑完退出再启下一个），再加载下一个。`test_infer.py` 本身是单次单模型，
多英雄对比要分多次跑、不要在同一进程里 `OmniVoice.from_pretrained` 两次。

### py3.13 装不上 / pydub 报错
**症状**：`ModuleNotFoundError: No module named 'audioop'`。
**原因**：Python 3.13 移除了 `audioop`。
**解法**：`pip install audioop-lts`。

### OmniVoice 装不上
**症状**：pip 构建失败。
**解法**：装 `hatchling` + `editables`，并用 `pip install -e . --no-build-isolation`。

---

## 评估阶段

### PEFT 合并后模型音色全丢
**症状**：`merge_lora.py` 跑完，合并模型输出是通用音色。
**原因**：PEFT state dict 键名是 `.lora_A.default.weight`（**带 `.default`**），
手写脚本按 `.lora_A.weight` 找就全漏了。
**解法**：**优先用官方工具** `python -m omnivoice.cli.merge_lora`。
备用 `scripts/train/merge_lora.py` 已处理 `.default`。

### CER 很高但听起来没问题
**症状**：CER 30%+。
**原因**：繁体没转简。
**解法**：CER 前 `zhconv.convert(t, "zh-hans")` + 全角数字归一 + 标点剥离。

> **英文数据集不要做繁转简**（`zhconv` 是中文专用，英文侧会误伤）。
> 英文只需统一标点（弯引号 → 直引号）与大小写归一即可。

> **注意 `zhconv` 可能压根没装**。`make_norm()` 里是 `except ImportError: pass`
> 静默跳过，于是繁体全部保留、CER 虚高 —— 实测同一份产物：
> 缺 zhconv 时 ckpt-600/ref CER = 0.202，装上后 = **0.000**。
> 中文评估前先确认：`python -c "import zhconv"`。

### 相似度看着很低就以为失败了
**症状**：spk-sim 0.6 就判定「没学到」。
**原因**：没有基线对比。
**解法**：先算**真人片段互相之间的相似度**作为基线。
本项目邪影芳灵基线 0.644 —— 生成相似度 0.664 已**超过**基线，
说明学到了。不同英雄的基线差异很大，必须自己测。

### whisper 加载音频失败
**症状**：`RuntimeError: Failed to load audio`。
**原因**：faster-whisper 依赖 ffmpeg 解码音频，而系统没装 ffmpeg。
**解法**：用 `soundfile` 自己读 wav 传 numpy 进去。

### `ModuleNotFoundError: No module named 'whisper'`
**症状**：评估脚本第 138 行 `import whisper` 直接崩。
**原因**：评估要用 OpenAI whisper，但训练环境常常只装了 faster-whisper
（包名不同，`import whisper` 不成立）。
**解法**：评估脚本已支持**双后端自动探测**（`--asr_backend auto`）：

| 后端 | 包名 | 说明 |
|---|---|---|
| `whisper` | `openai-whisper` | `import whisper`，Windows 上依赖较重 |
| `faster_whisper` | `faster-whisper` | `from faster_whisper import WhisperModel`，轻量 |

```bash
pip install openai-whisper -i https://mirrors.aliyun.com/pypi/simple/
# 或
pip install faster-whisper  -i https://mirrors.aliyun.com/pypi/simple/
```

两个都装不上时，脚本会打印明确安装提示而不是抛 ModuleNotFoundError。

> **中文评估还需要 `zhconv`**（繁转简），缺失时 CER 会虚高 2–3 倍：
> `pip install zhconv -i https://mirrors.aliyun.com/pypi/simple/`

### 真人基线和历史报告对不上
**症状**：同一模型、同一批 checkpoint，重跑后基线从 0.644 变成 0.339。
**原因**：基线取决于**选了哪几条真人片段**。
用 `--real_dir` + `--real_glob` 采样时，glob 顺序 / 文件数量一变，
选中的片段就完全不同，基线和 spk-sim 都不可比。
**解法**：用 `--real_list` 固定住片段清单（每行一条 wav 路径）：

```bash
python scripts/eval/eval_omnivoice.py \
    --ckpt_root  D:/dwvits/out/omnivoice_paige \
    --real_list  D:/dwvits/work/eval/paige_real_list.txt \
    --texts      D:/dwvits/work/eval/paige_eval_texts.json \
    --lang en
```

> 清单里的片段**必须是留出集**（不在训练清单里）。
> 本项目用 dev.jsonl 生成，已验证与 train.jsonl 零重叠。

### `NoSuchFile: Load model from D:/dwvits/models/campplus.onnx failed`
**症状**：评估脚本建 onnx session 时报模型文件不存在。
**原因**：`s2v_config` 里 `CAMPPLUS` 硬编码成 `$ROOT/models/campplus.onnx`，
但 CosyVoice 发行包把它放在 `models/cosyvoice/<model>/campplus.onnx`。
**解法**：`s2v_config._resolve_campplus()` 现在会在 `$ROOT/models` 下
递归查找 `campplus.onnx`；也可以显式指定 `S2V_CAMPPLUS=<绝对路径>`。

### 带参考音频反而更长
**症状**：同一句话，带 ref 生成 33 s，纯文本 16 s。
**原因**：ref 模式下模型会把参考音频的内容也合成出来。
**解法**：日常使用**推荐纯文本模式**（音色已内化进参数）。
评估时两个模式都要测 —— noref 相似度才说明音色真的学进去了。

### 合并后校验报 `tokenizer/ 缺失`，但模型其实是好的
**症状**：`merge_and_verify.py` 明明合并成功，却打印 `tokenizer/ 缺失`。
**原因**：OmniVoice 的 tokenizer 是**扁平文件**（`tokenizer.json` +
`tokenizer_config.json` + `chat_template.jinja`），不是目录。
校验只判了 `tokenizer/` 目录，于是永远报缺失。
**解法**：校验清单已改为逐个文件判断，同时保留 `audio_tokenizer/` 目录检查。

### 合并脚本一直走回退分支
**症状**：日志里官方 `merge_lora` 失败，紧接着回退到 `merge_lora.py`。
**原因**：官方 CLI 的参数名是 **`--lora_adapter` / `--output_dir`**，
不是 `--adapter` / `--output`。传错名字 argparse 直接退出非零。
**解法**：`merge_and_verify.py` 已按官方签名传参。改这个脚本前
务必先看一眼目标仓库的 CLI 定义：

```bash
grep -n "add_argument" <OmniVoice源码>/omnivoice/cli/merge_lora.py
```

### 长任务没有守护进程，训练完就停在那儿
**症状**：训练跑完 5 小时，后面合并/评估/上传全靠人手动触发。
**解法**：用「等待 + 串行执行」的守护脚本（见 `references/` 里的思路）。
存活性判定**不要用 `ps -ef | grep`**——Git Bash 下 `ps` 输出可能含二进制
字符，`grep` 匹配行为不可靠；改看**日志 mtime**：训练每步都写日志，
停更 10 分钟即判定训练已死。

---

## 发布阶段

### HF 上传极慢
**症状**：150 KB/s，3 GB 要 4.5 小时。
**原因**：没装 `hf_transfer`。
**解法**：`pip install hf_transfer` + `HF_HUB_ENABLE_HF_TRANSFER=1` → **34 MB/s**。

### HF 上传「卡死」但其实是正常静默
**症状**：`upload_hf.py` 打了 `[HH:MM:SS] START <repo>` 后，日志十几分钟
没有新行，进程还活着，看起来像挂了。
**原因**：`upload_folder` 走 `hf_xet`/`hf_transfer` 时**只在 START / DONE 打印**，
中间无逐文件进度；3 GB 级模型走代理时静默 3–10 分钟属正常。
**判活**（别靠日志行数）：① `python.exe` 进程是否还在；② 代理可达
（`curl -x http://127.0.0.1:10808 https://huggingface.co` 返回 200）；
③ HF 仓库 ref/blob 是否有变化。三者都正常就耐心等 `DONE`。
**切勿**在静默期手动再启一个 `upload_hf.py` 传同一仓库——
会和正在跑的 `upload_folder` 抢同一 ref，可能冲突或覆盖。

### 代理连不上 HF
**症状**：huggingface.co 返回 502，或 hf-mirror 308 跳转。
**原因**：**代理端口搞错了**。shell 里已有的 `http_proxy` 环境变量
不一定是你系统代理真正的端口。
**解法**：从注册表读真实值：
```powershell
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable, ProxyServer
```
然后在进程内显式设 `HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy`。
`netsh winhttp show proxy` 显示「直接访问」是正常的（WinHTTP 层无代理）。
用对代理后**官方端点 huggingface.co 直连可用**，不必绕 hf-mirror。

### hf_hub_download 报 FileNotFoundError
**症状**：返回路径存在但 `open()` 失败。
**原因**：Windows 下 HF 默认缓存的 snapshot 软链接建不出来。
**解法**：**加 `local_dir=` 参数**直接下载到目录：
```python
hf_hub_download(repo_id, "config.json", repo_type="model", local_dir="D:/out")
```
仓库本身没问题。

### 模型文件下载下来是 0 字节
**症状**：`model.safetensors` 是 0 字节。
**原因**：xet CDN 走代理超时，`.incomplete` 文件没归位。
**解法**：检查 `blobs/` 里的 `.incomplete`，**文件其实已经字节完整**，
手动改名归位即可。

---

## 通用坑

### 响度阈值全局化导致整包误杀
**症状**：某个播音包 431 条全被判定为离群。
**原因**：播音包和英雄语音的母带增益不同。
**解法**：**按来源分组**做响度离群判断。

### 训练时误删数据
**症状**：某些条目被当异常丢掉。
**原因**：「语气夸张」不等于「数据脏」。
**解法**：**分桶而不是删除** —— `core` / `style` / `review` 三桶。
`core` 用于先训音色，`style` 作为语气增强候选，`review` 需人工听审。

### 划分不确定导致评估不可复现
**症状**：重跑后 dev 集变了，指标无法对比。
**解法**：固定 seed 洗牌（`prep_omnivoice_data.py` 的 `--seed 42`），
留出集一旦确定就不要再动。
