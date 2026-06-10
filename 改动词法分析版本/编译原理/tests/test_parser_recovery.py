"""语法分析器错误恢复：任何报错都必须在有限时间内结束。"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compiler import Compiler
from compiler.lexer import Lexer
from compiler.parser import Parser

TIMEOUT = 3.0
TOKENS = ROOT / "grammar" / "tokens.json"

BAD_SOURCES = [
    "if (ok == 1 && top == 0 { print(1); }",
    "if (x == 1 { print(x); }",
    "while (i < n { i = i + 1; }",
    "for (i = 0; i < 10; i = i + 1 { print(i); }",
    "int x int y;",
    "print(hello);",
    "print();",
    "int arr[; int x;",
    "int fib(int n { return n; }",
    "if (1) else print(1);",
    "else { print(1); }",
    "{ { {",
    "}}}}",
    "x = = 1;",
    "if if if (1) { }",
    "print(print(print(1;",
    "input(,);",
    "write(,);",
    "return return 1;",
    "break continue;",
    "int 123abc;",
    "&& || !",
    "if (a && ) { }",
    "if (a || ) { }",
    "if (!) { }",
    "func(a,,b);",
    "((((((",
    "))))))",
    "",
    "@#$%^& invalid chars only",
    "int x; int y; if (x == ) { print(x); } while ( { } for (;; {",
]


def compile_with_timeout(source: str) -> tuple[bool, float, str]:
    result = {"done": False, "err": None}

    def run():
        try:
            Compiler().compile(source, optimize=True, run=False)
            result["done"] = True
        except Exception as e:
            result["err"] = str(e)

    t0 = time.time()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(TIMEOUT)
    elapsed = time.time() - t0
    if th.is_alive():
        return False, elapsed, "HANG (Compiler)"
    if result["err"]:
        return False, elapsed, f"ERR: {result['err']}"
    return True, elapsed, "OK"


def parse_with_timeout(source: str) -> tuple[bool, float, str]:
    result = {"done": False, "err": None}

    def run():
        try:
            lr = Lexer(source, TOKENS).tokenize()
            Parser(lr.tokens).parse()
            result["done"] = True
        except Exception as e:
            result["err"] = str(e)

    t0 = time.time()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(TIMEOUT)
    elapsed = time.time() - t0
    if th.is_alive():
        return False, elapsed, "HANG (Parser)"
    if result["err"]:
        return False, elapsed, f"ERR: {result['err']}"
    return True, elapsed, "OK"


def main() -> None:
    failed = []
    for i, src in enumerate(BAD_SOURCES):
        ok, elapsed, msg = parse_with_timeout(src)
        if not ok:
            failed.append((i, src[:40], msg, elapsed))
        ok2, elapsed2, msg2 = compile_with_timeout(src)
        if not ok2:
            failed.append((i, src[:40], msg2, elapsed2))

    if failed:
        print(f"FAILED {len(failed)} cases:")
        for i, preview, msg, elapsed in failed:
            print(f"  [{i}] {elapsed:.2f}s {msg} | {preview!r}")
        raise SystemExit(1)
    print(f"All {len(BAD_SOURCES)} malformed sources finished within {TIMEOUT}s (parser + compiler).")


if __name__ == "__main__":
    main()
