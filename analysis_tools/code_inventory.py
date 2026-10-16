from __future__ import annotations

import marshal
import sys
from pathlib import Path
from types import CodeType


def walk(code: CodeType, parent: str = ""):
    qualified = f"{parent}.{code.co_name}" if parent else code.co_name
    yield qualified, code
    for const in code.co_consts:
        if isinstance(const, CodeType):
            yield from walk(const, qualified)


def main() -> None:
    for arg in sys.argv[1:]:
        root = marshal.loads(Path(arg).read_bytes())
        print(f"=== {arg} ===")
        for name, code in walk(root):
            args = list(code.co_varnames[: code.co_argcount + code.co_kwonlyargcount])
            print(
                f"{name}\tline={code.co_firstlineno}\t"
                f"args={args!r}\tlocals={code.co_nlocals}\t"
                f"stack={code.co_stacksize}"
            )


if __name__ == "__main__":
    main()
