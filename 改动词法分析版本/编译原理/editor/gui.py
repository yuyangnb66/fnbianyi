"""MiniLang 桌面代码编辑器 — 用户自行编写、编译、运行、写文件。"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compiler import Compiler
from compiler.runtime import OUTPUT_DIR, WORKSPACE, ensure_dirs, reset_handlers, set_input_handler, set_write_handler

DEFAULT_SOURCE = ""

STATUS_OK = "#2ea043"
STATUS_ERR = "#f85149"
STATUS_WARN = "#d29922"


class _LiveStdout:
    """运行时将 print 实时写入输出面板。"""

    def __init__(self, widget: scrolledtext.ScrolledText, root: tk.Misc) -> None:
        self.widget = widget
        self.root = root
        self._parts: list[str] = []

    def write(self, text: str) -> None:
        if not text:
            return
        self._parts.append(text)
        self.widget.config(state=tk.NORMAL)
        self.widget.insert(tk.END, text)
        self.widget.config(state=tk.DISABLED)
        self.widget.see(tk.END)
        self.root.update_idletasks()

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return "".join(self._parts)


class LineNumberedEditor(tk.Frame):
    """带行号栏的代码编辑器。"""

    def __init__(self, master: tk.Misc, **text_kwargs) -> None:
        super().__init__(master)
        font = text_kwargs.get("font", ("Consolas", 12))

        body = tk.Frame(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.lineno = tk.Text(
            body,
            width=5,
            padx=6,
            pady=2,
            takefocus=0,
            border=0,
            state=tk.DISABLED,
            font=font,
            background="#f6f8fa",
            foreground="#656d76",
            cursor="arrow",
        )
        self.lineno.pack(side=tk.LEFT, fill=tk.Y)

        text_frame = tk.Frame(body)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.vbar = tk.Scrollbar(text_frame, orient=tk.VERTICAL)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text = tk.Text(
            text_frame,
            wrap=tk.NONE,
            yscrollcommand=self._on_yscroll,
            font=font,
            undo=True,
            **{k: v for k, v in text_kwargs.items() if k != "font"},
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar.config(command=self._on_vscroll)

        self.hbar = tk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.config(xscrollcommand=self.hbar.set)

        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<KeyRelease>", self._update_lineno)
        self.text.bind("<ButtonRelease>", self._update_lineno)
        self.text.bind("<MouseWheel>", self._update_lineno)
        self.text.bind("<Configure>", self._update_lineno)

    def _on_yscroll(self, first: str, last: str) -> None:
        self.vbar.set(first, last)
        self.lineno.yview_moveto(first)

    def _on_vscroll(self, *args) -> None:
        self.text.yview(*args)
        self.lineno.yview(*args)

    def _on_modified(self, _event=None) -> None:
        self._update_lineno()
        self.text.edit_modified(False)

    def _update_lineno(self, _event=None) -> None:
        end_index = self.text.index("end-1c")
        line_count = max(1, int(end_index.split(".")[0]))
        width = max(4, len(str(line_count)))
        self.lineno.config(width=width + 1)
        numbers = "\n".join(str(i) for i in range(1, line_count + 1))
        self.lineno.config(state=tk.NORMAL)
        self.lineno.delete("1.0", tk.END)
        self.lineno.insert("1.0", numbers)
        self.lineno.config(state=tk.DISABLED)
        first, _ = self.text.yview()
        self.lineno.yview_moveto(first)


class MiniLangIDE(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MiniLang IDE")
        self.geometry("1100x720")
        self.minsize(860, 560)

        ensure_dirs()
        self.current_file: Path | None = WORKSPACE / "main.ml"
        self._build_ui()
        self._load_default()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=6)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="新建", command=self._new_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="打开", command=self._open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="保存", command=self._save_file).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="编译", command=self._compile_only).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="运行", command=self._run).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="编译并运行", command=self._compile_and_run).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="打开输出目录", command=self._open_output_dir).pack(side=tk.LEFT, padx=2)

        self.file_label = ttk.Label(toolbar, text="", foreground="#666")
        self.file_label.pack(side=tk.RIGHT, padx=4)

        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        editor_frame = ttk.LabelFrame(paned, text="源代码 (.ml)", padding=4)
        self.editor_widget = LineNumberedEditor(editor_frame, font=("Consolas", 12))
        self.editor_widget.pack(fill=tk.BOTH, expand=True)
        self.editor = self.editor_widget.text
        paned.add(editor_frame, weight=3)

        bottom = ttk.PanedWindow(paned, orient=tk.HORIZONTAL)
        paned.add(bottom, weight=2)

        err_frame = ttk.LabelFrame(bottom, text="错误 / 警告", padding=4)
        self.error_text = scrolledtext.ScrolledText(
            err_frame, height=8, font=("Consolas", 10), state=tk.DISABLED,
        )
        self.error_text.pack(fill=tk.BOTH, expand=True)
        bottom.add(err_frame, weight=1)

        out_frame = ttk.LabelFrame(bottom, text="运行输出", padding=4)
        self.output_text = scrolledtext.ScrolledText(
            out_frame, height=8, font=("Consolas", 10), state=tk.DISABLED,
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)
        bottom.add(out_frame, weight=1)

        self.status = ttk.Label(self, text="F5 编译运行 | Ctrl+S 保存 | 支持 string[i]、len()、数组(栈/队列)", anchor=tk.W, padding=(8, 4))
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

        self.bind("<Control-s>", lambda e: self._save_file())
        self.bind("<F5>", lambda e: self._compile_and_run())

    def _load_default(self) -> None:
        if self.current_file and self.current_file.exists():
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", self.current_file.read_text(encoding="utf-8"))
        else:
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", DEFAULT_SOURCE)
        self.editor_widget._update_lineno()
        self._update_file_label()

    def _update_file_label(self) -> None:
        if self.current_file:
            self.file_label.config(text=str(self.current_file))
        else:
            self.file_label.config(text="未保存")

    def _new_file(self) -> None:
        self.current_file = WORKSPACE / "main.ml"
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", DEFAULT_SOURCE)
        self.editor_widget._update_lineno()
        self._clear_panels()
        self._set_status("新建文件")
        self._update_file_label()

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=WORKSPACE,
            filetypes=[("MiniLang", "*.ml"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.current_file = Path(path)
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", self.current_file.read_text(encoding="utf-8"))
        self.editor_widget._update_lineno()
        self._clear_panels()
        self._set_status(f"已打开 {self.current_file.name}")
        self._update_file_label()

    def _save_file(self) -> None:
        ensure_dirs()
        if not self.current_file:
            self.current_file = WORKSPACE / "main.ml"
        self.current_file.parent.mkdir(parents=True, exist_ok=True)
        self.current_file.write_text(self.editor.get("1.0", tk.END), encoding="utf-8")
        self._set_status(f"已保存 → {self.current_file}")
        self._update_file_label()

    def _open_output_dir(self) -> None:
        ensure_dirs()
        import os
        os.startfile(str(OUTPUT_DIR))

    def _clear_panels(self) -> None:
        self._set_text(self.error_text, "")
        self._set_text(self.output_text, "")

    @staticmethod
    def _set_text(widget: scrolledtext.ScrolledText, content: str) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.config(state=tk.DISABLED)

    def _set_status(self, msg: str, ok: bool = True) -> None:
        self.status.config(text=msg, foreground=STATUS_OK if ok else STATUS_ERR)

    def _get_source(self) -> str:
        return self.editor.get("1.0", tk.END)

    def _show_diagnostics(self, result) -> bool:
        lines: list[str] = []
        for e in result.errors:
            lines.append(f"错误 [{e.stage}] L{e.line}: {e.message}")
        for w in result.warnings:
            lines.append(f"警告 [{w.stage}] L{w.line}: {w.message}")
        self._set_text(self.error_text, "\n".join(lines) if lines else "无错误或警告")
        return result.success

    def _compile_only(self) -> None:
        self._save_file()
        result = Compiler().compile(self._get_source(), optimize=True, run=False)
        ok = self._show_diagnostics(result)
        if ok:
            out_py = self.current_file.with_suffix(".py") if self.current_file else WORKSPACE / "main.py"
            out_py.write_text(result.target_code, encoding="utf-8")
            self._set_text(self.output_text, f"编译成功\n目标代码 → {out_py}")
            self._set_status("编译成功")
        else:
            self._set_text(self.output_text, "编译失败，请查看错误面板")
            self._set_status(f"编译失败 — {len(result.errors)} 个错误", ok=False)

    def _gui_input(self, prompt: str) -> str:
        self.update_idletasks()
        val = simpledialog.askstring("程序输入", prompt or "请输入:", parent=self)
        return val or ""

    def _on_write_notify(self, path: Path, content: str) -> None:
        msg = f"\n[已写入文件] {path}\n内容: {content}\n"
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, msg)
        self.output_text.config(state=tk.DISABLED)
        self.output_text.see(tk.END)

    def _run_compiled(self, code: str) -> None:
        reset_handlers()
        set_input_handler(self._gui_input)
        set_write_handler(self._on_write_notify)

        from compiler.runtime import runtime_globals

        self._set_text(self.output_text, "")
        live_out = _LiveStdout(self.output_text, self)
        old_out = sys.stdout
        sys.stdout = live_out
        globs = {"__name__": "__main__"}
        globs.update(runtime_globals())
        err = False
        try:
            exec(compile(code, "<generated>", "exec"), globs)
        except Exception as e:
            live_out.write(f"\n[运行错误] {type(e).__name__}: {e}\n")
            err = True
        finally:
            sys.stdout = old_out
            reset_handlers()

        if not live_out.getvalue().strip():
            self._set_text(self.output_text, "(程序运行完毕，无 print 输出)")
        self._set_status("运行完成" if not err else "运行出错", ok=not err)

    def _compile_and_run(self) -> None:
        self._save_file()
        result = Compiler().compile(self._get_source(), optimize=True, run=False)
        if not self._show_diagnostics(result):
            self._set_text(self.output_text, "编译失败，无法运行")
            self._set_status(f"编译失败 — {len(result.errors)} 个错误", ok=False)
            return
        if self.current_file:
            self.current_file.with_suffix(".py").write_text(result.target_code, encoding="utf-8")
        self._run_compiled(result.target_code)

    def _run(self) -> None:
        self._compile_and_run()


def main() -> None:
    app = MiniLangIDE()
    app.mainloop()


if __name__ == "__main__":
    main()
