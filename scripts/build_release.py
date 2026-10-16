"""Build the portable Windows release using the current Python environment."""

import hashlib
import importlib.metadata as metadata
import platform
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo,
)


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.0"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
STEM = f"Chenghua-v{VERSION}-windows-x64"
PRODUCT = "\u57ce\u753b"


def make_icon():
    image = Image.new("RGBA", (256, 256), (23, 79, 70, 255))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 176)
    draw.text((128, 124), PRODUCT[0], font=font, anchor="mm", fill="white")
    icon = BUILD / "chenghua.ico"
    image.save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return icon


def make_version_info():
    version = tuple(map(int, VERSION.split("."))) + (0,)
    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3f,
                          flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("080404B0", [
            StringStruct("FileDescription", PRODUCT + " - Automatic Drawing"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "Chenghua"),
            StringStruct("OriginalFilename", "Chenghua.exe"),
            StringStruct("ProductName", PRODUCT),
            StringStruct("ProductVersion", VERSION),
        ])]), VarFileInfo([VarStruct("Translation", [2052, 1200])])],
    )
    target = BUILD / "version_info.txt"
    target.write_text(str(info), encoding="utf-8")
    return target


def third_party_notices():
    sections = ["Chenghua - Third-Party Notices\n\n"
                "The following notices apply to components bundled with the Windows executable.\n"
                "PyInstaller is distributed under GPL with a bootloader exception.\n"]
    for name in ("numpy", "Pillow", "opencv-python-headless", "requests", "certifi",
                 "charset-normalizer", "idna", "urllib3", "pyinstaller"):
        package = metadata.distribution(name)
        sections.append(f"\n{'=' * 72}\n{name} {package.version}\n{'=' * 72}\n")
        found = False
        for item in sorted(package.files or []):
            path = str(item).replace("\\", "/")
            filename = Path(path).name.lower()
            legal_name = filename.startswith(("license", "licence", "copying", "notice"))
            if legal_name and (".dist-info/" in path or path in
                               ("cv2/LICENSE.txt", "cv2/LICENSE-3RD-PARTY.txt")):
                sections.append(f"\n--- {path} ---\n" +
                                package.locate_file(item).read_text(encoding="utf-8", errors="replace"))
                found = True
        if not found:
            raise RuntimeError(f"No license text found for {name}")
    python_home = Path(sys.base_prefix)
    sections.append(f"\n{'=' * 72}\nPython {platform.python_version()}\n" +
                    (python_home / "LICENSE.txt").read_text(encoding="utf-8"))
    for license_file in sorted((python_home / "tcl").glob("*/license.terms")):
        sections.append(f"\n{'=' * 72}\n{license_file.parent.name}\n" +
                        license_file.read_text(encoding="utf-8", errors="replace"))
    output = DIST / "THIRD_PARTY_NOTICES.txt"
    output.write_text("\n".join(sections), encoding="utf-8")
    return output


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build with 64-bit Python on Windows.")
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    icon = make_icon()
    version_info = make_version_info()
    notices = third_party_notices()
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "Chenghua", "--icon", str(icon),
        "--version-file", str(version_info), "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
        "--add-data", f"{notices};.", "--exclude-module", "pytest",
        "--exclude-module", "unittest", "--exclude-module", "tkinter.test",
        str(ROOT / "chenghua_app.py"),
    ], check=True, cwd=ROOT)
    executable = DIST / f"{STEM}.exe"
    shutil.copy2(DIST / "Chenghua.exe", executable)
    archive = DIST / f"{STEM}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for source, name in ((executable, "Chenghua.exe"), (ROOT / "README.md", "README.md"),
                             (ROOT / "RELEASE_NOTES.md", "RELEASE_NOTES.md"),
                             (notices, notices.name)):
            bundle.write(source, f"Chenghua/{name}")
    assets = (executable, archive, notices)
    checksums = DIST / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in assets), encoding="ascii")
    for path in (*assets, checksums):
        print(f"{path.name}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
