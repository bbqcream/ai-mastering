"""Regression checks for autonomous writes and evidence required to finish."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.live_agent import REQUIRED, run_agent
from core.live_audio import capture


class FakeSession:
    def __init__(self):
        self.db = 0
        self.value = 0.85
        self.parameter = 0.5
        self.writes = []

    async def list_tools(self):
        names = REQUIRED | {"get_browser_tree", "load_instrument_or_effect"}
        tools = [SimpleNamespace(name=name, description=name, inputSchema={"type": "object"}) for name in names]
        return SimpleNamespace(tools=tools, nextCursor=None)

    async def call_tool(self, name, arguments):
        if name == "get_session_info":
            result = {"track_count": 1, "song_length": 32, "loop": False}
        elif name == "get_track_info":
            result = {"name": "Kick", "solo": False, "mute": False, "devices": []}
        elif name == "get_mixer":
            result = {"name": "Kick", "is_group": False, "volume": {"value": self.value, "db": self.db}, "panning": {"value": 0}}
        elif name == "get_device_parameters":
            result = {"device": {"parameters": [{"index": 0, "name": "Gain", "value": self.parameter, "min": 0, "max": 1}]}}
        elif name == "set_device_parameter":
            self.parameter = arguments["value"]
            self.writes.append((name, arguments))
            result = "Set parameter"
        elif name == "set_track_volume":
            self.db = arguments["db"]
            self.value = 0.85 + self.db / 50
            self.writes.append((name, arguments))
            result = "Set volume"
        else:
            raise AssertionError(f"Unexpected MCP call {name}")
        return SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text=json.dumps(result))])


class ScriptedModel:
    model = "fake:local"

    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, prompt, context, schema):
        name, args = next(self.actions)
        return {"tool": name, "arguments": args, "reason": "측정 결과로 조정"}


async def fake_capture(*args, **kwargs):
    sr = 48000
    mono = .2 * np.sin(2 * np.pi * 100 * np.arange(sr) / sr)
    return np.column_stack([mono, mono]).astype(np.float32), sr


class LiveAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_failure_restores_solo_and_transport(self):
        class Recorder:
            def __init__(self, device):
                self.ready = threading.Event()
                self.stop = threading.Event()

            def record(self, limit):
                self.ready.set()
                self.stop.wait(5)
                return np.zeros((48000, 2)), 48000

        solos = [True, False]
        position = 4
        playing = False

        async def tool(session, name, **args):
            nonlocal position, playing
            if name == "get_session_info":
                return {"track_count": 2, "loop": False, "current_song_time": position, "is_playing": playing}
            if name == "get_track_info":
                index = args["track_index"]
                return {"name": str(index), "solo": solos[index]}
            if name == "set_track_solo":
                solos[args["track_index"]] = args["solo"]
            if name == "set_arrangement_time":
                position = args["time"]
            if name == "start_playback":
                raise RuntimeError("playback failed")
            if name == "stop_playback":
                playing = False

        with patch("core.live_audio.LoopbackRecorder", Recorder):
            with self.assertRaisesRegex(RuntimeError, "playback failed"):
                await capture(None, tool, 0, 16, track_index=1)
        self.assertEqual(solos, [True, False])
        self.assertEqual(position, 4)
        self.assertFalse(playing)

    async def test_parameter_guard_and_remeasurement_before_master(self):
        session = FakeSession()
        model = ScriptedModel([
            ("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0, "value": .4}),
            ("get_device_parameters", {"track_index": 0, "device_index": 0}),
            ("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0, "value": 50}),
            ("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0, "value": .4}),
            ("set_track_volume", {"track_index": 0, "db": -6}),
            ("finish", {}),
            ("measure_audio", {"track_index": 0}),
            ("measure_audio", {}),
            ("finish", {}),
        ])
        with tempfile.TemporaryDirectory() as folder, patch("core.live_agent.capture", fake_capture):
            output = Path(folder) / "output"
            report = await run_agent(session, model, output)
            self.assertEqual(report["status"], "complete")
            self.assertEqual(len(session.writes), 2)
            errors = [event["error"] for event in report["events"] if "error" in event]
            self.assertEqual(len(errors), 3)
            self.assertTrue((output / "master.wav").exists())
            self.assertEqual(report["initial_tracks"][0]["mixer"]["volume"]["db"], 0)
            self.assertLessEqual(report["master"]["after"]["true_peak_db"], -1)

    async def test_budget_exhaustion_records_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch("core.live_agent.capture", fake_capture):
            output = Path(folder) / "output"
            with self.assertRaisesRegex(RuntimeError, "한도"):
                await run_agent(FakeSession(), ScriptedModel([("finish", {})]), output, max_steps=1)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertFalse((output / "master.wav").exists())


if __name__ == "__main__":
    unittest.main()
