from __future__ import annotations

import dis
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
    if len(sys.argv) < 3:
        raise SystemExit("usage: dis_function.py MODULE FUNCTION [FUNCTION ...]")
    root = marshal.loads(Path(sys.argv[1]).read_bytes())
    all_code = dict(walk(root))
    for query in sys.argv[2:]:
        matches = [
            (name, code)
            for name, code in all_code.items()
            if name == query or name.endswith(f".{query}")
        ]
        if not matches:
            print(f"NOT FOUND: {query}")
            continue
        for name, code in matches:
            print(f"\n===== {name} =====")
            print(
                f"args={code.co_argcount} kwonly={code.co_kwonlyargcount} "
                f"locals={code.co_nlocals} stack={code.co_stacksize} "
                f"line={code.co_firstlineno}"
            )
            print("NAMES:", code.co_names)
            print("VARS:", code.co_varnames)
            print("CONSTS:")
            for index, value in enumerate(code.co_consts):
                if isinstance(value, CodeType):
                    print(f"  {index}: <code {value.co_name}>")
                else:
                    text = repr(value).encode("ascii", "backslashreplace").decode("ascii")
                    print(f"  {index}: {text}")
            print("DIS:")
            dis.dis(code)


if __name__ == "__main__":
    main()
