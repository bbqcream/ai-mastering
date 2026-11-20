import unittest

import numpy as np

from core.audio_features import measure_audio
from core.live_safety import GainProtection, audition_ranges, validate_parameter
from core.roles import classify_track


class ProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_and_master_are_remeasured_after_attenuation(self):
        levels = {"track": 0.0, "master": 0.0}
        events = []

        async def call(session, name, **args):
            kind = args.get("track_type", "track")
            if name == "get_mixer":
                return {"name": kind, "volume": {"db": levels[kind]}}
            if name == "set_track_volume":
                levels[kind] = args["db"]
                return "OK"
            if name == "measure_mix":
                return {"master_peak_db": 10 + levels["master"] + levels["track"],
                        "tracks": [{"name": "track", "index": 0, "peak_db": 1 + levels["track"], "is_group": False}]}
            raise AssertionError(name)

        protection = GainProtection(None, call, events.append)
        result = await protection.check(0, 16)
        self.assertLessEqual(result["master_peak_db"], -6)
        self.assertLessEqual(result["tracks"][0]["peak_db"], -3)
        self.assertLess(levels["master"], 0)
        self.assertLess(levels["track"], 0)
        self.assertEqual(sum(event.get("protection") == "meter_scan" for event in events), 3)

    def test_parameter_limits_reject_excessive_gain_and_plugin(self):
        parameter = {"name": "Gain", "min": -15, "max": 15, "value": 0}
        with self.assertRaises(ValueError):
            validate_parameter({"class_name": "Eq8"}, parameter, 10)
        with self.assertRaises(ValueError):
            validate_parameter({"class_name": "PluginDevice", "name": "EQ Eight"}, parameter, 1)

    def test_audio_features_preserve_antiphase_energy_and_detect_full_scale(self):
        wave = .3 * np.sin(2 * np.pi * 200 * np.arange(48000) / 48000)
        result = measure_audio(np.column_stack([wave, -wave]), 48000)
        self.assertAlmostEqual(result["stereo_correlation"], -1)
        self.assertGreater(result["bands_db"]["low"], -1)
        clipped = np.clip(wave * 10, -1, 1)
        self.assertGreater(measure_audio(clipped[:, None], 48000)["full_scale_fraction"], .1)

    def test_names_and_representative_sections(self):
        for name, role in [("보컬더블01 L", "backing_vocal"), ("베이스드럼", "kick"),
                           ("베이스기타", "bass"), ("Open_Hat", "hi_hat"), ("BG Vox R", "backing_vocal")]:
            self.assertEqual(classify_track(name), role)
        self.assertEqual(audition_ranges(0, 128), [(0, 16), (56, 72), (112, 128)])
        self.assertEqual(audition_ranges(0, 8), [(0, 8)])
