# Source2Voice · 已知坑与解法

按「症状 → 原因 → 解法」组织。全部来自本项目真实踩坑。

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

### 存 checkpoint 时报错中断
**症状**：`save_pretrained` 抛异常，训练直接停。
**原因**：PEFT 的 `save_pretrained` 在这个模型结构上失败，但全量 state dict 是好的。
**解法**：补丁 `checkpoint.py` —— `save_pretrained` 失败不中断，
改走 `save_state`（FULL_STATE_DICT）存全量。**否则几百步白训。**

### prepare 阶段 OOM
**症状**：还没开始训练就 CUDA OOM。
**原因**：prepare 把所有权重搬到了显存。
**解法**：补丁 `trainer.py` —— prepare 之后把 frozen 权重搬回内存。

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

### 带参考音频反而更长
**症状**：同一句话，带 ref 生成 33 s，纯文本 16 s。
**原因**：ref 模式下模型会把参考音频的内容也合成出来。
**解法**：日常使用**推荐纯文本模式**（音色已内化进参数）。
评估时两个模式都要测 —— noref 相似度才说明音色真的学进去了。

---

## 发布阶段

### HF 上传极慢
**症状**：150 KB/s，3 GB 要 4.5 小时。
**原因**：没装 `hf_transfer`。
**解法**：`pip install hf_transfer` + `HF_HUB_ENABLE_HF_TRANSFER=1` → **34 MB/s**。

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
