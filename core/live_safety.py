"""Measured gain protection independent of model decisions."""

import math

from .native_effects import native_name


class CaptureOverload(RuntimeError):
    pass


def audition_ranges(start, end):
    """Sample the beginning, middle and ending, avoiding overlapping short songs."""
    length = min(16, end - start)
    starts = [start, start + (end - start - length) / 2, end - length]
    selected = []
    for position in starts:
        if not selected or position - selected[-1][0] >= length:
            selected.append((position, position + length))
    return selected


class GainProtection:
    def __init__(self, session, call, record):
        self.session = session
        self.call = call
        self.record = record
        self.changes = 0
        self.mixers = {}

    async def attenuate(self, reduction_db, index=0, track_type="master", expected_name=None):
        before = await self.call(self.session, "get_mixer", track_index=index, track_type=track_type)
        if expected_name is not None and before["name"] != expected_name:
            raise RuntimeError("보호 처리 중 트랙 순서가 변경되었습니다")
        db = before["volume"].get("db")
        if db is None or not math.isfinite(db):
            raise RuntimeError("피크 보호에 필요한 페이더 dB를 읽을 수 없습니다")
        target = max(-60, db - max(0, reduction_db))
        if target >= db - 0.05:
            raise RuntimeError("페이더를 더 낮출 수 없습니다. 입력 또는 이펙트 게인을 확인하세요")
        self.record({"protection": "attenuate", "track_type": track_type, "track_index": index,
                     "name": before["name"], "before_db": db, "target_db": target, "state": "requested"})
        self.changes += 1
        await self.call(self.session, "set_track_volume", track_index=index, track_type=track_type, db=target)
        after = await self.call(self.session, "get_mixer", track_index=index, track_type=track_type)
        actual = after["volume"].get("db")
        if after["name"] != before["name"] or actual is None or not math.isfinite(actual) or abs(actual - target) > 0.1:
            raise RuntimeError("피크 보호 페이더 적용값을 확인하지 못했습니다")
        self.record({"protection": "attenuate", "track_type": track_type, "track_index": index,
                     "name": before["name"], "before_db": db, "after_db": actual, "state": "verified"})
        self.mixers[(track_type, index)] = after
        return after

    async def check(self, start, end):
        """Meter samples are approximate. Reserve 6 dB of master headroom."""
        for _ in range(4):
            result = await self.call(self.session, "measure_mix", start_beats=start,
                                     length_beats=min(8, end - start), target_db=-6)
            self.record({"protection": "meter_scan", "measurement": result})
            sources = [track for track in result.get("tracks", [])
                       if not track.get("is_group") and track.get("peak_db") is not None
                       and track["peak_db"] > -3]
            if sources:
                for track in sources:
                    await self.attenuate(track["peak_db"] + 3.5, track["index"], "track", track["name"])
                continue
            groups = [track for track in result.get("tracks", [])
                      if track.get("is_group") and track.get("peak_db") is not None and track["peak_db"] > -3]
            if groups:
                for track in groups:
                    await self.attenuate(track["peak_db"] + 3.5, track["index"], "track", track["name"])
                continue
            peak = result.get("master_peak_db")
            if peak is None or peak <= -6:
                return result
            await self.attenuate(peak + 6.5)
        raise RuntimeError("반복 감쇠 후에도 피크가 높습니다. 보호를 위해 자동 믹싱을 중단합니다")


def validate_parameter(device, parameter, value):
    """Bound risky model moves using actual device metadata and parameter units."""
    if native_name(device) is None:
        raise ValueError("지원하는 Ableton 내장 오디오 이펙트만 수정할 수 있습니다")
    if not math.isfinite(value) or not parameter["min"] <= value <= parameter["max"]:
        raise ValueError("디바이스 파라미터 범위 오류")
    if not parameter.get("is_enabled", True) or parameter.get("automation_state", 0):
        raise ValueError("비활성 또는 자동화된 파라미터는 수정할 수 없습니다")
    if parameter.get("is_quantized") and value != int(value):
        raise ValueError("선택형 파라미터에는 정수 값을 사용하세요")
    name = parameter["name"].casefold()
    minimum, maximum = parameter["min"], parameter["max"]
    if minimum == 0 and maximum == 1 and not parameter.get("is_quantized"):
        if abs(value - parameter["value"]) > 0.15:
            raise ValueError("정규화된 파라미터는 한 번에 0.15 이하로 조정하세요")
    if "gain" in name and minimum < 0 and value > 3:
        raise ValueError("이펙트 게인 부스트는 +3 dB 이하로 제한합니다")
    if "ratio" in name and maximum > 4 and value > 4:
        raise ValueError("컴프레션 비율은 4:1 이하로 제한합니다")
    if "dry/wet" in name and maximum > 1 and value > 20:
        raise ValueError("공간계 Dry/Wet은 20% 이하로 제한합니다")
