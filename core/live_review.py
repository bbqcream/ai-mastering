"""Measure reversible edits and restore their exact values after a regression."""

from contextlib import asynccontextmanager

from .mix_review import technical_regressions


class ChangeReview:
    def __init__(self, session, call, measure, record, advance_revision):
        self.session, self.call = session, call
        self.measure, self.record = measure, record
        self.advance_revision = advance_revision

    async def snapshot(self, tool, arguments):
        index = arguments["track_index"]
        track = await self.call(self.session, "get_track_info", track_index=index)
        snapshot = {"track_index": index, "track_name": track["name"]}
        if tool == "configure_effect":
            snapshot["batch"] = [await self.snapshot("set_device_parameter", {
                "track_index": index, "device_index": arguments["device_index"],
                "parameter_index": setting["parameter_index"],
            }) for setting in arguments["settings"]]
            return snapshot
        if tool in {"set_device_parameter", "set_effect_value"}:
            device_index, parameter_index = arguments["device_index"], arguments["parameter_index"]
            data = await self.call(self.session, "get_device_parameters", track_index=index, device_index=device_index)
            parameter = next((entry for entry in data["device"]["parameters"] if entry["index"] == parameter_index), None)
            if parameter is None:
                raise ValueError("검증된 디바이스 파라미터 인덱스가 없습니다")
            snapshot.update(tool="set_device_parameter", device_name=data["device"]["name"],
                            device_class=data["device"].get("class_name"), parameter_name=parameter["name"],
                            arguments={"track_index": index, "device_index": device_index,
                                       "parameter_index": parameter_index, "value": parameter["value"]})
        else:
            mixer = await self.call(self.session, "get_mixer", track_index=index)
            field = "volume" if tool == "set_track_volume" else "panning"
            snapshot.update(tool=tool, arguments={"track_index": index, "value": mixer[field]["value"]})
            if tool == "set_track_volume":
                snapshot["before_db"] = mixer["volume"]["db"]
        return snapshot

    async def restore(self, snapshot):
        if "batch" in snapshot:
            errors = []
            for child in reversed(snapshot["batch"]):
                try:
                    await self.restore(child)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise RuntimeError("이펙트 묶음 복구 확인 필요: " + ", ".join(errors))
            return
        index = snapshot["track_index"]
        track = await self.call(self.session, "get_track_info", track_index=index)
        if track["name"] != snapshot["track_name"]:
            raise RuntimeError("트랙 순서 변경으로 자동 복구를 중단했습니다")
        arguments = snapshot["arguments"]
        if snapshot["tool"] == "set_device_parameter":
            data = await self.call(self.session, "get_device_parameters", track_index=index, device_index=arguments["device_index"])
            parameter = next(entry for entry in data["device"]["parameters"] if entry["index"] == arguments["parameter_index"])
            if (data["device"]["name"], data["device"].get("class_name"), parameter["name"]) != (snapshot["device_name"], snapshot["device_class"], snapshot["parameter_name"]):
                raise RuntimeError("디바이스 변경으로 자동 복구를 중단했습니다")
        self.advance_revision()
        self.record({"change_review": "restore_requested", "snapshot": snapshot})
        await self.call(self.session, snapshot["tool"], **arguments)
        if snapshot["tool"] == "set_device_parameter":
            data = await self.call(self.session, "get_device_parameters", track_index=index, device_index=arguments["device_index"])
            actual = next(entry["value"] for entry in data["device"]["parameters"] if entry["index"] == arguments["parameter_index"])
        else:
            mixer = await self.call(self.session, "get_mixer", track_index=index)
            field = "volume" if snapshot["tool"] == "set_track_volume" else "panning"
            actual = mixer[field]["value"]
        if abs(actual - arguments["value"]) > 0.001:
            raise RuntimeError("측정 악화 후 이전 파라미터 복구를 확인하지 못했습니다")
        self.record({"change_review": "restored", "snapshot": snapshot})

    @asynccontextmanager
    async def edit(self, tool, arguments, role):
        index = arguments["track_index"]
        before = await self.measure(index)
        # Headroom protection during the measurement may have changed this fader.
        snapshot = await self.snapshot(tool, arguments)
        if tool == "set_track_volume" and arguments["db"] > snapshot["before_db"] + 3:
            raise ValueError("측정 중 보호 감쇠가 적용되었습니다. 새 페이더를 기준으로 +3 dB 이내로 조정하세요")
        result = {"before": before}
        self.advance_revision()
        try:
            yield result
            after = await self.measure(index)
        except BaseException:
            await self.restore(snapshot)
            raise
        expected_gain = arguments["db"] - snapshot["before_db"] if tool == "set_track_volume" else 0
        reasons = technical_regressions(before, after, role, expected_gain)
        result.update(accepted=not reasons, after=after, reasons=reasons)
        if reasons:
            await self.restore(snapshot)
            result["restored_analysis"] = await self.measure(index)
        self.record({"change_review": "evaluated", "track_index": index, "tool": tool, "result": result})
