#!/usr/bin/env python3
"""OmniVoice TTS HTTP service (Dark Willow fine-tuned model).

Works on both Linux servers and Windows. Single-process, one model in memory.

Endpoints:
    GET  /health                 -> {"status": "ok", "model": ...}
    POST /tts                    -> audio/wav bytes
         JSON body: {
             "text": "...",                 # required
             "language": "zh",              # optional
             "ref_audio_b64": "...",        # optional base64 wav for cloning
             "ref_text": "...",             # required if ref_audio_b64 given
             "instruct": "...",             # optional voice-design style
             "speed": 1.0, "num_step": 32,
             "guidance_scale": 2.0
         }
    POST /tts_file               -> {"path": "<saved wav path>", "seconds": x}
         same body as /tts, but saves to --out_dir and returns the path

Usage:
    python omnivoice_server.py --model <exp>/omnivoice_dark_willow_merged \
        --device cuda:0 --dtype fp16 --host 0.0.0.0 --port 8124

Env alternatives: OMNIVOICE_MODEL / OMNIVOICE_DEVICE / OMNIVOICE_DTYPE
"""
import argparse
import base64
import io
import os
import sys
import tempfile
import time

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from omnivoice.models.omnivoice import OmniVoice
from omnivoice.utils.lora import load_lora_adapter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402


class TtsRequest(BaseModel):
    text: str
    language: str | None = None
    ref_audio_b64: str | None = None
    ref_text: str | None = None
    instruct: str | None = None
    speed: float = 1.0
    num_step: int = 32
    guidance_scale: float = 2.0


def build_app(model_path: str, device: str, dtype: str, lora_adapter: str | None,
              out_dir: str) -> FastAPI:
    app = FastAPI(title="OmniVoice TTS", version="1.0")
    dt = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[dtype]
    print(f"[server] loading {model_path} on {device} ({dtype}) ...")
    model = OmniVoice.from_pretrained(model_path, device_map=device, dtype=dt)
    if lora_adapter:
        print(f"[server] applying adapter {lora_adapter}")
        model = load_lora_adapter(model, lora_adapter)
    print("[server] ready")

    def _generate(req: TtsRequest):
        kwargs = {}
        if req.ref_audio_b64:
            if not req.ref_text:
                raise HTTPException(400, "ref_text is required with ref_audio_b64")
            raw = base64.b64decode(req.ref_audio_b64)
            tmp = os.path.join(tempfile.gettempdir(), "omnivoice_ref.wav")
            with open(tmp, "wb") as f:
                f.write(raw)
            kwargs["ref_audio"] = tmp
            kwargs["ref_text"] = req.ref_text
        if req.instruct:
            kwargs["instruct"] = req.instruct
        t0 = time.time()
        audios = model.generate(
            text=req.text,
            language=req.language,
            speed=req.speed,
            num_step=req.num_step,
            guidance_scale=req.guidance_scale,
            **kwargs,
        )
        gen_s = time.time() - t0
        return audios[0], gen_s

    @app.get("/health")
    def health():
        return {"status": "ok", "model": model_path, "device": device, "dtype": dtype}

    @app.post("/tts")
    def tts(req: TtsRequest):
        audio, gen_s = _generate(req)
        buf = io.BytesIO()
        sf.write(buf, audio, model.sampling_rate, format="WAV")
        return Response(
            content=buf.getvalue(),
            media_type="audio/wav",
            headers={"X-Gen-Seconds": f"{gen_s:.2f}",
                     "X-Audio-Seconds": f"{len(audio)/model.sampling_rate:.2f}"},
        )

    @app.post("/tts_file")
    def tts_file(req: TtsRequest):
        audio, gen_s = _generate(req)
        os.makedirs(out_dir, exist_ok=True)
        name = f"tts_{int(time.time()*1000)}.wav"
        path = os.path.join(out_dir, name)
        sf.write(path, audio, model.sampling_rate)
        return {"path": path, "seconds": round(len(audio) / model.sampling_rate, 2),
                "gen_seconds": round(gen_s, 2)}

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get(
        "OMNIVOICE_MODEL", os.path.join(s2v_config.EXP_DIR, "omnivoice_dark_willow_merged")))
    ap.add_argument("--lora_adapter", default=None)
    ap.add_argument("--device", default=os.environ.get("OMNIVOICE_DEVICE", "cuda:0"))
    ap.add_argument("--dtype", default=os.environ.get("OMNIVOICE_DTYPE", "fp16"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8124)
    ap.add_argument("--out_dir", default=os.path.join(
        s2v_config.OUT_DIR, "omnivoice_dark_willow", "server"))
    args = ap.parse_args()

    app = build_app(args.model, args.device, args.dtype, args.lora_adapter, args.out_dir)
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
