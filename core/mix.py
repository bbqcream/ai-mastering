"""Stem-level mix planning and rendering."""
import json
from pathlib import Path

import numpy as np

from .io import load_audio
from .master.analyze import analyze

SUPPORTED = {".wav", ".aif", ".aiff", ".flac"}


def suggest_mix(stem_dir, max_gain_db=6.0):
    folder = Path(stem_dir)
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
    if not paths:
        raise ValueError(f"스템 폴더에 WAV/AIFF/FLAC 파일이 없습니다: {folder}")

    measured = []
    for path in paths:
        audio, sample_rate = load_audio(path)
        measured.append((path, analyze(audio, sample_rate)))

    target_lufs = float(np.median([result["lufs"] for _, result in measured]))
    tracks = []
    for path, result in measured:
        gain_db = float(np.clip(target_lufs - result["lufs"], -max_gain_db, max_gain_db))
        tracks.append({
            "name": path.stem,
            "file": path.name,
            "gain_db": round(gain_db, 1),
            "pan": 0.0,
            "analysis": result,
            "reason": f"스템 중앙값 {target_lufs:.1f} LUFS 기준 초기 게인 스테이징",
        })
    return {"target_lufs": target_lufs, "tracks": tracks}


def load_mix_plan(path):
    with Path(path).open(encoding="utf-8") as file:
        plan = json.load(file)
    if not isinstance(plan.get("tracks"), list) or not plan["tracks"]:
        raise ValueError("믹스 플랜에 tracks 목록이 없습니다")
    return plan


def save_mix_plan(path, plan):
    with Path(path).open("w", encoding="utf-8") as file:
        json.dump(plan, file, ensure_ascii=False, indent=2)
        file.write("\n")


def render_mix(stem_dir, plan):
    folder = Path(stem_dir)
    output = None
    sample_rate = None
    names = set()

    for track in plan["tracks"]:
        name = track.get("name")
        filename = track.get("file")
        gain_db = float(track.get("gain_db", 0.0))
        pan = float(track.get("pan", 0.0))
        if not name or not filename or name in names:
            raise ValueError("각 트랙은 중복되지 않는 name과 file이 필요합니다")
        if not np.isfinite(gain_db) or not -24.0 <= gain_db <= 24.0:
            raise ValueError(f"{name}: gain_db는 -24~24dB 범위여야 합니다")
        if not np.isfinite(pan) or not -1.0 <= pan <= 1.0:
            raise ValueError(f"{name}: pan은 -1(왼쪽)~1(오른쪽) 범위여야 합니다")
        names.add(name)

        audio, sr = load_audio(folder / filename)
        if sample_rate is None:
            sample_rate = sr
            output = np.zeros((len(audio), 2), dtype=np.float32)
        elif sr != sample_rate or len(audio) != len(output):
            raise ValueError(f"스템이 정렬되지 않았습니다: {filename}")
        if audio.shape[1] not in (1, 2):
            raise ValueError(f"{filename}: 모노 또는 스테레오 스템만 지원합니다")

        audio = audio * np.float32(10 ** (gain_db / 20.0))
        if audio.shape[1] == 1:
            angle = (pan + 1.0) * np.pi / 4.0
            stereo = np.column_stack((audio[:, 0] * np.cos(angle), audio[:, 0] * np.sin(angle)))
        else:
            left_gain = 1.0 - max(0.0, pan)
            right_gain = 1.0 + min(0.0, pan)
            stereo = audio * np.array([left_gain, right_gain], dtype=np.float32)
        output += stereo

    peak = float(np.max(np.abs(output)))
    safety_gain_db = 0.0
    if peak > 0.99:
        safety_gain_db = 20.0 * np.log10(0.99 / peak)
        output *= np.float32(10 ** (safety_gain_db / 20.0))
    return output, sample_rate, {"safety_gain_db": safety_gain_db}