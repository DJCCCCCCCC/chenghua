from __future__ import annotations

import importlib.util
import marshal
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: make_pyc.py INPUT [INPUT ...]")
    for arg in sys.argv[1:]:
        source = Path(arg)
        code = marshal.loads(source.read_bytes())
        target = source.with_suffix(".pyc")
        target.write_bytes(importlib.util.MAGIC_NUMBER + b"\0" * 12 + marshal.dumps(code))
        print(target)


if __name__ == "__main__":
    main()
