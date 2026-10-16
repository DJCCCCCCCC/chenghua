"""Export selected bytecode as static evidence; never execute target modules."""

import dis
import hashlib
import io
import json
import marshal
import sys
from pathlib import Path

from dis_function import walk


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "modern_app": [
        "ImageProcessThread.run", "DrawingThread.run",
        "ModernDrawingApp.select_position", "ModernDrawingApp.start_drawing",
        "ModernDrawingApp.create_left_panel",
    ],
    "imgprocess": [
        "ImageProcessor.preprocess", "ImageProcessor.extract_contours", "ImageProcessor.get_drawing_points",
    ],
    "area_selector": [
        "AreaSelectorV2.__init__", "AreaSelectorV2.select_area", "AreaSelectorV2.on_mouse_drag",
        "AreaSelectorV2._draw_preview_strokes", "AreaSelectorV2.on_confirm",
    ],
    "mctl": ["MouseController.move_to", "MouseController.draw_stroke"],
}


def main():
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("The original marshal requires Python 3.11")
    directory = ROOT / "analysis_extract" / "drawing_evidence"
    directory.mkdir(exist_ok=True)
    manifest = {"evidence_type": "static Python 3.11 bytecode; target code not executed",
                "target": "YouYu自动绘画.exe", "files": [], "unmatched": []}
    digest = hashlib.sha256()
    with (ROOT / manifest["target"]).open("rb") as executable:
        for block in iter(lambda: executable.read(1024 * 1024), b""):
            digest.update(block)
    manifest["target_sha256"] = digest.hexdigest()
    for module, queries in TARGETS.items():
        source = ROOT / "analysis_extract" / "modules" / (module + ".marshal")
        data = source.read_bytes()
        functions = list(walk(marshal.loads(data)))
        output = io.StringIO()
        output.write(f"Module: {module}\nSHA-256: {hashlib.sha256(data).hexdigest()}\n")
        entries = []
        for query in queries:
            matches = [(name, code) for name, code in functions if name.endswith("." + query)]
            if not matches:
                manifest["unmatched"].append(f"{module}:{query}")
            for name, code in matches:
                output.write(f"\n=== {name} (original source line {code.co_firstlineno}) ===\n")
                dis.dis(code, file=output)
                entries.append({"qualified_name": name, "source_line": code.co_firstlineno})
        path = directory / (module + ".txt")
        path.write_text(output.getvalue(), encoding="utf-8")
        manifest["files"].append({"path": str(path.relative_to(ROOT)), "functions": entries})
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
