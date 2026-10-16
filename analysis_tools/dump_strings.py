from __future__ import annotations

import marshal
import sys
from pathlib import Path
from types import CodeType


def walk(code: CodeType, parent: str = ""):
    name = f"{parent}.{code.co_name}" if parent else code.co_name
    yield name, code
    for const in code.co_consts:
        if isinstance(const, CodeType):
            yield from walk(const, name)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: dump_strings.py MODULE [FILTER]")
    root = marshal.loads(Path(sys.argv[1]).read_bytes())
    needle = sys.argv[2].lower() if len(sys.argv) > 2 else ""
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    lines: list[str] = []
    for name, code in walk(root):
        for index, const in enumerate(code.co_consts):
            if not isinstance(const, str) or not const:
                continue
            if needle and needle not in const.lower() and needle not in name.lower():
                continue
            safe = const.encode("unicode_escape").decode("ascii")
            lines.append(f"{name}\t{code.co_firstlineno}\t{index}\t{safe}")
    text = "\n".join(lines) + ("\n" if lines else "")
    if out:
        out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
