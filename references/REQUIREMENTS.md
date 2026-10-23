# Source2Voice · 环境与算力要求

本文所有数字均为**本项目实测值**（Dota 2 邪影芳灵 / Deadlock Paige & Violet，2026-10），
不是理论估算。换硬件时按下面的比例线性外推。

## 参考实测环境

| 项 | 配置 |
|---|---|
| GPU | NVIDIA GeForce RTX 3050 Ti Laptop GPU，**4 GB VRAM**，驱动 617.42 |
| CPU | Intel Core i7-12700H，14 核 20 线程 |
| RAM | 39.7 GB |
| OS | Windows（Win10/11，Git Bash） |
| Python | 3.13（训练）/ 3.10（CosyVoice 支线） |
| 磁盘 | 数据集 1.0 GB + 模型 3.3 GB + 中间产物 ≈ 15 GB |

> **关键约束**：Windows 版 PyTorch **不带 NCCL** → FSDP / DDP 完全不可用。
> 这直接决定了整个训练方案：**单进程 + 自研逐层 CPU offload**。
>
> **第二约束**：**一张 GPU 同时只能训一个音色**。多英雄必须排队，
> 并发会显存互撞。

---

## 最低 / 推荐 / 舒适

| 资源 | 最低可跑 | 推荐 | 舒适 |
|---|---|---|---|
| **VRAM** | 4 GB（需 offload） | 8 GB | 12 GB+ |
| **RAM** | 16 GB | 32 GB | 48 GB+ |
| **CPU** | 6 核 | 14 核 | 16 核+ |
| **磁盘空闲** | 20 GB | 40 GB | 80 GB+ |
| **GPU 算力** | 无 GPU（CPU 可训，约 20× 慢） | 任意 CUDA | RTX 4090 / A100 |

### VRAM 与 RAM 的关系（最关键的一条）

OmniVoice 0.6B 基座是 fp32 冻结权重 + LoRA：

```
冻结基座权重（fp32）≈ 2.4 GB   ← 常驻 RAM，不进显存
LoRA + audio_embeddings/heads   ← 常驻 VRAM
每层 decoder 临时流转           ← 峰值只放几层
```

所以 **VRAM 4 GB 就够，但 RAM 至少 16 GB**（要装下 2.4 GB 基座 + 优化器 +
数据 tokenize 缓冲）。RAM 不足会 OOM，且报错信息误导为 CUDA OOM。

参考实现：`patches/omnivoice_cpu_offload.patch` 的 `_install_cpu_offload()`。

### GPU 算力档位

| 档位 | 条件 | 单步耗时（600 步总时长） | 说明 |
|---|---|---|---|
| 无 GPU | CPU fp32 | ~580 s/步（约 4 天） | 不推荐 |
| 入门 | 4–6 GB 桌面卡 | ~25–35 s/步（**5–6 h**） | 本项目实测档 |
| 主流 | 8–12 GB | ~12–18 s/步（2.5–3.5 h） | 建议 |
| 高端 | 24 GB+ | ~6–9 s/步（1–1.5 h） | 可上 batch_tokens 4096 |

**时间比值**：训练时间 ≈ `steps × 单步耗时`，
单步耗时 ∝ `batch_tokens × gradient_accumulation_steps ÷ GPU 算力`。

> ⚠️ 换更强显卡时**不要线性加大 batch_tokens**。
> 本项目 904 条数据只有 0.8 小时，batch 太大会导致 epoch 太少、
> 有效训练量反而下降。显存富裕优先**多存 checkpoint**（save_steps 调小到 75）。

### 训练期间不要跑重活（实测）

`OMNIVOICE_CPU_OFFLOAD=1` 的逐层 offload 依赖 **CPU 持续供数**，
所以训练期间并行跑评估/推理会直接拖慢训练：

| 训练期间在做什么 | 单步耗时 |
|---|---|
| 什么都不做 | **28–31 s** |
| 并行跑 whisper medium 评估 | **58 s**（慢 87%） |

> 实测：跑一轮 Dark Willow 回归评估（whisper medium，CPU int8），
> 训练单步从 28.5 s 涨到 57.9 s。
> **训练期间只做轻活**（改文档、准备清单、写评估 JSON），
> 评估/推理/合并全部等训练结束。

---

## 各阶段耗时（实测）

| 阶段 | 4GB 入门卡 | 8–12GB 主流卡 | 纯 CPU | 瓶颈 |
|---|---|---|---|---|
| 0 定位资源 | 10 min | 10 min | 10 min | 人工 |
| 1 提取音频 | 5 min | 5 min | 5 min | ffmpeg（CPU） |
| **2 ASR**（仅缺字幕时） | **2–4 h** | 2–4 h | **20–40 h** | **CPU + Whisper** |
| 3 清洗 | 20 min | 20 min | 20 min | 人工 + CPU |
| 4 数据准备 | 15 min | 15 min | 15 min | GPU tokenize |
| **5 训练** | **5–6 h** | 2.5–3.5 h | ~4 天 | **GPU** |
| 6 评估+发布 | 1 h | 30 min | 1 h | GPU + 网络 |
| **合计（有官方字幕）** | **6–7 h** | **4–5 h** | **4–6 天** | |
| **合计（需 ASR）** | **10–14 h** | **7–9 h** | **5–7 天** | |

> **有官方英文字幕 vs 必须 ASR，差 4–7 小时。**
> Deadlock 走英文路线实测 6–7 h，Dota 2 走中文路线 10–14 h。

### 阶段 2（ASR）是隐藏的最大成本

这是最容易被低估的一环 —— **它跟 GPU 无关，纯粹吃 CPU**。

实测数据（14 核 i7-12700H，faster-whisper large-v3 int8）：

| 方式 | 速度 | 2400 条耗时 | 质量 |
|---|---|---|---|
| 逐条识别 | 0.16× 实时 | ~10 h | 最好 |
| **窗口打包（28s/窗 + 词级时间戳回切）** | **4.25× 实时** | **~15 min** | 有边界粘连，需修正 |
| 单条重识别（修边界粘连） | 12.75 s/条 | 732 条 ≈ 52 min | 长度准、字词退化 |

**时间比值**：
- 窗口打包 vs 逐条：**约 40× 加速**
- 但打包后有 ~30% 条目需单独重识别（732/2400），这部分**抵消约 35% 的加速收益**

> 结论：先打包跑一遍，再只对可疑条目单独识别，是总耗时最优解。
> 纯逐条要 10 小时，打包+修正约 1.5 小时。

### 阶段 3（清洗）走官方字幕时快很多

Dota 2 的清洗耗时大头是**人工校对 ASR 文本**（2 小时量级）。
走官方字幕路线时文本天然干净：

| 实例 | 提取 clips | 唯一台词 | 重复 | 超短 | CJK 混入 | 人工修正耗时 |
|---|---|---|---|---|---|---|
| Dota 2 邪影芳灵（中） | 2437 | — | — | — | — | **~2 h** |
| Deadlock Paige（英） | 1615 | 1524 | 23 | 0 | 0 | **0** |
| Deadlock Violet（英） | 2111 | 2009 | 20 | 0 | 0 | **0** |

---

## 磁盘与带宽

| 项 | 需求 | 说明 |
|---|---|---|
| 游戏本体 | 已装（~60 GB） | **前置条件**，不在本技能范围内 |
| VPK 索引 | ~1 GB | `pak01_dir.vpk` |
| 数据集 | ~1 GB（2400 条 × 32000Hz 16bit mono） | ≈ 206 分钟音频 |
| OmniVoice 基座 | 3.3 GB | 含 audio_tokenizer |
| tokenize 中间产物 | ~2 GB | WebDataset shards |
| checkpoint（×3） | ~4 GB | 每 150 步一个 |
| **合计额外** | **≈ 15 GB** | 不含游戏本体 |

### 网络

| 操作 | 需求 | 备注 |
|---|---|---|
| 下载 OmniVoice 基座 | 3.3 GB | 走代理；xet CDN 可能超时，需手动归位 `.incomplete` 文件 |
| 下载 faster-whisper | 3 GB | |
| 上传 HF（模型+数据集） | ~3.5 GB | **必须装 `hf_transfer`**，否则 154 KB/s → 4.5 小时 |
| HF 上传（开 hf_transfer） | — | **34 MB/s** → 约 2 分钟 |

---

## 关键软件依赖

### 系统级

| 依赖 | 版本 | 必需 | 备注 |
|---|---|---|---|
| **ffmpeg** | 任意近期版本 | ✅ | 用于 MP3→WAV。Windows 常需单独装 |
| **NVIDIA 驱动** | ≥ 517 | ✅（有 GPU 时） | |
| Git | 任意 | ✅ | 拉 OmniVoice 源码 |

> 找不到 ffmpeg 时：`scripts/s2v_config.py` 会自动探测
> `C:\Program Files (x86)\FormatFactory\FFModules\Encoder\ffmpeg.exe`
> 等常见位置；也可设 `S2V_FFMPEG` 环境变量。

### Python 训练环境（venv）

```
python 3.13
torch 2.8.0+cu128        # CUDA 版，镜像源的 torch 是 CPU 版
transformers 5.20.2
accelerate 1.15
peft 0.21
soundfile, numpy, scipy
webdataset
audioop-lts              # py3.13 移除了 audioop，pydub 依赖它
hatchling + editables    # OmniVoice 用 hatchling 构建
```

安装要点：
```bash
pip install "setuptools<81"
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -e ./OmniVoice --no-build-isolation
```

### Python ASR 环境（可与训练环境分开）

```
faster-whisper            # pip 走阿里云镜像，清华源没有
ctranslate2
torch（CPU 版即可）
```

### Python 评估环境

```
onnxruntime        # campplus 说话人嵌入
soundfile, numpy, scipy
zhconv             # 繁→简，CER 前必须做（英文数据集不需要）
# ASR 后端二选一，评估脚本自动探测：
openai-whisper     # pip install openai-whisper
# 或
faster-whisper     # pip install faster-whisper
```

> ⚠️ **zhconv 是可选依赖**，`make_norm()` 里 `except ImportError: pass`
> 静默跳过。缺它时 whisper 输出的繁体全部保留，中文 CER 虚高 2–3 倍
> （实测同一份产物：缺 zhconv 0.202，装上 0.000）。
> 中文评估前先 `python -c "import zhconv"` 确认。

### 三个 venv 的分工（本项目实测）

| venv | 关键包 | 用途 |
|---|---|---|
| `envs/omnivoice` | torch + **huggingface_hub** + hf_transfer | 训练、**推理**（要 `import omnivoice`）、**HF 上传** |
| `envs/train` | torch + **scipy** + onnxruntime + whisper + zhconv | 数据准备、**评估** |
| `envs/asr` | faster-whisper | ASR（仅「缺官方字幕」的语言需要） |

> `huggingface_hub` 只装在 `envs/omnivoice` 与 `envs/asr`；
> `scipy` 只装在 `envs/train`（`envs/omnivoice` 没有）。
> **上传用 `envs/omnivoice`，评估用 `envs/train`，别混。**
>
> 推理（`test_infer.py`）需要 `import omnivoice.*`，
> 所以要用 `envs/omnivoice` 并设 `PYTHONPATH=<OmniVoice 源码目录>`。

---

## 代理配置（踩坑重灾区）

**本机系统代理只写在 Windows 注册表里，Python 进程默认读不到。**

正确读法：
```powershell
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable, ProxyServer
# ProxyEnable : 1
# ProxyServer : 127.0.0.1:10808
```

- `netsh winhttp show proxy` 显示「直接访问」——WinHTTP 层无代理，
  必须在 Python 进程内显式设 `HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy`
- **不要相信 shell 里已有的 `http_proxy` 环境变量**，它可能指向别的端口
- `scripts/publish/upload_hf.py` 已经实现了注册表探测，可直接用

---

## 训练数据量参考

| 数据量 | 时长 | 建议 steps | 效果 |
|---|---|---|---|
| 200 条 | ~0.2 h | 300 | 音色粗略，有杂音 |
| **900 条** | **~0.8 h** | **600** | **本项目验证档，CER 0.000–0.06** |
| **1000–1300 条** | **~0.9–1.1 h** | **600** | **Deadlock 验证档（Paige 1001 / Violet 1289）** |
| 2000 条 | ~1.8 h | 1200 | 更稳，但收益递减 |
| 5000 条 | ~4.5 h | 2500 | 需大显存；本流程 4GB 跑不完 |

**比例**：约 **600 steps / 900 条 ≈ 0.67 step/条 ≈ 69 epoch**（904 条数据）。
经验区间：50–100 epoch。低于 20 epoch 学不到音色，高于 150 epoch 开始过拟合。

> Deadlock 实测：Paige 1001 条 / 1269 train、Violet 1289 条 / 1269 train，
> 同样用 600 步，单步耗时 26–28 s（与 Dota 2 几乎一致）。

---

## 推理性能

| 环境 | 24 字中文耗时 | RTF | 备注 |
|---|---|---|---|
| GPU fp16（RTX 3050 Ti 4G） | 3.36 s/句 | **0.71** | 快于实时 |
| 纯 CPU fp32 | 59.8 s/句 | 12.5 | GPU 快 **17.8×** |

- `num_step=32`（扩散步数），降低它能按比例提速
- **带参考音频会显著拉长音频**（33 s vs 16 s）→ 日常使用推荐纯文本模式
- 推理显存需求 ≈ 2.6 GB（fp16）

---

## 最低配置速查

如果只有一台**没装游戏的老机器**：
- 装游戏 + 提音频 + ASR ≈ **3–5 h**（纯 CPU 可完成）
- 微调必须上 GPU（4 GB 起步 + 16 GB RAM）
