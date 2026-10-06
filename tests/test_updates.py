from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import updates


class UpdateTests(unittest.TestCase):
    def test_compares_numeric_versions_and_does_not_offer_downgrades(self):
        for tag, expected in (("v0.3.10", "available"), ("0.3.3", "current"), ("v0.3.2", "current")):
            with self.subTest(tag=tag), patch.object(updates, "VERSION", "0.3.3"), \
                 patch.object(updates, "urlopen", return_value=BytesIO(json.dumps({"tag_name": tag}).encode())) as request:
                result = updates.check_updates()
                self.assertEqual(result["status"], expected)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.kwargs["timeout"], 5)
                self.assertEqual(result["url"], updates.RELEASES_URL)

    def test_unreachable_github_stops_after_initial_attempt_and_three_retries(self):
        with patch.object(updates, "urlopen", side_effect=URLError("blocked")) as request, \
             patch.object(updates.time, "sleep") as sleep:
            self.assertEqual(updates.check_updates()["status"], "unavailable")
            self.assertEqual(request.call_count, 4)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [.5, 1, 2])

    def test_success_on_last_retry(self):
        with patch.object(updates, "VERSION", "0.3.3"), patch.object(updates.time, "sleep"), \
             patch.object(updates, "urlopen", side_effect=[URLError("blocked")] * 3 + [BytesIO(b'{"tag_name":"v0.4.0"}')]) as request:
            self.assertEqual(updates.check_updates()["status"], "available")
            self.assertEqual(request.call_count, 4)

    def test_invalid_or_prerelease_responses_are_not_reported_as_current(self):
        for body in (b"not JSON", b'{}', b'null', b'{"tag_name":"v0.4.0-beta"}', b'{"tag_name":"v0.4.0","prerelease":true}'):
            with self.subTest(body=body), patch.object(updates.time, "sleep"), \
                 patch.object(updates, "urlopen", side_effect=lambda *args, **kwargs: BytesIO(body)) as request:
                self.assertEqual(updates.check_updates()["status"], "unavailable")
                self.assertEqual(request.call_count, 4)
