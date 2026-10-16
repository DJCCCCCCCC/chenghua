import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime_paths import application_data_directory


class RuntimePathTests(unittest.TestCase):
    def test_source_output_stays_beside_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("runtime_paths.sys.frozen", False, create=True):
                self.assertEqual(application_data_directory(Path(directory) / "app.py"),
                                 Path(directory).resolve())

    def test_frozen_output_survives_temporary_bundle_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("runtime_paths.sys.frozen", True, create=True), \
                    mock.patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                result = application_data_directory("nonexistent-bundle/app.py")
                self.assertEqual(result, Path(directory) / "Chenghua")
                self.assertTrue(result.is_dir())
                (result / "image.png").write_bytes(b"persistent")
                self.assertEqual(application_data_directory("different-bundle/app.py"), result)
                self.assertEqual((result / "image.png").read_bytes(), b"persistent")

    def test_frozen_output_has_home_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("runtime_paths.sys.frozen", True, create=True), \
                    mock.patch.dict(os.environ, {"LOCALAPPDATA": ""}), \
                    mock.patch("runtime_paths.Path.home", return_value=Path(directory)):
                self.assertEqual(application_data_directory("app.py"),
                                 Path(directory) / "AppData" / "Local" / "Chenghua")
