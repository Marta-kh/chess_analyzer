#!/usr/bin/env python3
"""Zero-config test runner that works from any working directory on Windows, macOS, and Linux."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")

pkg_dir = Path(__file__).resolve().parent
parent_dir = pkg_dir.parent
for bad in ("", ".", str(pkg_dir), os.getcwd()):
    if Path(bad or ".").resolve() == pkg_dir.resolve():
        while bad in sys.path:
            sys.path.remove(bad)
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

if __name__ == "__main__":
    tests_dir = pkg_dir / "tests"
    suite = unittest.defaultTestLoader.discover(start_dir=str(tests_dir), top_level_dir=str(tests_dir))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
