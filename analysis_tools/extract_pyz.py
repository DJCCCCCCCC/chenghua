from __future__ import annotations

import marshal
import struct
import zlib
from pathlib import Path


ARCHIVE = Path(r"D:\桌面\Code\绘图工具逆向\analysis_extract\PYZ.pyz")
OUTPUT = Path(r"D:\桌面\Code\绘图工具逆向\analysis_extract\modules")
TARGETS = {
    "modern_app",
    "modern_main",
    "imgprocess",
    "imgprocess_line",
    "image_to_line",
    "paint_algos",
    "mctl",
    "area_selector",
    "screenshot_selector",
    "paint_order_dialog",
    "siliconflow_generator",
    "space_gradio_client",
    "tag_translate",
    "theme",
    "update_downloader",
    "version_info",
}


def read_toc(data: bytes) -> list[tuple[str, tuple[int, int, int]]]:
    toc_pos = struct.unpack("!i", data[8:12])[0]
    toc = marshal.loads(data[toc_pos:])
    return toc


def extract_module(data: bytes, entry: tuple[int, int, int]):
    _, offset, length = entry
    return marshal.loads(zlib.decompress(data[offset : offset + length]))


def main() -> None:
    data = ARCHIVE.read_bytes()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entries = dict(read_toc(data))
    for name in sorted(TARGETS):
        if name not in entries:
            print(f"missing {name}")
            continue
        code = extract_module(data, entries[name])
        path = OUTPUT / f"{name}.marshal"
        path.write_bytes(marshal.dumps(code))
        print(f"{name}: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
