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
from core.live_safety import CaptureOverload


class FakeSession:
    def __init__(self):
        self.db = 0
        self.value = 0.85
        self.parameter = 0.5
        self.writes = []
        self.master_db = -12

    async def list_tools(self):
        names = REQUIRED | {"get_browser_tree", "load_instrument_or_effect"}
        tools = [SimpleNamespace(name=name, description=name, inputSchema={"type": "object"}) for name in names]
        return SimpleNamespace(tools=tools, nextCursor=None)

    async def call_tool(self, name, arguments):
        if name == "get_session_info":
            result = {"track_count": 1, "song_length": 32, "loop": False, "is_playing": False}
        elif name == "measure_mix":
            result = {"master_peak_db": -8, "tracks": [{"index": 0, "name": "Kick", "is_group": False, "peak_db": -10}]}
        elif name in {"stop_playback", "set_arrangement_time"}:
            result = "OK"
        elif name == "get_track_info":
            result = {"name": "Kick", "solo": False, "mute": False, "devices": []}
        elif name == "get_mixer":
            if arguments.get("track_type") == "master":
                result = {"name": "Master", "volume": {"value": .6, "db": self.master_db}, "panning": {"value": 0}}
            else:
                result = {"name": "Kick", "is_group": False, "volume": {"value": self.value, "db": self.db}, "panning": {"value": 0}}
        elif name == "get_device_parameters":
            result = {"device": {"name": "EQ Eight", "class_name": "Eq8", "parameters": [{"index": 0, "name": "Gain", "value": self.parameter, "min": 0, "max": 1}]}}
        elif name == "set_device_parameter":
            self.parameter = arguments["value"]
            self.writes.append((name, arguments))
            result = "Set parameter"
        elif name == "set_track_volume":
            if arguments.get("track_type") == "master":
                self.master_db = arguments["db"]
            else:
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
    async def test_destructive_live_edit_is_rolled_back_before_export(self):
        session = FakeSession()

        async def changing_capture(*args, **kwargs):
            sr = 48000
            t = np.arange(sr) / sr
            if session.parameter == .5:
                mono = .45 * np.sin(2 * np.pi * 100 * t) * np.exp(-30 * (t % .25))
            else:
                mono = .13 * np.sin(2 * np.pi * 100 * t)
            return np.column_stack([mono, mono]).astype(np.float32), sr

        model = ScriptedModel([
            ("get_device_parameters", {"track_index": 0, "device_index": 0}),
            ("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0, "value": .4}),
            ("measure_audio", {}), ("finish", {}),
        ])
        with tempfile.TemporaryDirectory() as folder, patch("core.live_agent.capture", changing_capture):
            report = await run_agent(session, model, Path(folder) / "output")
        self.assertEqual(session.parameter, .5)
        self.assertEqual(report["status"], "complete")
        rejected = [event for event in report["events"] if event.get("change_review") == "evaluated" and not event["result"]["accepted"]]
        self.assertEqual(len(rejected), 1)
        self.assertTrue(rejected[0]["result"]["reasons"])

    async def test_invalid_model_arguments_are_repaired_without_stopping_the_run(self):
        model = ScriptedModel([("measure_audio", {"track_index": 999}), ("measure_audio", {}), ("finish", {})])
        with tempfile.TemporaryDirectory() as folder, patch("core.live_agent.capture", fake_capture):
            report = await run_agent(FakeSession(), model, Path(folder) / "output")
        self.assertEqual(report["status"], "complete")
        self.assertTrue(any("error" in event for event in report["events"]))
        self.assertTrue(report["quality"]["loudness_target_met"])

    async def test_prepare_configure_remeasure_and_export(self):
        class Session(FakeSession):
            def __init__(self):
                super().__init__()
                self.devices = []
                self.muted_writes = []

            async def call_tool(self, name, arguments):
                if name == "get_track_info":
                    result = {"name": "Kick", "solo": False, "mute": False, "devices": list(self.devices)}
                elif name == "get_browser_items_at_path":
                    result = {"items": [{"name": "EQ Eight", "uri": "native:eq8"}]}
                elif name == "load_instrument_or_effect":
                    self.devices.append({"name": "EQ Eight", "class_name": "Eq8", "index": 0})
                    result = "Loaded"
                elif name == "get_device_parameters":
                    result = {"device": {"name": "EQ Eight", "class_name": "Eq8", "parameters": [
                        {"index": 0, "name": "Frequency", "min": 0, "max": 1, "value": self.parameter,
                         "value_string": f"{20 * 1000 ** self.parameter:.2f} Hz"},
                    ]}}
                elif name == "set_track_volume" and "value" in arguments:
                    self.value = arguments["value"]
                    result = "Set volume"
                elif name == "set_device_parameter":
                    self.muted_writes.append(self.value == 0)
                    return await super().call_tool(name, arguments)
                else:
                    return await super().call_tool(name, arguments)
                return SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text=json.dumps(result))])

            async def list_tools(self):
                page = await super().list_tools()
                page.tools.append(SimpleNamespace(name="get_browser_items_at_path", description="browser", inputSchema={"type": "object"}))
                return page

        session = Session()
        model = ScriptedModel([
            ("prepare_track", {"track_index": 0}),
            ("set_effect_value", {"track_index": 0, "device_index": 0, "parameter_index": 0, "target": 70, "unit": "hz"}),
            ("measure_audio", {"track_index": 0}), ("measure_audio", {}), ("finish", {}),
        ])
        with tempfile.TemporaryDirectory() as folder, patch("core.live_agent.capture", fake_capture):
            report = await run_agent(session, model, Path(folder) / "output")
        self.assertEqual(report["status"], "complete")
        self.assertAlmostEqual(20 * 1000 ** session.parameter, 70, delta=1)
        self.assertEqual(len(session.devices), 1)
        self.assertTrue(all(session.muted_writes))
        self.assertEqual(session.value, .85)

    async def test_overloaded_capture_is_discarded_and_retried_at_lower_master_gain(self):
        count = 0

        async def overloaded_once(*args, **kwargs):
            nonlocal count
            count += 1
            audio, sr = await fake_capture()
            return (audio * 10 if count == 1 else audio), sr

        session = FakeSession()
        model = ScriptedModel([("measure_audio", {}), ("finish", {})])
        with tempfile.TemporaryDirectory() as folder, patch("core.live_agent.capture", overloaded_once):
            report = await run_agent(session, model, Path(folder) / "output")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(session.master_db, -18)
        self.assertTrue(any(event.get("protection") == "capture_overload" for event in report["events"]))

    async def test_live_overload_stops_playback_even_if_it_was_initially_playing(self):
        class Recorder:
            def __init__(self, device):
                self.ready = threading.Event()
                self.stop = threading.Event()
                self.peak = 1.0

            def record(self, limit):
                self.ready.set()
                self.stop.wait(5)
                return np.ones((48000, 2)), 48000

        state = {"position": 4, "playing": True}

        async def tool(session, name, **args):
            if name == "get_session_info":
                return {"track_count": 0, "loop": False, "current_song_time": state["position"], "is_playing": state["playing"]}
            if name == "set_arrangement_time":
                state["position"] = args["time"]
            if name in {"start_playback", "stop_playback"}:
                state["playing"] = name == "start_playback"

        with patch("core.live_audio.LoopbackRecorder", Recorder):
            with self.assertRaises(CaptureOverload):
                await capture(None, tool, 0, 16)
        self.assertFalse(state["playing"])
        self.assertEqual(state["position"], 4)

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
