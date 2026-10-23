# OmniVoice 微调邪影芳灵音色 — 训练与评估报告

日期：2026-10-24 | 数据：`schinese_dark_willow_vo_pure.list`（904 条 / 0.8h，884 训练 + 20 留出）

## 训练概况

- 模型：OmniVoice（k2-fsa/OmniVoice，0.6B Qwen3 底座，639M 参数）LoRA 微调（r=16，约 4.2% 参数可训练）
- 配置：lr 1e-4，600 步，batch_tokens 1024 × grad_accum 8（≈8192 tokens/步，约 69 epochs）
- 硬件：RTX 3050 Ti Laptop 4GB，**冻结权重常驻内存、逐层流转 GPU**（Windows 无 NCCL，FSDP 不可用）
- 结果：600/600 步正常完成，历时 4 小时 52 分，loss 4.5 → 3.96，每 150 步存档

## 不同步数对比评估

测试集：4 条**留出**文本（不在训练集）；两种模式：ref（带 DW 参考音频）、noref（纯文本）
指标：CER（whisper-medium 中文转写字符错误率，繁简归一后）、spk-sim（campplus 对 6 条真人 DW 留出片段的平均余弦相似度）
**基线：真人 DW 片段互相相似度 = 0.644**

| checkpoint | 模式 | CER ↓ | spk-sim ↑ |
|---|---|---|---|
| **ckpt-600** | ref | **0.000** | 0.664 |
| ckpt-600 | noref | 0.060 | 0.636 |
| ckpt-300 | ref | 0.042 | **0.694** |
| ckpt-300 | noref | 0.045 | 0.660 |
| ckpt-450 | ref | 0.045 | 0.614 |
| ckpt-450 | noref | 0.063 | 0.657 |

合并模型（ckpt-600 官方 merge-lora）额外验证 3 条：CER 0/0.333/0，sim 0.67/0.62/0.66。

## 结论

1. **推荐 ckpt-600 + ref 模式**：内容零错误，相似度 0.664 超过真人基线；ckpt-300 相似度略高（0.694）可作为备选。
2. **noref 模式可用**：无参考音频时相似度仍达 0.63-0.66，说明音色已微调进模型参数，日常使用不必带参考音频。
3. 音色已成功学到邪影芳灵的声线，中文发音清晰（CER 普遍 < 7%）。

## 交付物

| 内容 | 路径 |
|---|---|
| 合并模型（独立可用） | `D:/dwvits/exp/omnivoice_dark_willow_merged` |
| LoRA checkpoint | `D:/dwvits/exp/omnivoice_dark_willow_lora/checkpoint-{300,450,600}` |
| 生成样本 | `D:/dwvits/out/omnivoice_dark_willow/`（ckpt-300/450/600/merged 子目录） |
| 训练/评估脚本 | `D:/dwvits/src/OmniVoice/examples/` |

推理命令：
```bash
python -m omnivoice.cli.infer --model D:/dwvits/exp/omnivoice_dark_willow_merged \
    --text "待着吧,哪儿也别想去。" --language zh --output out.wav
# 或 adapter 模式（免合并）：
#   --model D:/dwvits/models/omnivoice --lora_adapter .../checkpoint-600
```

## 推理速度实测（24 字中文，num_step=32）

| 环境 | 平均生成耗时 | RTF | 备注 |
|---|---|---|---|
| GPU fp16（RTX 3050 Ti Laptop 4G） | 3.36 s/句 | 0.71 | 快于实时 |
| 纯 CPU fp32 | 59.8 s/句 | 12.5 | GPU 快 17.8 倍 |

## 部署工具（deploy/ 目录）

| 文件 | 用途 |
|---|---|
| `D:/dwvits/deploy/omnivoice_server.py` | FastAPI HTTP 服务（`/health`、`/tts`、`/tts_file`） |
| `D:/dwvits/deploy/start_server.bat` | Windows 一键启动 |
| `D:/dwvits/deploy/start_server.sh` | Linux 服务器启动 |
| `D:/dwvits/deploy/client_example.py` | 客户端调用示例 |
| `D:/dwvits/deploy/README.md` | 部署文档 |
