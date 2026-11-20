"""Discover Ableton's own effects without guessing browser URIs or device indices."""


NATIVE_CLASSES = {
    "Eq8": "EQ Eight", "Compressor2": "Compressor", "GlueCompressor": "Glue Compressor",
    "StereoGain": "Utility", "Limiter": "Limiter", "Reverb": "Reverb", "Delay": "Delay",
}
NATIVE_NAMES = {value.casefold() for value in NATIVE_CLASSES.values()}


def native_name(device):
    class_name = device.get("class_name")
    if class_name:
        return NATIVE_CLASSES.get(class_name)
    name = device.get("name", "")
    return name if name.casefold() in NATIVE_NAMES else None


def browser_entries(data):
    if isinstance(data, dict):
        if "name" in data:
            yield data
        for value in data.values():
            yield from browser_entries(value)
    elif isinstance(data, list):
        for value in data:
            yield from browser_entries(value)


class NativeEffects:
    def __init__(self, session, call, record):
        self.session, self.call, self.record = session, call, record
        self.items = {}

    async def discover(self):
        queue = ["audio_effects"]
        visited = set()
        while queue and len(visited) < 24:
            path = queue.pop(0)
            if path in visited:
                continue
            visited.add(path)
            data = await self.call(self.session, "get_browser_items_at_path", path=path)
            self.record({"native_browser_path": path, "result": data})
            for item in browser_entries(data):
                name = item["name"].casefold()
                if name in NATIVE_NAMES and item.get("uri"):
                    self.items[name] = item
                elif item.get("is_folder") and not item.get("is_loadable"):
                    queue.append(item.get("path") or f"{path}/{item['name']}")
        return self.items

    async def ensure(self, index, expected_name, requested):
        if not self.items:
            await self.discover()
        result = []
        for effect_name in requested:
            before = await self.call(self.session, "get_track_info", track_index=index)
            if before["name"] != expected_name:
                raise RuntimeError("이펙트 준비 중 트랙 순서가 변경되었습니다")
            found = next((device for device in before.get("devices", [])
                          if (native_name(device) or "").casefold() == effect_name.casefold()), None)
            loaded = False
            if found is None:
                item = self.items.get(effect_name.casefold())
                if not item:
                    result.append({"effect": effect_name, "available": False})
                    continue
                self.record({"native_load": effect_name, "track_index": index, "uri": item["uri"], "state": "requested"})
                await self.call(self.session, "load_instrument_or_effect", track_index=index, uri=item["uri"])
                after = await self.call(self.session, "get_track_info", track_index=index)
                if after["name"] != expected_name or len(after.get("devices", [])) != len(before.get("devices", [])) + 1:
                    raise RuntimeError("내장 이펙트 로드 결과를 확인하지 못했습니다")
                found = next((device for device in after["devices"]
                              if (native_name(device) or "").casefold() == effect_name.casefold()), None)
                if found is None:
                    raise RuntimeError("요청한 내장 이펙트와 로드된 디바이스가 다릅니다")
                loaded = True
            params = await self.call(self.session, "get_device_parameters", track_index=index, device_index=found["index"])
            entry = {"effect": effect_name, "available": True, "loaded": loaded, "device_index": found["index"], "parameters": params}
            self.record({"native_prepared": entry, "track_index": index})
            result.append(entry)
        return result
