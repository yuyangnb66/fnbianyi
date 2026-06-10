"""MiniLang 运行时 — 支持交互输入与写文件，GUI/CLI 可注入回调。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

# 工作目录：用户代码与输出文件默认放这里
WORKSPACE = Path(__file__).parent.parent / "workspace"
OUTPUT_DIR = WORKSPACE / "output"

_input_fn: Optional[Callable[[str], str]] = None
_on_write_fn: Optional[Callable[[Path, str], None]] = None


def set_input_handler(fn: Callable[[str], str]) -> None:
    global _input_fn
    _input_fn = fn


def set_write_handler(fn: Callable[[Path, str], None]) -> None:
    global _on_write_fn
    _on_write_fn = fn


def reset_handlers() -> None:
    global _input_fn, _on_write_fn
    _input_fn = None
    _on_write_fn = None


def ensure_dirs() -> None:
    WORKSPACE.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)


def ml_input(prompt: str = "") -> str:
    if _input_fn:
        return _input_fn(prompt)
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    return sys.stdin.readline().rstrip("\n\r")


def ml_split_line(raw: str) -> list[str]:
    return raw.split()


def ml_getint(line: str, index: int) -> int:
    parts = ml_split_line(line.strip())
    if index < 0 or index >= len(parts):
        return 0
    try:
        return int(parts[index])
    except ValueError:
        try:
            return int(float(parts[index]))
        except ValueError:
            return 0


def ml_write(path: str, content: str) -> None:
    ensure_dirs()
    p = Path(path)
    if not p.is_absolute():
        p = OUTPUT_DIR / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content) + "\n", encoding="utf-8")
    if _on_write_fn:
        _on_write_fn(p, str(content))


def runtime_globals() -> dict:
    """注入到 exec 的命名空间。"""
    return {
        "_ml_input": ml_input,
        "_ml_write": ml_write,
        "_ml_split_line": ml_split_line,
        "_ml_getint": ml_getint,
    }
