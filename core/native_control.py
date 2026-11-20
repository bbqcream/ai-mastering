"""Set physical values using Live's readback instead of assuming a parameter taper."""

import math
import re

from .native_effects import native_name


def display_value(text, unit):
    text = text.strip().casefold().replace("−", "-").replace("∞", "inf")
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+|inf))\s*(.*)", text)
    if not match:
        raise ValueError(f"Live 표시값의 단위를 해석할 수 없습니다: {text}")
    value, suffix = float(match[1]), match[2].strip()
    factors = {
        "hz": {"hz": 1, "khz": 1000},
        "ms": {"ms": 1, "s": 1000},
        "db": {"db": 1}, "percent": {"%": 1}, "ratio": {":1": 1, ": 1": 1},
    }
    if suffix not in factors[unit]:
        raise ValueError(f"Live 표시 단위 {suffix}와 요청 단위 {unit}가 다릅니다")
    return value * factors[unit][suffix]


def validate_target(parameter, target, unit):
    if not math.isfinite(target):
        raise ValueError("유한한 목표값을 사용하세요")
    limits = {"hz": (15, 16000), "ms": (5, 300), "db": (-50, 3), "percent": (0, 120), "ratio": (1, 4)}
    if unit not in limits or not limits[unit][0] <= target <= limits[unit][1]:
        raise ValueError("권장 믹싱 파라미터 범위를 벗어났습니다")
    name = parameter["name"].casefold()
    if unit == "db" and "gain" in name and target < -3:
        raise ValueError("EQ 및 메이크업 게인 컷은 -3 dB 이상으로 제한합니다")
    if unit == "percent" and "dry/wet" in name and target > 20:
        raise ValueError("공간계 Dry/Wet은 20% 이하로 제한합니다")
    if parameter.get("is_quantized") or not parameter.get("is_enabled", True) or parameter.get("automation_state", 0):
        raise ValueError("연속형의 활성·비자동화 파라미터만 물리 단위로 조절할 수 있습니다")


async def set_physical(session, call, record, index, device_index, parameter_index, target, unit):
    initial = await call(session, "get_device_parameters", track_index=index, device_index=device_index)
    if native_name(initial["device"]) is None:
        raise ValueError("Ableton 내장 이펙트만 수정할 수 있습니다")
    parameter = next((entry for entry in initial["device"]["parameters"] if entry["index"] == parameter_index), None)
    if parameter is None:
        raise ValueError("파라미터 인덱스가 없습니다")
    validate_target(parameter, target, unit)
    # Reject a mismatched unit before moving any knob.
    display_value(parameter.get("value_string", ""), unit)
    original = parameter["value"]
    identity = (initial["device"].get("class_name"), initial["device"]["name"], parameter["name"])
    mixer = await call(session, "get_mixer", track_index=index)
    restore_output = True

    async def write(value):
        if (await call(session, "get_session_info")).get("is_playing"):
            raise RuntimeError("재생 중에는 물리 단위 매핑을 계산할 수 없습니다")
        current = await call(session, "get_device_parameters", track_index=index, device_index=device_index)
        current_parameter = next(entry for entry in current["device"]["parameters"] if entry["index"] == parameter_index)
        if (current["device"].get("class_name"), current["device"]["name"], current_parameter["name"]) != identity:
            raise RuntimeError("물리 단위 매핑 전에 디바이스가 변경되었습니다")
        record({"physical_parameter": parameter_index, "track_index": index, "device_index": device_index,
                "raw_value": value, "state": "requested"})
        await call(session, "set_device_parameter", track_index=index, device_index=device_index,
                   parameter_index=parameter_index, value=value)
        readback = await call(session, "get_device_parameters", track_index=index, device_index=device_index)
        entry = next(entry for entry in readback["device"]["parameters"] if entry["index"] == parameter_index)
        if (readback["device"].get("class_name"), readback["device"]["name"], entry["name"]) != identity:
            raise RuntimeError("물리 단위 매핑 중 디바이스가 변경되었습니다")
        record({"physical_parameter": parameter_index, "track_index": index, "device_index": device_index,
                "raw_value": entry["value"], "display": entry.get("value_string"), "state": "verified"})
        return display_value(entry.get("value_string", ""), unit), readback

    try:
        record({"physical_mapping_mute": index, "before_value": mixer["volume"]["value"]})
        await call(session, "set_track_volume", track_index=index, value=0)
        muted = await call(session, "get_mixer", track_index=index)
        if muted["name"] != mixer["name"] or muted["volume"]["value"] != 0:
            raise RuntimeError("물리 단위 매핑 전 트랙 출력을 차단하지 못했습니다")
        low, high = parameter["min"], parameter["max"]
        low_display, _ = await write(low)
        high_display, _ = await write(high)
        if not min(low_display, high_display) <= target <= max(low_display, high_display):
            raise ValueError("Live 디바이스의 표시 범위 밖인 목표값입니다")
        increasing = high_display > low_display
        tolerance = {"db": 0.1, "hz": max(1, abs(target) * 0.01), "ms": max(0.2, target * 0.02), "ratio": 0.1, "percent": 0.5}[unit]
        for _ in range(24):
            raw = (low + high) / 2
            value, readback = await write(raw)
            if abs(value - target) <= tolerance:
                return readback
            if (value < target) == increasing:
                low = raw
            else:
                high = raw
        raise ValueError("Live 표시 정밀도 내에서 목표값에 도달하지 못했습니다")
    except BaseException:
        try:
            await write(original)
        except BaseException as restore_error:
            restore_output = False
            raise RuntimeError("파라미터 매핑 실패 후 이전값 복구를 확인하지 못했습니다") from restore_error
        raise
    finally:
        if not restore_output:
            record({"physical_mapping_restore_failed": index, "output": "muted"})
            raise RuntimeError("이펙트 값 복구 실패로 트랙 출력을 차단한 상태를 유지합니다")
        current_mixer = await call(session, "get_mixer", track_index=index)
        if current_mixer["name"] != mixer["name"]:
            raise RuntimeError("물리 단위 매핑 후 트랙 순서가 변경되어 출력 복구를 중단합니다")
        await call(session, "set_track_volume", track_index=index, value=mixer["volume"]["value"])
        restored = await call(session, "get_mixer", track_index=index)
        if restored["name"] != mixer["name"] or abs(restored["volume"]["value"] - mixer["volume"]["value"]) > 0.001:
            raise RuntimeError("물리 단위 매핑 후 트랙 출력 복구를 확인하지 못했습니다")
        record({"physical_mapping_restore": index, "value": restored["volume"]["value"]})
