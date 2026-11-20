import json
import unittest

from core.agent_context import model_context


class AgentContextTests(unittest.TestCase):
    def test_focus_and_latest_parameters_survive_without_repeated_review_payloads(self):
        analysis = {"lufs": -20, "crest_db": 12, "spectrum_db": {str(value): -10 for value in range(1000)}}
        tracks = {index: {"track": {"name": f"Track {index}", "clip_slots": ["large unused data"] * 1000},
                          "mixer": {"volume": {"db": -6}}, "role": "unknown", "analysis": analysis,
                          "mixing_guidance": {"role": "unknown"}} for index in range(40)}
        observations = [{"tool": "set_effect_value", "arguments": {"track_index": 3, "device_index": 0},
                         "result": {"review": {"accepted": True, "reasons": [], "before": analysis, "after": analysis},
                                    "readback": {"device": {"name": "EQ Eight", "parameters": [{"index": 0, "name": "Frequency", "value_string": "80 Hz"}]}}}}] * 20
        observations.append({"tool": "get_mixer", "arguments": {"track_index": 7}, "result": {"volume": {"db": -9}}})
        context = model_context(tracks, {}, {}, observations, 2, {3: 2})
        self.assertEqual(context["focus_track"]["track_index"], 7)
        self.assertEqual(context["current_device"]["track_index"], 3)
        self.assertEqual(context["history"][-1]["result"]["volume"]["db"], -9)
        self.assertNotIn("clip_slots", context["focus_track"]["track"])
        self.assertNotIn("spectrum_db", context["history"][0]["review"]["before"])
        self.assertLess(len(json.dumps(context)), 20000)
