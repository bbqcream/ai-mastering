"""Minimal AbletonOSC client for applying track panning in Live."""
import threading

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


class AbletonOSC:
    def __init__(self, host="127.0.0.1", remote_port=11000, reply_port=11001, timeout=1.5):
        self.timeout = timeout
        self._response = None
        self._event = threading.Event()
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._on_message)
        try:
            self._server = ThreadingOSCUDPServer(("0.0.0.0", reply_port), dispatcher)
        except OSError as exc:
            raise RuntimeError(f"OSC 응답 포트 {reply_port}를 열 수 없습니다: {exc}") from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._client = SimpleUDPClient(host, remote_port)

    def _on_message(self, address, *values):
        if address == "/live/song/get/track_names":
            self._response = values
            self._event.set()

    def track_names(self):
        self._response = None
        self._event.clear()
        self._client.send_message("/live/song/get/track_names", [])
        if not self._event.wait(self.timeout):
            raise RuntimeError(
                "AbletonOSC 응답이 없습니다. Live에서 AbletonOSC Remote Script를 활성화했는지 확인하세요."
            )
        return [str(name) for name in self._response]

    def apply_panning(self, plan):
        live_names = self.track_names()
        lookup = {name.casefold(): index for index, name in enumerate(live_names)}
        matches = []
        missing = []
        for track in plan["tracks"]:
            pan = float(track.get("pan", 0.0))
            if not -1.0 <= pan <= 1.0:
                raise ValueError(f"{track['name']}: pan은 -1~1 범위여야 합니다")
            index = lookup.get(str(track["name"]).casefold())
            if index is None:
                missing.append(track["name"])
                continue
            matches.append((track["name"], index, pan))
        if missing:
            raise RuntimeError("Live 트랙 이름과 일치하지 않음: " + ", ".join(missing))

        applied = []
        for name, index, pan in matches:
            if pan:
                self._client.send_message("/live/track/set/panning", [index, pan])
            applied.append(name)
        return applied

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1.0)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()