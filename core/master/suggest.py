"""분석 결과 -> 조정안(Adjustment) 목록. 지금은 규칙 기반.

나중에 이 함수만 LLM/학습 모델 호출로 바꿔도 나머지 구조는 그대로다.
아래 수치들은 출발점으로 잡은 휴리스틱이라, 내 곡으로 들어보며 조정해야 한다.
"""
import numpy as np

from ..types import Adjustment

# sub 대역은 EQ 대신 하이패스로 다룬다.
EQ_BANDS = {
    "low": ("eq_low_shelf", 150.0),
    "low_mid": ("eq_peak", 350.0),
    "mid": ("eq_peak", 1000.0),
    "high_mid": ("eq_peak", 3500.0),
    "high": ("eq_high_shelf", 8000.0),
}
LABEL = {"low": "저역", "low_mid": "중저역", "mid": "중역", "high_mid": "중고역", "high": "고역"}

MAX_EQ_DB = 3.0  # 한 번에 건드리는 EQ 최대 폭
STRENGTH = 0.5  # 참고곡과의 차이 중 절반만 보정
MIN_DIFF_DB = 1.0  # 이보다 작은 차이는 무시


def suggest(analysis, ref_analysis=None, target_lufs=-14.0, ceiling_db=-1.0):
    adjustments = [
        Adjustment("master", "highpass", {"freq": 25.0}, "25Hz 이하 초저역을 정리해 헤드룸을 확보"),
    ]

    if ref_analysis is not None:
        adjustments += _eq_from_reference(analysis, ref_analysis)

    comp = _compressor(analysis, target_lufs, ceiling_db)
    if comp:
        adjustments.append(comp)

    adjustments.append(
        Adjustment(
            "master",
            "limiter",
            {"target_lufs": target_lufs, "ceiling_db": ceiling_db},
            f"{target_lufs:g} LUFS에 맞추고 트루피크를 {ceiling_db:g}dBTP 이하로 제한",
        )
    )
    return adjustments


def _eq_from_reference(a, ref):
    names = list(EQ_BANDS)
    diffs = np.array([ref["bands_db"][n] - a["bands_db"][n] for n in names])
    # 전체 레벨 차이(공통 오프셋)는 제거하고 '모양' 차이만 본다.
    diffs = diffs - np.median(diffs)

    out = []
    for name, d in zip(names, diffs):
        if abs(d) < MIN_DIFF_DB:
            continue
        gain = float(np.clip(d * STRENGTH, -MAX_EQ_DB, MAX_EQ_DB))
        effect, freq = EQ_BANDS[name]
        word = "부족" if d > 0 else "과다"
        out.append(
            Adjustment(
                "master",
                effect,
                {"freq": freq, "gain_db": round(gain, 1), "q": 0.7},
                f"참고곡 대비 {LABEL[name]}이 약 {abs(d):.1f}dB {word} -> {gain:+.1f}dB (차이의 절반만 보정)",
            )
        )
    return out


def _compressor(a, target_lufs, ceiling_db):
    target_plr = ceiling_db - target_lufs  # 목표 라우드니스에서 허용되는 피크 여유
    excess = a["plr_db"] - target_plr
    if excess <= 3.0:
        return None
    ratio = 1.5 if excess < 6 else 2.0
    return Adjustment(
        "master",
        "compressor",
        {"threshold_db": round(a["lufs"] + 4, 1), "ratio": ratio, "attack_ms": 30.0, "release_ms": 200.0},
        f"PLR {a['plr_db']:.1f}dB가 목표({target_plr:.1f}dB)보다 커서 리미터 부담을 줄이려 가벼운 컴프레션",
    )
