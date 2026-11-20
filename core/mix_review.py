"""Objective regression checks and potential spectral overlap for AI decisions."""

from itertools import combinations


def technical_regressions(before, after, role="unknown", expected_gain_db=0):
    """Reject large technical damage without treating a score as listening quality."""
    if before.get("silent"):
        return []
    if after.get("silent"):
        return ["처리 후 측정 가능한 신호가 사라졌습니다"]
    reasons = []
    if "lufs" in before and "lufs" in after and before["lufs"] + expected_gain_db - after["lufs"] > 12:
        reasons.append("의도한 게인 조절 외에 라우드니스가 12 LU 넘게 감소했습니다")
    if after.get("full_scale_fraction", 0) > max(0.001, before.get("full_scale_fraction", 0) + 0.0005):
        reasons.append("풀스케일 샘플 비율이 증가했습니다")
    if before.get("crest_db", 0) - after.get("crest_db", 0) > 6:
        reasons.append("크레스트 팩터가 6 dB 넘게 줄어 트랜지언트 손상이 의심됩니다")
    before_corr = before.get("stereo_correlation")
    after_corr = after.get("stereo_correlation")
    if before_corr is not None and after_corr is not None and after_corr < -0.2 and before_corr - after_corr > 0.35:
        reasons.append("스테레오 상관도가 크게 악화되었습니다")
    # Band ratios survive uniform gain changes, including automatic headroom trims.
    if role in {"kick", "bass"}:
        old_bands, new_bands = before.get("bands_db", {}), after.get("bands_db", {})
        for band in ("sub", "low"):
            if old_bands.get(band, -120) > -12 and old_bands[band] - new_bands.get(band, -120) > 9:
                reasons.append(f"{band} 대역의 상대 에너지가 9 dB 넘게 줄었습니다")
    return reasons


def masking_context(tracks):
    """Rank candidate conflicts. Average spectra alone cannot prove audible masking."""
    conflicts = []
    accompaniment = {"guitar", "keys", "lead_synth", "pad", "strings", "winds"}
    for first, second in combinations(tracks, 2):
        roles = {first.get("role"), second.get("role")}
        if roles != {"kick", "bass"} and not ("lead_vocal" in roles and roles.intersection(accompaniment)):
            continue
        a, b = first.get("analysis", {}), second.get("analysis", {})
        if a.get("silent") or b.get("silent") or "lufs" not in a or "lufs" not in b:
            continue
        spectrum_a, spectrum_b = a.get("spectrum_db", {}), b.get("spectrum_db", {})
        candidates = []
        for center in spectrum_a.keys() & spectrum_b.keys():
            frequency = float(center)
            if roles == {"kick", "bass"} and frequency > 300:
                continue
            level_a = a["lufs"] + spectrum_a[center]
            level_b = b["lufs"] + spectrum_b[center]
            if min(spectrum_a[center], spectrum_b[center]) < -20 or abs(level_a - level_b) > 8:
                continue
            candidates.append((min(level_a, level_b), center, level_a - level_b))
        if not candidates:
            continue
        _, center, difference = max(candidates)
        conflicts.append({
            "tracks": [first["name"], second["name"]], "roles": [first["role"], second["role"]],
            "candidate_hz": float(center), "approximate_level_difference_db": round(difference, 1),
            "interpretation": "Potential spectral overlap. Separate solo captures do not prove simultaneous masking. Check the mix and preserve each instrument's fundamental before complementary EQ cuts.",
        })
    return conflicts
