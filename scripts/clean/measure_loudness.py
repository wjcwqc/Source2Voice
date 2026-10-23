# -*- coding: utf-8 -*-
"""批量测量 .list 清单中每条 WAV 的响度指标(EBU R128)。

输入: GPT-SoVITS 格式 .list  (wav路径|speaker|lang|text)
输出: CSV  (path,name,duration,sr,channels,width,I_lufs,lra_lu,true_peak_dbfs,
           thresh_lufs,ffmpeg_ok,notes)

并合并 cosyvoice report.csv 中已有的 rms_db/peak/clip_frac/zcr/flags/bucket。
"""
import csv
import json
import re
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

FFMPEG = r"C:\Program Files (x86)\FormatFactory\FFModules\Encoder\ffmpeg.exe"
LIST = r"D:\DarkWillow_VoiceDataset\metadata\schinese_dark_willow_vo_pure.list.bak"
REPORT = r"D:\dwvits\data\cosyvoice_dark_willow_all\report.csv"
OUT = r"D:\DarkWillow_VoiceDataset\metadata\refined\measure.csv"
WORKERS = 8

RE_I = re.compile(r"I:\s*(-?\d+\.?\d*)\s*LUFS")
RE_THRESH = re.compile(r"Threshold:\s*(-?\d+\.?\d*)\s*LUFS")
RE_LRA = re.compile(r"LRA:\s*(-?\d+\.?\d*)\s*LU")
RE_PEAK = re.compile(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS")


def measure_one(path: str):
    row = {"path": path, "name": Path(path).stem, "ffmpeg_ok": 0, "notes": ""}
    # 容器信息 + 时长
    try:
        with wave.open(path, "rb") as w:
            row["sr"] = w.getframerate()
            row["channels"] = w.getnchannels()
            row["width"] = w.getsampwidth()
            row["duration"] = round(w.getnframes() / float(w.getframerate()), 4)
    except Exception as e:
        row["notes"] = f"wave_open_fail:{e}"
        return row
    # EBU R128
    cmd = [FFMPEG, "-nostats", "-hide_banner", "-i", path,
           "-filter_complex", "ebur128=peak=true", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           errors="replace")
        tail = p.stderr[-3000:]
        summary = tail[tail.rfind("Summary:"):]
        m_i = RE_I.search(summary)
        m_lra = RE_LRA.search(summary)
        m_peak = RE_PEAK.findall(summary)
        m_th = RE_THRESH.search(summary)
        if m_i:
            row["I_lufs"] = float(m_i.group(1))
            row["lra_lu"] = float(m_lra.group(1)) if m_lra else ""
            # peak=true 时最后一个 Peak 是 true peak
            row["true_peak_dbfs"] = float(m_peak[-1]) if m_peak else ""
            row["thresh_lufs"] = float(m_th.group(1)) if m_th else ""
            row["ffmpeg_ok"] = 1
        else:
            row["notes"] = "no_summary"
    except Exception as e:
        row["notes"] = f"ffmpeg_fail:{e}"
    return row


def main():
    entries = []
    with open(LIST, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            entries.append((parts[0], parts[3] if len(parts) > 3 else ""))
    print(f"list entries: {len(entries)}")

    # 读取 cosyvoice report 以供合并
    report = {}
    if Path(REPORT).exists():
        with open(REPORT, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                report[Path(r["src"]).stem] = r
    print(f"report rows: {len(report)}")

    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(measure_one, p): p for p, _ in entries}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results[r["name"]] = r
            done += 1
            if done % 150 == 0:
                print(f"  {done}/{len(entries)}")

    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "path", "text", "duration", "sr", "channels", "width",
              "I_lufs", "thresh_lufs", "lra_lu", "true_peak_dbfs",
              "rms_db", "peak_lin", "clip_frac", "zcr", "flags",
              "audio_outlier", "bucket", "ffmpeg_ok", "notes"]
    n_fail = 0
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p, text in entries:
            name = Path(p).stem
            r = results.get(name, {"name": name, "path": p, "ffmpeg_ok": 0,
                                   "notes": "missing"})
            rep = report.get(name, {})
            row = {k: r.get(k, "") for k in
                   ["name", "path", "duration", "sr", "channels", "width",
                    "I_lufs", "thresh_lufs", "lra_lu", "true_peak_dbfs",
                    "ffmpeg_ok", "notes"]}
            row["text"] = text
            row["rms_db"] = rep.get("rms_db", "")
            row["peak_lin"] = rep.get("peak", "")
            row["clip_frac"] = rep.get("clip_frac", "")
            row["zcr"] = rep.get("zcr", "")
            row["flags"] = (rep.get("flags", "") or "").strip('"')
            row["audio_outlier"] = rep.get("audio_outlier", "")
            row["bucket"] = rep.get("bucket", "")
            if not row["ffmpeg_ok"]:
                n_fail += 1
            w.writerow(row)
    print(f"wrote {OUT}, ffmpeg_fail={n_fail}")


if __name__ == "__main__":
    main()
