# Source2Voice · OmniVoice 本地补丁说明

低显存（4GB）Windows 单卡训练 OmniVoice 需要两组改动：
**A 组 = 源码补丁**（本目录 `omnivoice_cpu_offload.patch`，打在 OmniVoice 仓库上）
**B 组 = venv 内的库补丁**（打在你自己的 Python venv 里，没有 .patch 文件，按下面步骤手改）

---

## A 组：源码补丁（3 个文件，90 行）

```bash
cd <OmniVoice 源码目录>
git apply /path/to/Source2Voice/patches/omnivoice_cpu_offload.patch
```

| 文件 | 改动 | 为什么 |
|---|---|---|
| `omnivoice/training/builder.py` | 新增 `_install_cpu_offload()` / `_offload_frozen()`；num_workers=0 时不再传 `prefetch_factor` | **核心**：冻结基座权重常驻内存，逐 decoder 层流转 GPU；`prefetch_factor` 在 num_workers=0 时会抛 ValueError |
| `omnivoice/training/checkpoint.py` | `save_pretrained` 失败不中断，改用 `save_state` 存全量 | PEFT 的 save_pretrained 在这个模型结构上会抛错，但全量 state dict 是好的，失败就白训 |
| `omnivoice/training/trainer.py` | prepare 之后把 frozen 权重搬回内存 | 防止 prepare 阶段把所有权重留在显存里直接 OOM |

开关：`OMNIVOICE_CPU_OFFLOAD=1`（见 `scripts/train/run_train.sh`）。

---

## B 组：venv 内库补丁（Windows 专属，3 处）

| 文件 | 改动 | 现象 |
|---|---|---|
| `torch/distributed/rendezvous.py` | Windows 下 `TCPStore(..., use_libuv=False)` | Windows 版 PyTorch 不带 libuv，默认 `use_libuv=True` 会直接崩 |
| `torch/distributed/elastic/rendezvous/static_tcp_rendezvous.py` | 同上 | 同上 |
| `webdataset/cache.py` | `file://` URL → Windows 路径转换 | webdataset 的 gopen 不认 `file:///D:/...`，需转成本地路径 |

### 定位与修改

```bash
SITE=$(python -c "import site; print(site.getsitepackages()[0])")
```

**rendezvous.py** —— 把 `TCPStore` 的构造改成显式关掉 libuv：

```python
# 找到 TCPStore( 那一行，补一个关键字参数
TCPStore(
    host=host,
    port=port,
    world_size=world_size,
    is_master=is_master,
    timeout=timedelta(seconds=timeout),
    use_libuv=False,        # <-- 新增这一行
)
```

**static_tcp_rendezvous.py** —— 同样在 `TCPStore(...)` 调用里加 `use_libuv=False`。

**webdataset/cache.py** —— 在处理 `file://` 前缀的地方，把 URL 转成本地路径：

```python
if url.startswith("file://"):
    # Windows: file:///D:/path -> D:/path
    url = url[len("file://"):]
    if re.match(r"^/[A-Za-z]:", url):   # /D:/... -> D:/...
        url = url[1:]
```

---

## 额外依赖

| 依赖 | 原因 |
|---|---|
| `audioop-lts` | Python 3.13 移除了 `audioop`，pydub 依赖它 |
| `hatchling` + `editables` + `pip install --no-build-isolation` | OmniVoice 用 hatchling 构建 |

---

## data.lst 的路径格式（极易踩）

`data.lst` 里每行的 tar 路径**必须**是 `file:///D:/...` 形式：

```
file:///D:/dwvits/work/data/omnivoice_dark_willow/tokens/train/audios/shard-000000.tar  file:///D:/.../txts/shard-000000.jsonl  100  123.4
```

写成 `D:/dwvits/...` 会失败 —— webdataset 的 gopen 会把它当相对路径或 URL。
`scripts/train/make_data_config.py` 已经自动处理这个转换。
