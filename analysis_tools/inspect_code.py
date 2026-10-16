from __future__ import annotations

import dis
import marshal
import sys
from pathlib import Path
from types import CodeType


def walk(code: CodeType, prefix: str = ""):
    yield prefix, code
    for const in code.co_consts:
        if isinstance(const, CodeType):
            yield from walk(const, prefix + "  ")


def strings(code: CodeType) -> list[str]:
    result: list[str] = []
    for const in code.co_consts:
        if isinstance(const, str) and const:
            result.append(const)
    return result


def main() -> None:
    for name in sys.argv[1:]:
        path = Path(name)
        code = marshal.loads(path.read_bytes())
        print(f"=== {path.name} ===")
        for indent, item in walk(code):
            args = item.co_argcount
            kwonly = item.co_kwonlyargcount
            print(
                f"{indent}{item.co_name} "
                f"line={item.co_firstlineno} args={args}+{kwonly} "
                f"locals={item.co_nlocals} stack={item.co_stacksize}"
            )
            for value in strings(item):
                safe = value.encode("ascii", "backslashreplace").decode("ascii")
                print(f"{indent}  STR {safe!r}")
        print()


if __name__ == "__main__":
    main()
