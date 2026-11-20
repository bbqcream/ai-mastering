import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from core.ai_mix import ai_mix
from core.live_review import ChangeReview
from core.live_safety import active_audition_ranges
from core.mix_review import masking_context, technical_regressions


class ReviewTests(unittest.TestCase):
    def test_overlap_candidates_require_shared_band_and_close_levels(self):
        tracks = [
            {"name": "Kick", "role": "kick", "analysis": {"lufs": -20, "spectrum_db": {"80": -2, "3000": -60}}},
            {"name": "Bass", "role": "bass", "analysis": {"lufs": -22, "spectrum_db": {"80": -3, "3000": -60}}},
            {"name": "Keys", "role": "keys", "analysis": {"lufs": -20, "spectrum_db": {"80": -60, "3000": -1}}},
        ]
        findings = masking_context(tracks)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["candidate_hz"], 80)
        tracks[1]["analysis"]["lufs"] = -45
        self.assertEqual(masking_context(tracks), [])

    def test_regressions_are_gain_invariant_and_preserve_bass(self):
        before = {"lufs": -20, "crest_db": 14, "bands_db": {"sub": -5, "low": -3}, "stereo_correlation": .8}
        quieter = dict(before, lufs=-30)
        self.assertEqual(technical_regressions(before, quieter, "bass"), [])
        after = dict(before, crest_db=5, bands_db={"sub": -20, "low": -25}, stereo_correlation=-.6)
        self.assertEqual(len(technical_regressions(before, after, "bass")), 4)

    def test_clip_positions_avoid_empty_intro_and_ignore_invalid_metadata(self):
        self.assertEqual(active_audition_ranges(0, 256, {"clips": [{"start_time": 96, "end_time": 112}]}), [(96, 112)])
        ranges = active_audition_ranges(0, 256, {"clips": [
            {"start_time": 64, "end_time": 96}, {"start_time": 96, "end_time": 128},
            {"start_time": float("nan"), "end_time": 200},
        ]})
        self.assertTrue(all(64 <= begin < finish <= 128 for begin, finish in ranges))

    def test_stem_processing_retains_last_accepted_plan_after_regression(self):
        class Model:
            def __init__(self):
                self.contexts = []

            def decide(self, prompt, context, schema):
                self.contexts.append(context)
                return {"role": "kick", "gain_db": 0, "pan": 0, "highpass_hz": 180,
                        "eq_hz": 1000, "eq_gain_db": 0, "ratio": 4, "threshold_db": -50,
                        "attack_ms": 5, "release_ms": 300, "reason": "deliberately destructive test"}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sr = 48000
            t = np.arange(sr * 2) / sr
            wave = .5 * np.sin(2 * np.pi * 45 * t) * np.exp(-30 * (t % .5))
            sf.write(root / "Kick.wav", wave, sr)
            model = Model()
            audio, rate, plan, report = ai_mix(root, model, passes=2, progress=lambda _: None)
            reviews = [entry for turn in report["passes"] for entry in turn["track_reviews"]]
            self.assertTrue(any(not entry["accepted"] for entry in reviews))
            self.assertFalse(model.contexts[1]["track"]["previous_review"]["accepted"])
            self.assertEqual(rate, sr)
            self.assertTrue(np.isfinite(audio).all())
            self.assertNotEqual(plan["tracks"][0]["effects"][0]["params"]["freq"], 180)


class LiveReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_parameter_edit_is_restored_and_verified(self):
        parameter_value = .5
        revisions = []
        events = []

        async def call(session, name, **args):
            nonlocal parameter_value
            if name == "get_track_info":
                return {"name": "Kick"}
            if name == "get_device_parameters":
                return {"device": {"name": "Compressor", "class_name": "Compressor2", "parameters": [
                    {"index": 0, "name": "Threshold", "value": parameter_value},
                ]}}
            if name == "set_device_parameter":
                parameter_value = args["value"]
                return "OK"
            raise AssertionError(name)

        async def measure(index):
            return {"crest_db": 15 if parameter_value == .5 else 4, "lufs": -20}

        review = ChangeReview(None, call, measure, events.append, lambda: revisions.append(True))
        async with review.edit("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0, "value": .9}, "kick") as result:
            await call(None, "set_device_parameter", value=.9)
        self.assertEqual(parameter_value, .5)
        self.assertFalse(result["accepted"])
        self.assertEqual(len(revisions), 2)
        self.assertTrue(any(event.get("change_review") == "restored" for event in events))

    async def test_failed_write_restores_previous_fader(self):
        value = .85

        async def call(session, name, **args):
            nonlocal value
            if name == "get_track_info":
                return {"name": "Vocal"}
            if name == "get_mixer":
                return {"volume": {"value": value, "db": 0}}
            if name == "set_track_volume":
                value = args["value"]
                return "OK"
            raise AssertionError(name)

        async def measure(index):
            return {"lufs": -20, "crest_db": 10}

        review = ChangeReview(None, call, measure, lambda _: None, lambda: None)
        with self.assertRaisesRegex(RuntimeError, "partial failure"):
            async with review.edit("set_track_volume", {"track_index": 0, "db": -6}, "lead_vocal"):
                value = .3
                raise RuntimeError("partial failure")
        self.assertEqual(value, .85)
