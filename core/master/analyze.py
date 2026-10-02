"""마스터링 분석: 라우드니스, 트루피크, 대역별 밸런스."""
import numpy as np
import pyloudnorm as pyln
from scipy.signal import resample_poly, welch

BANDS = {
    "sub": (20, 60),
    "low": (60, 250),
    "low_mid": (250, 500),
    "mid": (500, 2000),
    "high_mid": (2000, 6000),
    "high": (6000, 16000),
}


def _db(x):
    return 20 * np.log10(max(float(x), 1e-12))


def true_peak_db(y):
    """4배 오버샘플링으로 트루피크(dBTP)를 근사 측정."""
    over = resample_poly(y, 4, 1, axis=0)
    return _db(np.max(np.abs(over)))


def band_balance(y, sr):
    """전체 에너지 대비 각 대역 에너지(dB). 곡 전체 평균 스펙트럼 기준."""
    mono = y.mean(axis=1)
    freqs, psd = welch(mono, fs=sr, nperseg=8192)
    total = psd[(freqs >= 20) & (freqs < 16000)].sum() + 1e-20
    out = {}
    for name, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        out[name] = float(10 * np.log10(psd[mask].sum() / total + 1e-12))
    return out


def analyze(y, sr):
    y64 = y.astype(np.float64)
    lufs = float(pyln.Meter(sr).integrated_loudness(y64))
    if not np.isfinite(lufs):
        raise ValueError("라우드니스를 측정할 수 없어요 (무음이거나 너무 짧은 파일)")
    tp = float(true_peak_db(y64))
    return {
        "lufs": lufs,
        "sample_peak_db": float(_db(np.max(np.abs(y64)))),
        "true_peak_db": tp,
        "plr_db": tp - lufs,  # 피크 대 라우드니스 비율(다이내믹 여유)
        "bands_db": band_balance(y64, sr),
    }
