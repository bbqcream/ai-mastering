"""조정안(Adjustment)을 실제 오디오에 적용한다."""
import numpy as np
import pyloudnorm as pyln
from pedalboard import (
    Compressor,
    Gain,
    HighpassFilter,
    HighShelfFilter,
    Limiter,
    LowShelfFilter,
    Pedalboard,
    PeakFilter,
)

from .analyze import true_peak_db


def _process(board, y, sr):
    """y: (samples, channels). pedalboard는 (channels, samples)를 쓴다."""
    x = np.ascontiguousarray(y.T, dtype=np.float32)
    out = board(x, sr)
    return np.ascontiguousarray(out.T)


def _plugin(adj):
    p = adj.params
    if adj.effect == "highpass":
        return HighpassFilter(cutoff_frequency_hz=p["freq"])
    if adj.effect == "eq_low_shelf":
        return LowShelfFilter(cutoff_frequency_hz=p["freq"], gain_db=p["gain_db"], q=p.get("q", 0.7))
    if adj.effect == "eq_high_shelf":
        return HighShelfFilter(cutoff_frequency_hz=p["freq"], gain_db=p["gain_db"], q=p.get("q", 0.7))
    if adj.effect == "eq_peak":
        return PeakFilter(cutoff_frequency_hz=p["freq"], gain_db=p["gain_db"], q=p.get("q", 0.7))
    if adj.effect == "compressor":
        return Compressor(
            threshold_db=p["threshold_db"],
            ratio=p["ratio"],
            attack_ms=p.get("attack_ms", 30.0),
            release_ms=p.get("release_ms", 200.0),
        )
    raise ValueError(f"알 수 없는 effect: {adj.effect}")


def _loudness_stage(y, sr, target_lufs, ceiling_db, max_iter=6):
    """게인 + 리미터를 반복 조정해 타깃 LUFS와 트루피크 상한을 동시에 맞춘다.

    리미터가 걸리면 라우드니스가 기대보다 덜 올라가고 트루피크도 샘플 피크보다
    조금 넘칠 수 있어서, 측정 -> 보정을 몇 번 반복한다.
    """
    meter = pyln.Meter(sr)
    gain_db = target_lufs - meter.integrated_loudness(y.astype(np.float64))
    threshold = ceiling_db - 0.3

    out = y
    for _ in range(max_iter):
        board = Pedalboard([Gain(gain_db), Limiter(threshold_db=threshold, release_ms=100.0)])
        out = _process(board, y, sr)
        lufs = meter.integrated_loudness(out.astype(np.float64))
        tp = true_peak_db(out.astype(np.float64))

        tp_ok = tp <= ceiling_db + 0.05
        lufs_ok = abs(lufs - target_lufs) <= 0.2
        if tp_ok and lufs_ok:
            break
        if not tp_ok:
            threshold -= (tp - ceiling_db) + 0.05
        if not lufs_ok:
            gain_db += target_lufs - lufs

    # 마지막 안전장치: 그래도 넘치면 게인을 살짝 내려서 상한을 지킨다.
    tp = true_peak_db(out.astype(np.float64))
    trimmed = 0.0
    if tp > ceiling_db:
        trimmed = ceiling_db - tp
        out = out * float(10 ** (trimmed / 20))
    return out, {"pre_limiter_gain_db": float(gain_db), "trim_db": float(trimmed)}


def render(y, sr, adjustments):
    approved = [a for a in adjustments if a.approved]

    chain = [_plugin(a) for a in approved if a.effect != "limiter"]
    out = _process(Pedalboard(chain), y, sr) if chain else y

    info = {}
    limiter = next((a for a in approved if a.effect == "limiter"), None)
    if limiter:
        out, info = _loudness_stage(
            out, sr, limiter.params["target_lufs"], limiter.params["ceiling_db"]
        )
    return out, info
