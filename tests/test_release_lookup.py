"""Recover one existing draft identity without recreating or replacing assets."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("release_lookup", Path(__file__).resolve().parents[1] /
                                             "scripts/publish_github_release.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
TAG = "v0.1.0a3"
COMMIT = "a" * 40
URL = f"https://api.github.com/repos/{publisher.REPOSITORY}/releases/42"


def response(value):
    return SimpleNamespace(stdout=json.dumps(value), returncode=0)


class ReleaseLookupTests(unittest.TestCase):
    def test_a_missing_rest_entry_resolves_the_same_graphql_draft_id(self):
        draft = {"id": 42, "url": URL, "tag_name": TAG, "target_commitish": COMMIT, "draft": True}
        with patch.object(publisher, "gh", side_effect=[response([]),
                response({"data": {"repository": {"release": {"databaseId": 42}}}}),
                response(draft)]) as gh:
            self.assertEqual(publisher.find_release(TAG), draft)
        self.assertEqual(gh.call_count, 3)
        self.assertEqual(gh.call_args.args, ("api", f"repos/{publisher.REPOSITORY}/releases/42"))

    def test_unavailable_graphql_identity_is_not_an_absent_release(self):
        for result in ({"errors": [{"message": "refused"}]}, {"data": None},
                       {"data": {"repository": None}}):
            with self.subTest(result=result), patch.object(publisher, "gh", side_effect=[response([]), response(result)]):
                with self.assertRaisesRegex(ValueError, "GraphQL"):
                    publisher.find_release(TAG)

    def test_absent_release_requires_a_successful_null_lookup(self):
        with patch.object(publisher, "gh", side_effect=[response([]),
                response({"data": {"repository": {"release": None}}})]):
            self.assertIsNone(publisher.find_release(TAG))

    def test_wrong_repository_tag_or_database_id_is_rejected(self):
        for change in ({"id": 43}, {"tag_name": "v0.1.0a2"},
                       {"url": "https://api.github.com/repos/other/repo/releases/42"}):
            with self.subTest(change=change), patch.object(publisher, "gh", side_effect=[response([]),
                    response({"data": {"repository": {"release": {"databaseId": 42}}}}),
                    response({"id": 42, "url": URL, "tag_name": TAG, **change})]):
                with self.assertRaisesRegex(ValueError, "identity differs"):
                    publisher.find_release(TAG)

    def test_lookup_by_id_http_failure_does_not_recreate_a_release(self):
        for status in (403, 404, 503):
            with self.subTest(status=status), patch.object(publisher, "gh", side_effect=[response([]),
                    response({"data": {"repository": {"release": {"databaseId": 42}}}}),
                    subprocess.CalledProcessError(1, ["gh"], stderr=f"HTTP {status}")]):
                with self.assertRaises(subprocess.CalledProcessError):
                    publisher.find_release(TAG)

    def test_created_but_unreadable_draft_is_not_recreated_or_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            (assets / "RELEASE_INFO.json").write_text(json.dumps({"version": "0.1.0a3",
                "repository": publisher.REPOSITORY, "source_commit": COMMIT, "ci_url": None}), encoding="utf-8")
            for name in ("SparsiLoop-0.1.0a3.zip", "sparsiloop-0.1.0a3-py3-none-any.whl", "sparsiloop-0.1.0a3.tar.gz"):
                (assets / name).write_bytes(b"original accepted asset")
            import hashlib
            (assets / "SHA256SUMS").write_text("".join(
                hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
                for path in sorted(assets.iterdir())), encoding="utf-8")
            notes = root / "notes.md"
            notes.write_text("Original notes", encoding="utf-8")
            with patch.object(publisher, "find_release", return_value=None) as lookup, \
                    patch.object(publisher.time, "sleep") as wait, \
                    patch.object(publisher.subprocess, "check_output", return_value=COMMIT.encode()), \
                    patch.object(publisher, "gh", return_value=SimpleNamespace(
                        returncode=1, stdout="", stderr="Not Found (HTTP 404)")) as gh:
                with self.assertRaisesRegex(ValueError, "preserve the existing draft"):
                    publisher.publish(assets, notes, True)
            self.assertEqual(lookup.call_count, 5)
            self.assertEqual([call.args[0] for call in wait.call_args_list], [1, 2, 4])
            self.assertEqual(sum(call.args[:2] == ("release", "create") for call in gh.call_args_list), 1)
            self.assertFalse(any(call.args[:2] in (("release", "edit"), ("release", "upload"))
                                 for call in gh.call_args_list))

    def test_wait_requires_the_original_source_identity(self):
        with patch.object(publisher, "find_release", return_value={"target_commitish": "b" * 40}), \
                patch.object(publisher.time, "sleep") as wait:
            with self.assertRaisesRegex(ValueError, "source changed"):
                publisher.wait_release(TAG, COMMIT)
        wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
