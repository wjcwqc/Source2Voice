#!/usr/bin/env python3
"""Source2Voice · 阶段 7：把模型仓库 + 数据集仓库上传到 HuggingFace。

为什么要单独写脚本而不是直接用 `huggingface-cli upload`
--------------------------------------------------------
1. **代理**：本机系统代理只写在 Windows 注册表里，Python 进程默认读不到。
   脚本会**自己探测**系统代理（读 `HKCU\\...\\Internet Settings` 的
   `ProxyServer`），再显式塞进 HTTP_PROXY/HTTPS_PROXY —— 不要手写端口号，
   换机器/换代理软件后会失效。
2. **速度**：必须 `hf_transfer`（`pip install hf_transfer`），
   否则大文件上传只有 ~150KB/s，3GB 模型要 4.5 小时；开了之后 30+MB/s。
3. **一次传完**：`upload_folder` 自动跳过已存在的相同文件，可安全重跑。

用法
----
    pip install hf_transfer huggingface_hub
    export HF_TOKEN=hf_xxx                    # 或 Windows: set HF_TOKEN=hf_xxx
    python upload_hf.py \
        --model_repo   <user>/<model-name>   --model_dir   <staged model dir> \
        --dataset_repo <user>/<ds-name>      --dataset_dir <staged dataset dir>

Proxy 探测失败时可用 --proxy 显式指定。
"""
import argparse
import os
import subprocess
import sys
import time


# ---------------------------------------------------------------- 代理探测
def detect_system_proxy() -> str | None:
    """读取 Windows 系统代理（WinINET）设置。

    返回形如 http://127.0.0.1:10808 ；读不到返回 None。
    注意：这只在 Windows 上有效；Linux/macOS 请用 --proxy 或环境变量。
    """
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
    except OSError:
        return None
    try:
        enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if not enable:
            return None
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)

    if not server:
        return None
    # "host:port" 或 "http=host:port;https=host:port"
    if "=" in server:
        for part in server.split(";"):
            if part.startswith("http="):
                server = part.split("=", 1)[1]
                break
        else:
            return None
    server = server.strip()
    if not server:
        return None
    if not server.startswith("http"):
        server = "http://" + server
    return server


def apply_proxy(proxy: str | None) -> None:
    if not proxy:
        print("[proxy] 未启用代理（直连）")
        return
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ[k] = proxy
    print("[proxy] 使用", proxy)


# ---------------------------------------------------------------- 上传
def upload(api, repo_type: str, repo_id: str, folder: str, message: str) -> str:
    t0 = time.time()
    print("[%s] START %s (%s) <- %s" % (time.strftime("%H:%M:%S"), repo_id, repo_type, folder),
          flush=True)
    api.create_repo(repo_id, repo_type=repo_type, exist_ok=True)
    r = api.upload_folder(
        folder_path=folder,
        repo_id=repo_id,
        repo_type=repo_type,
        commit_message=message,
    )
    print("[%s] DONE %s in %.1fs" % (time.strftime("%H:%M:%S"), repo_id, time.time() - t0),
          flush=True)
    print("    commit: %s" % r, flush=True)
    return r


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段7 上传到 HuggingFace")
    ap.add_argument("--model_repo", help="模型仓库 id，如 user/MyVoice")
    ap.add_argument("--model_dir", help="模型仓库本地目录（已暂存好要传的文件）")
    ap.add_argument("--dataset_repo", help="数据集仓库 id")
    ap.add_argument("--dataset_dir", help="数据集仓库本地目录")
    ap.add_argument("--proxy", default=None, help="代理地址；默认自动探测系统代理")
    ap.add_argument("--no_proxy", action="store_true", help="强制直连")
    ap.add_argument("--endpoint", default=None, help="HF 端点（默认官方 huggingface.co）")
    ap.add_argument("--message", default="Upload model + training artifacts")
    a = ap.parse_args()

    proxy = None if a.no_proxy else (a.proxy or detect_system_proxy())
    apply_proxy(proxy)

    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    if a.endpoint:
        os.environ["HF_ENDPOINT"] = a.endpoint

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if not token:
        print("ERROR: 未找到 HF_TOKEN，请先 export HF_TOKEN=hf_xxx", file=sys.stderr)
        raise SystemExit(2)

    try:
        import hf_transfer  # noqa: F401
    except ImportError:
        print("WARNING: 未安装 hf_transfer，上传会很慢（~150KB/s）。"
              "建议 pip install hf_transfer", file=sys.stderr)

    from huggingface_hub import HfApi
    api = HfApi(token=token)

    jobs = []
    if a.model_repo and a.model_dir:
        jobs.append(("model", a.model_repo, a.model_dir, a.message))
    if a.dataset_repo and a.dataset_dir:
        jobs.append(("dataset", a.dataset_repo, a.dataset_dir, a.message))
    if not jobs:
        print("ERROR: 至少指定一组 --model_repo/--model_dir 或 --dataset_repo/--dataset_dir",
              file=sys.stderr)
        raise SystemExit(2)

    for repo_type, repo_id, folder, msg in jobs:
        if not os.path.isdir(folder):
            print("ERROR: 目录不存在: %s" % folder, file=sys.stderr)
            raise SystemExit(2)
        try:
            upload(api, repo_type, repo_id, folder, msg)
        except Exception as e:
            print("FAIL %s: %s: %s" % (repo_id, type(e).__name__, str(e)[:500]), file=sys.stderr)
            raise SystemExit(1)

    print("ALL_UPLOADS_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
