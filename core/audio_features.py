"""Audio evidence supplied to the local mixing model."""

import numpy as np

from .master.analyze import UnmeasurableLoudness, analyze


def measure_audio(audio, sample_rate):
    if audio.ndim != 2 or audio.shape[1] not in (1, 2) or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("유효한 모노/스테레오 오디오가 필요합니다")
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    pad = max(0, int(np.ceil(sample_rate * 0.4)) - len(audio))
    try:
        result = analyze(np.pad(audio, ((0, pad), (0, 0))), sample_rate)
    except UnmeasurableLoudness:
        result = {"silent": True}
    result.update({
        "rms_dbfs": float(20 * np.log10(max(rms, 1e-12))),
        "crest_db": float(20 * np.log10(max(peak, 1e-12) / max(rms, 1e-12))),
        "full_scale_fraction": float(np.mean(np.abs(audio) >= 0.999)),
        "dc_offset": [float(value) for value in np.mean(audio, axis=0)],
    })
    if audio.shape[1] == 2:
        left, right = audio.astype(np.float64).T
        mid, side = (left + right) / 2, (left - right) / 2
        result["side_to_mid_db"] = float(10 * np.log10((np.mean(side ** 2) + 1e-20) / (np.mean(mid ** 2) + 1e-20)))
        denominator = np.std(left) * np.std(right)
        result["stereo_correlation"] = float(np.mean((left - left.mean()) * (right - right.mean())) / denominator) if denominator > 1e-15 else 0.0
    return result
