"""MiniLang 编译器 CLI 入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from compiler.compiler import Compiler
from compiler.runtime import runtime_globals


def _print_stage(title: str) -> None:
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print("=" * 50)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MiniLang 编译器 — 词法/语法/语义分析 → 中间代码 → 优化 → 目标代码"
    )
    parser.add_argument("source", nargs="?", help="MiniLang 源文件 (.ml)")
    parser.add_argument("-o", "--output", help="输出目标代码文件路径")
    parser.add_argument("--run", action="store_true", help="编译并运行")
    parser.add_argument("--gui", action="store_true", help="启动桌面代码编辑器")
    parser.add_argument("--no-opt", action="store_true", help="跳过优化阶段")
    parser.add_argument("--trace", action="store_true", help="打印词法器 NFA/DFA 调试信息")
    parser.add_argument(
        "--dump",
        choices=["tokens", "ast", "tac", "opt", "all"],
        help="打印中间结果",
    )
    args = parser.parse_args(argv)

    if args.gui or not args.source:
        from editor.gui import main as gui_main
        gui_main()
        return 0

    src_path = Path(args.source)
    if not src_path.exists():
        print(f"错误: 文件不存在 {src_path}", file=sys.stderr)
        return 1

    compiler = Compiler()
    result = compiler.compile_file(src_path, optimize=not args.no_opt, run=args.run, trace=args.trace)

    if not result.success:
        print("编译失败:", file=sys.stderr)
        for err in result.errors:
            print(f"  {err}", file=sys.stderr)
        for warn in result.warnings:
            print(f"  {warn}", file=sys.stderr)
        return 1

    if args.dump:
        if args.dump in ("tokens", "all"):
            _print_stage("1. 词法分析 — Token 流")
            for tok in result.tokens:
                print(f"  {tok}")
        if args.dump in ("ast", "all"):
            _print_stage("2. 语法分析 — 抽象语法树 (AST)")
            print(f"  {result.ast}")
        if args.dump in ("tac", "all"):
            _print_stage("4. 中间代码 — 三地址码 (TAC)")
            for i, ins in enumerate(result.tac.instructions, 1):
                print(f"  {i:3d}. {ins}")
        if args.dump in ("opt", "all") and result.optimized_tac:
            _print_stage("5. 优化后的中间代码")
            for i, ins in enumerate(result.optimized_tac.instructions, 1):
                print(f"  {i:3d}. {ins}")

    out_path = Path(args.output) if args.output else src_path.with_suffix(".py")
    out_path.write_text(result.target_code, encoding="utf-8")
    print(f"编译成功 → {out_path}")

    if args.run:
        print("\n--- 程序输出 ---")
        globs = {"__name__": "__main__"}
        globs.update(runtime_globals())
        exec(compile(result.target_code, str(out_path), "exec"), globs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
