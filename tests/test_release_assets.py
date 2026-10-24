import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


builder = module("build_release")
publisher = module("publish_github_release")


class ReleaseTests(unittest.TestCase):
    def source_git(self, private=False):
        names = ["LICENSE", "event_control_lab/__main__.py", "STATUS.json", "PROJECT_STATUS.md"]
        if private:
            names.append("artifacts/private.json")

        def git(*args):
            if args == ("rev-parse", "--show-toplevel"):
                return str(builder.ROOT).encode()
            if args[0] == "status":
                return b""
            if args[0] == "ls-tree":
                return b"".join(b"100644 blob " + b"a" * 40 + b"\t" + name.encode() + b"\0" for name in names)
            if args[:2] == ("cat-file", "blob"):
                return b"public source"
            if args == ("rev-parse", "HEAD"):
                return b"b" * 40
            raise AssertionError(args)

        return git

    def test_historical_status_is_not_shipped_as_current_delivery_evidence(self):
        with patch.object(builder, "git", self.source_git()):
            members, prefix, commit = builder.committed_source()
        self.assertEqual(set(members), {"source/LICENSE", "source/event_control_lab/__main__.py"})
        self.assertEqual(prefix, "")
        self.assertEqual(commit, "b" * 40)

    def test_unapproved_tracked_private_path_stops_the_build(self):
        with patch.object(builder, "git", self.source_git(private=True)):
            with self.assertRaisesRegex(ValueError, "unapproved release source"):
                builder.committed_source()

    def assets(self, destination):
        files = {"SparsiLoop-0.1.0a2.zip": b"bundle",
                 "sparsiloop-0.1.0a2-py3-none-any.whl": b"wheel",
                 "sparsiloop-0.1.0a2.tar.gz": b"source",
                 "RELEASE_INFO.json": json.dumps({"version": "0.1.0a2", "source_commit": "a" * 40,
                    "repository": publisher.REPOSITORY, "ci_url": None}).encode()}
        for name, data in files.items():
            (destination / name).write_bytes(data)
        (destination / "SHA256SUMS").write_text("".join(
            hashlib.sha256(data).hexdigest() + "  " + name + "\n" for name, data in files.items()), encoding="utf-8")

    def test_publication_dry_run_never_contacts_github(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assets(directory)
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            with patch.object(publisher, "gh", side_effect=AssertionError("Network before publication")):
                publisher.publish(directory, directory / "absent-notes.md")
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_changed_asset_is_rejected_before_any_remote_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assets(directory)
            (directory / "SparsiLoop-0.1.0a2.zip").write_bytes(b"changed")
            with patch.object(publisher, "gh", side_effect=AssertionError("Network before verification")):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    publisher.publish(directory, directory / "notes.md", True)


if __name__ == "__main__":
    unittest.main()
