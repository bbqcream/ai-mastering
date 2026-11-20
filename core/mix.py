"""Stem-level mix planning and rendering."""
import json
from pathlib import Path

import numpy as np

from .io import load_audio
from .master import analyze, render
from .master.analyze import UnmeasurableLoudness
from .roles import PROFILES, classify_track, track_pan
from .types import Adjustment

SUPPORTED = {".wav", ".aif", ".aiff", ".flac"}


def suggest_mix(stem_dir, max_gain_db=6.0):
    folder = Path(stem_dir)
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
    if not paths:
        raise ValueError(f"스템 폴더에 WAV/AIFF/FLAC 파일이 없습니다: {folder}")

    measured = []
    alignment = None
    for path in paths:
        audio, sample_rate = load_audio(path)
        _validate_audio(audio, path.name)
        key = (sample_rate, len(audio))
        if alignment is not None and key != alignment:
            raise ValueError(f"스템이 정렬되지 않았습니다: {path.name}")
        alignment = key
        # Loudness uses 400 ms blocks. Pad only the analysis of short clips.
        result = None
        if np.any(audio):
            pad = max(0, int(np.ceil(sample_rate * 0.4)) - len(audio))
            padded = np.pad(audio, ((0, pad), (0, 0))) if pad else audio
            try:
                result = analyze(padded, sample_rate)
            except UnmeasurableLoudness:
                pass
        measured.append((path, audio.shape[1], result))

    levels = [result["lufs"] for _, _, result in measured if result is not None]
    if not levels:
        raise ValueError("라우드니스를 측정할 수 있는 스템이 없습니다")
    target_lufs = float(np.median(levels))
    tracks = []
    positions = {}
    for path, channels, result in measured:
        role = classify_track(path.stem)
        profile = PROFILES[role]
        gain_db, pan = 0.0, 0.0
        effects = []
        if result is not None and role != "unknown":
            gain_db = float(np.clip(target_lufs + profile.level - result["lufs"], -max_gain_db, max_gain_db))
            gain_db = min(gain_db, max(0.0, -3.0 - result["true_peak_db"]))
            effects = _suggest_effects(profile, result, alignment[0])
            if channels == 1:
                position = positions.get(role, 0)
                pan = track_pan(path.stem, profile, position)
                positions[role] = position + 1
        tracks.append({
            "name": path.stem,
            "file": path.name,
            "role": role,
            "gain_db": round(gain_db, 1),
            "pan": pan,
            "effects": effects,
            "analysis": result or {},
            "reason": (
                "무음 또는 측정 한계 이하, 개별 조정 생략" if result is None else
                "트랙명에서 역할을 식별하지 못해 개별 조정 생략" if role == "unknown" else
                f"{role} 목표 {target_lufs + profile.level:.1f} LUFS와 피크 여유 기준"
            ),
        })
    return {"target_lufs": target_lufs, "peak_ceiling_db": -6.0, "tracks": tracks}


def _suggest_effects(profile, result, sample_rate):
    effects = []
    if 0 < profile.highpass < sample_rate / 2:
        effects.append({"effect": "highpass", "params": {"freq": profile.highpass}})
    if profile.eq_band and 0 < profile.eq_freq < sample_rate / 2:
        # A relative cut is only made when the selected band is prominent.
        band_db = result["bands_db"][profile.eq_band]
        if band_db > -10:
            cut = -min(2.5, (band_db + 10) / 3)
            effects.append({"effect": "eq_peak", "params": {
                "freq": profile.eq_freq, "gain_db": round(cut, 1), "q": 0.9,
            }})
    if profile.ratio > 1 and result["plr_db"] > 12:
        effects.append({"effect": "compressor", "params": {
            "threshold_db": round(max(-60, result["true_peak_db"] - 6), 1),
            "ratio": profile.ratio, "attack_ms": profile.attack_ms, "release_ms": profile.release_ms,
        }})
    return effects


def _validate_audio(audio, filename):
    if audio.shape[1] not in (1, 2):
        raise ValueError(f"{filename}: 모노 또는 스테레오 스템만 지원합니다")
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError(f"{filename}: 오디오 샘플이 비어 있거나 유효하지 않습니다")


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
        _validate_audio(audio, filename)
        if sample_rate is None:
            sample_rate = sr
            output = np.zeros((len(audio), 2), dtype=np.float32)
        elif sr != sample_rate or len(audio) != len(output):
            raise ValueError(f"스템이 정렬되지 않았습니다: {filename}")
        adjustments = []
        for entry in track.get("effects", []):
            effect = entry.get("effect")
            params = entry.get("params", {})
            if effect not in {"highpass", "eq_peak", "compressor"}:
                raise ValueError(f"{name}: 지원하지 않는 트랙 이펙트 {effect}")
            adjustments.append(Adjustment(name, effect, params, "악기별 믹스"))
        audio, _ = render(audio, sr, adjustments)
        audio = audio * np.float32(10 ** (gain_db / 20.0))
        if audio.shape[1] == 1:
            angle = (pan + 1.0) * np.pi / 4.0
            stereo = np.column_stack((audio[:, 0] * np.cos(angle), audio[:, 0] * np.sin(angle)))
        else:
            left_gain = 1.0 - max(0.0, pan)
            right_gain = 1.0 + min(0.0, pan)
            stereo = audio * np.array([left_gain, right_gain], dtype=np.float32)
        output += stereo

    ceiling_db = float(plan.get("peak_ceiling_db", 20 * np.log10(0.99)))
    if not np.isfinite(ceiling_db) or not -24.0 <= ceiling_db <= 0.0:
        raise ValueError("peak_ceiling_db는 -24~0dBFS 범위여야 합니다")
    ceiling = 10 ** (ceiling_db / 20.0)
    peak = float(np.max(np.abs(output)))
    safety_gain_db = 0.0
    if peak > ceiling:
        safety_gain_db = 20.0 * np.log10(ceiling / peak)
        output *= np.float32(10 ** (safety_gain_db / 20.0))
    return output, sample_rate, {"safety_gain_db": safety_gain_db}
