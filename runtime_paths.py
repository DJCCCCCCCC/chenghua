"""Persistent output paths for source runs and the portable executable."""

import os
import sys
from pathlib import Path


def application_data_directory(source_file):
    if not getattr(sys, "frozen", False):
        return Path(source_file).resolve().parent
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    directory = base / "Chenghua"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
