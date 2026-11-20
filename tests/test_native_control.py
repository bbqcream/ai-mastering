import tempfile
import unittest
from pathlib import Path

from core.native_control import display_value, set_physical
from core.native_effects import NativeEffects
from install_live_support import install


class PhysicalSession:
    def __init__(self):
        self.raw = .5
        self.fader = .85
        self.muted_at_writes = []

    async def call(self, session, name, **args):
        if name == "get_session_info":
            return {"is_playing": False}
        if name == "get_mixer":
            return {"name": "Vocal", "volume": {"value": self.fader}}
        if name == "set_track_volume":
            self.fader = args["value"]
            return "OK"
        if name == "get_device_parameters":
            hz = 20 * 1000 ** self.raw
            return {"device": {"name": "EQ Eight", "class_name": "Eq8", "parameters": [
                {"index": 0, "name": "Frequency", "min": 0, "max": 1, "value": self.raw,
                 "value_string": f"{hz:.2f} Hz", "is_quantized": False},
            ]}}
        if name == "set_device_parameter":
            self.muted_at_writes.append(self.fader == 0)
            self.raw = args["value"]
            return "OK"
        raise AssertionError(name)


class NativeControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_log_frequency_uses_live_display_and_restores_output(self):
        session = PhysicalSession()
        events = []
        await set_physical(session, session.call, events.append, 0, 0, 0, 80, "hz")
        self.assertAlmostEqual(20 * 1000 ** session.raw, 80, delta=1)
        self.assertEqual(session.fader, .85)
        self.assertTrue(all(session.muted_at_writes))
        self.assertTrue(any("physical_mapping_restore" in event for event in events))

    async def test_unreachable_target_restores_original_parameter_and_output(self):
        session = PhysicalSession()
        with self.assertRaises(ValueError):
            await set_physical(session, session.call, lambda _: None, 0, 0, 0, 15, "hz")
        self.assertEqual(session.raw, .5)
        self.assertEqual(session.fader, .85)

    async def test_native_discovery_handles_folders_and_renamed_existing_effect(self):
        devices = [{"name": "My EQ", "class_name": "Eq8", "index": 0}]
        loads = []

        async def call(session, name, **args):
            if name == "get_browser_items_at_path":
                if args["path"] == "audio_effects":
                    return {"items": [{"name": "Dynamics", "is_folder": True, "is_loadable": False}]}
                return {"items": [{"name": "Compressor", "uri": "native:compressor", "is_device": True}]}
            if name == "get_track_info":
                return {"name": "Vocal", "devices": list(devices)}
            if name == "get_device_parameters":
                return {"device": dict(devices[args["device_index"]], parameters=[])}
            if name == "load_instrument_or_effect":
                loads.append(args["uri"])
                devices.append({"name": "Compressor", "class_name": "Compressor2", "index": 1})
                return "Loaded"
            raise AssertionError(name)

        effects = NativeEffects(None, call, lambda _: None)
        result = await effects.ensure(0, "Vocal", ["EQ Eight", "Compressor"])
        await effects.ensure(0, "Vocal", ["EQ Eight", "Compressor"])
        self.assertEqual(loads, ["native:compressor"])
        self.assertFalse(result[0]["loaded"])
        self.assertTrue(result[1]["loaded"])

    def test_display_unit_conversion(self):
        self.assertEqual(display_value("1.25 kHz", "hz"), 1250)
        self.assertEqual(display_value("0.15 s", "ms"), 150)
        self.assertEqual(display_value("2.0:1", "ratio"), 2)
        with self.assertRaises(ValueError):
            display_value("50 %", "db")

    def test_remote_support_installer_is_idempotent_and_keeps_backup(self):
        source = 'class Bridge:\n    def _serialize_device(self, device):\n        return {"parameters": [{"index": 0}]}\n'
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "__init__.py"
            script.write_text(source)
            self.assertTrue(install(script))
            self.assertFalse(install(script))
            self.assertEqual(script.with_name("__init__.py.ai-mix-backup").read_text(), source)
            namespace = {}
            exec(script.read_text(), namespace)
            class Parameter:
                value = .5
                is_quantized = True
                value_items = ["Off", "On"]

                def str_for_value(self, value):
                    return "100 Hz"

            device = type("Device", (), {"parameters": [Parameter()]})()
            result = namespace["Bridge"]()._serialize_device(device)
            self.assertEqual(result["parameters"][0]["value_string"], "100 Hz")
            self.assertEqual(result["parameters"][0]["value_items"], ["Off", "On"])
