import ctypes
import os
from pathlib import Path
import tempfile
import unittest

from scripts.check_distribution import within_directory


class DistributionPathTests(unittest.TestCase):
    def test_real_containment_does_not_accept_adjacent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inside = root / "environment"
            inside.mkdir()
            outside = root / "environment-other"
            outside.mkdir()
            self.assertTrue(within_directory(inside, root))
            self.assertFalse(within_directory(outside, inside))
            with self.assertRaises(FileNotFoundError):
                within_directory(root / "missing", inside)

    @unittest.skipUnless(os.name == "nt", "Windows short-path alias")
    def test_windows_short_and_long_paths_have_same_containment(self):
        with tempfile.TemporaryDirectory(prefix="SparsiLoop alias regression ") as temporary:
            root = Path(temporary)
            environment = root / "isolated environment"
            environment.mkdir()
            source = environment / "module.py"
            source.write_text("", encoding="utf-8")
            buffer = ctypes.create_unicode_buffer(32768)
            count = ctypes.windll.kernel32.GetShortPathNameW(str(root), buffer, len(buffer))
            if not count or Path(buffer.value) == root:
                self.skipTest("8.3 aliases unavailable on this volume")
            self.assertTrue(within_directory(source, Path(buffer.value) / environment.name))


if __name__ == "__main__":
    unittest.main()
