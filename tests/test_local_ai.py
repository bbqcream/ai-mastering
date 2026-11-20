"""Reject remote inference and malformed local-model output before audio changes."""

import json
import unittest
from unittest.mock import patch

from core.local_ai import LocalAI


SCHEMA = {
    "type": "object", "properties": {"gain": {"type": "number", "minimum": -6, "maximum": 6}},
    "required": ["gain"], "additionalProperties": False,
}


def reply(content):
    return {"message": {"content": content}}


class LocalAITests(unittest.TestCase):
    def test_invalid_output_is_repaired_before_returning(self):
        ai = LocalAI()
        responses = [reply('{"gain": NaN}'), reply('{"gain": 80}'), reply(json.dumps({"gain": -2}))]
        with patch.object(ai, "request", side_effect=responses) as request:
            decision = ai.decide("mix", {}, SCHEMA)
        self.assertEqual(decision, {"gain": -2})
        self.assertEqual(request.call_count, 3)

    def test_repeated_invalid_output_fails(self):
        with patch.object(LocalAI, "request", return_value=reply('{"gain": 80}')):
            with self.assertRaises(RuntimeError):
                LocalAI().decide("mix", {}, SCHEMA)

    def test_remote_endpoint_and_cloud_model_are_rejected(self):
        with self.assertRaises(ValueError):
            LocalAI(url="https://example.com")
        with self.assertRaises(ValueError):
            LocalAI(model="example:cloud")


if __name__ == "__main__":
    unittest.main()
