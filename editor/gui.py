"""MiniLang 桌面代码编辑器"""

from __future__ import annotations

import sys
import threading
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compiler import Compiler
from compiler.runtime import OUTPUT_DIR, WORKSPACE, ensure_dirs, reset_handlers, set_input_handler, set_warn_handler, set_write_handler

DEFAULT_SOURCE = """print("Hello, MiniLang!");"""

# 全局配色方案
COLORS = {
    "bg": "#f8f9fa",
    "editor_bg": "#ffffff",
    "editor_fg": "#24292f",
    "lineno_bg": "#f6f8fa",
    "lineno_fg": "#656d76",
    "status_bg": "#e1e4e8",
    "status_fg": "#24292f",
    "error": "#cf222e",
    "warning": "#9a6700",
    "success": "#1a7f37",
    "info": "#0969da",
    "border": "#d1d9e0",
}


class RunWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.title("程序运行 - 控制台")
        self.geometry("800x500")
        self.minsize(600, 400)
        self.configure(bg=COLORS["bg"])

        self.window_destroyed = False
        self.program_running = True

        self.msg_queue = queue.Queue()
        self.input_queue = queue.Queue()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_msg_queue()

    def _build_ui(self):
        main_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 上半部分：纯输入区
        input_frame = ttk.LabelFrame(main_paned, text="[输入区] Enter提交当前行 | Shift+Enter换行")
        self.input_text = tk.Text(input_frame, height=8, font=("Consolas", 11), bg=COLORS["editor_bg"])
        self.input_text.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        self.input_text.bind("<Return>", self._on_enter_send)
        self.input_text.bind("<Shift-Return>", self._on_shift_enter)

        main_paned.add(input_frame, weight=1)

        # 下半部分：纯输出区
        output_frame = ttk.LabelFrame(main_paned, text="[输出区]")
        self.output_text = scrolledtext.ScrolledText(
            output_frame, font=("Consolas", 11), state=tk.DISABLED, bg=COLORS["editor_bg"]
        )
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        main_paned.add(output_frame, weight=2)

        self.input_text.focus_set()

    def _append_output(self, text: str):
        if self.window_destroyed:
            return
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, text)
        self.output_text.config(state=tk.DISABLED)
        self.output_text.see(tk.END)

    def _on_enter_send(self, event=None):
        if self.window_destroyed or not self.program_running:
            return "break"

        current_line_start = self.input_text.index(tk.INSERT + " linestart")
        current_line_end = self.input_text.index(tk.INSERT + " lineend")
        content = self.input_text.get(current_line_start, current_line_end).strip()

        if not content:
            return "break"

        self.input_queue.put(content)
        self.input_text.insert(tk.END, "\n")
        return "break"

    def _on_shift_enter(self, event=None):
        return None

    def gui_output(self, text: str):
        self.msg_queue.put(("output", text))

    def gui_warn(self, text: str):
        self.msg_queue.put(("warn", text))

    def run_finish(self, is_success: bool):
        self.msg_queue.put(("finish", is_success))

    def gui_input(self, prompt: str) -> str:
        if self.window_destroyed:
            return ""
        self._append_output(prompt)
        try:
            user_input = self.input_queue.get(timeout=600)
        except queue.Empty:
            user_input = ""
        return user_input

    def _poll_msg_queue(self):
        if self.window_destroyed:
            return
        try:
            while True:
                msg_type, content = self.msg_queue.get_nowait()
                if msg_type == "output":
                    self._append_output(content)
                elif msg_type == "warn":
                    self._append_output(f"\n警告：{content}\n")
                elif msg_type == "finish":
                    self.program_running = False
                    if content:
                        self._append_output("\n程序正常结束\n")
                    else:
                        self._append_output("\n程序异常结束\n")
        except queue.Empty:
            pass
        self.after(50, self._poll_msg_queue)

    def _on_close(self):
        if self.program_running:
            if not messagebox.askyesno("提示", "程序正在运行中，确定要关闭控制台吗？"):
                return
        self.window_destroyed = True
        self.destroy()


# 带行号的代码编辑器
class LineNumberedEditor(tk.Frame):
    def __init__(self, master: tk.Misc, **text_kwargs) -> None:
        super().__init__(master, bg=COLORS["bg"])
        font = text_kwargs.get("font", ("Consolas", 12))

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.lineno = tk.Text(
            body, width=5, padx=8, pady=4, takefocus=0, border=0,
            state=tk.DISABLED, font=font, background=COLORS["lineno_bg"],
            foreground=COLORS["lineno_fg"], cursor="arrow", highlightthickness=0
        )
        self.lineno.pack(side=tk.LEFT, fill=tk.Y)

        text_frame = tk.Frame(body, bg=COLORS["bg"])
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.vbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text = tk.Text(
            text_frame, wrap=tk.NONE, yscrollcommand=self._on_yscroll, font=font, undo=True,
            background=COLORS["editor_bg"], foreground=COLORS["editor_fg"],
            insertbackground=COLORS["editor_fg"], selectbackground=COLORS["info"],
            selectforeground="#ffffff", borderwidth=1, relief=tk.SOLID, highlightthickness=0,
            **{k: v for k, v in text_kwargs.items() if k not in ("font", "bg", "fg")}
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar.config(command=self._on_vscroll)

        self.hbar = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 0))
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
        end_idx = self.text.index("end-1c")
        line_cnt = max(1, int(end_idx.split(".")[0]))
        width = max(4, len(str(line_cnt)))
        self.lineno.config(width=width + 1)
        nums = "\n".join(str(i) for i in range(1, line_cnt + 1))
        self.lineno.config(state=tk.NORMAL)
        self.lineno.delete("1.0", tk.END)
        self.lineno.insert("1.0", nums)
        self.lineno.config(state=tk.DISABLED)
        first, _ = self.text.yview()
        self.lineno.yview(first)


# 主IDE窗口
class MiniLangIDE(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MiniLang IDE")
        self.geometry("1200x800")
        self.minsize(900, 600)
        self.configure(bg=COLORS["bg"])

        self._set_theme()
        self.current_file: Path | None = WORKSPACE / "main.ml"
        self.is_modified = False
        self.current_run_window: RunWindow | None = None

        ensure_dirs()
        self._build_ui()
        self._load_default()
        self._bind_events()

    def _set_theme(self) -> None:
        style = ttk.Style(self)
        themes = style.theme_names()
        if "vista" in themes:
            style.theme_use("vista")
        elif "clam" in themes:
            style.theme_use("clam")

        style.configure("TButton", padding=(8, 4), font=("Segoe UI", 9))
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["status_fg"], font=("Segoe UI", 9))
        style.configure("TLabelframe", background=COLORS["bg"], borderwidth=1, relief=tk.SOLID)
        style.configure("TLabelframe.Label", background=COLORS["bg"], foreground=COLORS["status_fg"], font=("Segoe UI", 9, "bold"))
        style.configure("TSeparator", background=COLORS["border"])

    def _build_ui(self) -> None:
        # 工具栏
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="新建", command=self._new_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="打开", command=self._open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="保存", command=self._save_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="另存为", command=self._save_as_file).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="编译", command=self._compile_only).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="运行", command=self._run).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="编译并运行", command=self._compile_and_run).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="打开输出目录", command=self._open_output_dir).pack(side=tk.LEFT, padx=2)

        self.file_label = ttk.Label(toolbar, text="", foreground=COLORS["lineno_fg"])
        self.file_label.pack(side=tk.RIGHT, padx=4)

        # 主分割窗
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # 代码编辑器
        editor_frame = ttk.LabelFrame(paned, text="源代码 (.ml)", padding=6)
        self.editor_widget = LineNumberedEditor(editor_frame)
        self.editor_widget.pack(fill=tk.BOTH, expand=True)
        self.editor = self.editor_widget.text
        paned.add(editor_frame, weight=2)

        # 错误/警告面板
        err_frame = ttk.LabelFrame(paned, text="错误 / 警告", padding=6)
        err_frame.pack(fill=tk.BOTH, expand=True)

        # 水平容器：左侧错误文本区，右侧状态显示
        err_container = ttk.Frame(err_frame)
        err_container.pack(fill=tk.BOTH, expand=True)

        # 左侧：错误/警告文本框
        self.error_text = scrolledtext.ScrolledText(
            err_container, height=12, font=("Consolas", 10), state=tk.DISABLED,
            background=COLORS["editor_bg"], foreground=COLORS["editor_fg"]
        )
        self.error_text.tag_config("error", foreground=COLORS["error"])
        self.error_text.tag_config("warning", foreground=COLORS["warning"])
        self.error_text.tag_config("success", foreground=COLORS["success"])
        self.error_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))

        # 右侧：编译/运行状态标签（靠右显示）
        self.run_status_label = ttk.Label(err_container, text="就绪", font=("Segoe UI", 10))
        self.run_status_label.pack(side=tk.RIGHT, anchor=tk.NE, padx=5)

        # 用 tk.Label：Windows 下 ttk.Label 的 foreground 常被主题忽略
        self.status = tk.Label(
            self,
            text="F5 编译运行 | Ctrl+S 保存 | 支持 string[i]、len()、数组(栈/队列)",
            anchor=tk.W,
            padx=8,
            pady=4,
            fg=STATUS_OK,
        )
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

        self.error_text.tag_configure("diag_error", foreground=STATUS_ERR)
        self.error_text.tag_configure("diag_warn", foreground=STATUS_WARN)
        self.error_text.tag_configure("diag_ok", foreground=STATUS_OK)

        self.bind("<Control-s>", lambda e: self._save_file())
        self.bind("<Control-Shift-s>", lambda e: self._save_as_file())
        self.bind("<F5>", lambda e: self._compile_and_run())
        self.bind("<F6>", lambda e: self._compile_only())
        self.bind("<F7>", lambda e: self._run())

        # 文本变更监听
        self.editor.bind("<KeyRelease>", self._on_text_change)
        self.editor.bind("<ButtonRelease>", self._on_text_change)

    def _on_text_change(self, _event=None) -> None:
        self.is_modified = True

    def _load_default(self) -> None:
        if self.current_file and self.current_file.exists():
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", self.current_file.read_text(encoding="utf-8"))
        else:
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", DEFAULT_SOURCE)
        self.editor_widget._update_lineno()
        self._update_file_label()
        self.is_modified = False
        self._set_status("就绪", "success")

    def _update_file_label(self) -> None:
        self.file_label.config(text=str(self.current_file) if self.current_file else "未保存")

    def _new_file(self) -> None:
        if self.is_modified and not messagebox.askyesno("提示", "当前文件已修改，是否保存？"):
            return
        self.current_file = WORKSPACE / "main.ml"
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", DEFAULT_SOURCE)
        self.editor_widget._update_lineno()
        self._clear_panels()
        self._set_status("新建文件", "success")
        self._update_file_label()
        self.is_modified = False

    def _open_file(self) -> None:
        if self.is_modified and not messagebox.askyesno("提示", "当前文件已修改，是否保存？"):
            return
        path = filedialog.askopenfilename(initialdir=WORKSPACE, filetypes=[("MiniLang", "*.ml"), ("所有文件", "*.*")])
        if not path:
            return
        self.current_file = Path(path)
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", self.current_file.read_text(encoding="utf-8"))
        self.editor_widget._update_lineno()
        self._clear_panels()
        self._set_status(f"已打开 {self.current_file.name}", "success")
        self._update_file_label()
        self.is_modified = False

    def _save_file(self) -> None:
        ensure_dirs()
        if not self.current_file:
            self._save_as_file()
            return
        self.current_file.parent.mkdir(parents=True, exist_ok=True)
        self.current_file.write_text(self.editor.get("1.0", tk.END), encoding="utf-8")
        self._set_status(f"已保存 → {self.current_file}", "success")
        self._update_file_label()
        self.is_modified = False

    def _save_as_file(self) -> None:
        path = filedialog.asksaveasfilename(initialdir=WORKSPACE, defaultextension=".ml", filetypes=[("MiniLang", "*.ml"), ("所有文件", "*.*")])
        if not path:
            return
        self.current_file = Path(path)
        self._save_file()

    def _open_output_dir(self) -> None:
        ensure_dirs()
        import os
        os.startfile(str(OUTPUT_DIR))

    def _clear_panels(self) -> None:
        self._set_text(self.error_text, "")

    @staticmethod
    def _set_text(widget: scrolledtext.ScrolledText, content: str) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.config(state=tk.DISABLED)

    def _set_status(self, msg: str, ok: bool = True, warn: bool = False) -> None:
        if warn:
            color = STATUS_WARN
        elif ok:
            color = STATUS_OK
        else:
            color = STATUS_ERR
        self.status.config(text=msg, fg=color)

    def _get_source(self) -> str:
        return self.editor.get("1.0", tk.END)

    def _show_diagnostics(self, result) -> bool:
        self.error_text.config(state=tk.NORMAL)
        self.error_text.delete("1.0", tk.END)
        if not result.errors and not result.warnings:
            self.error_text.insert(tk.END, "无错误或警告\n", "diag_ok")
        else:
            for e in result.errors:
                self.error_text.insert(
                    tk.END,
                    f"错误 [{e.stage}] L{e.line}: {e.message}\n",
                    "diag_error",
                )
            for w in result.warnings:
                self.error_text.insert(
                    tk.END,
                    f"警告 [{w.stage}] L{w.line}: {w.message}\n",
                    "diag_warn",
                )
        self.error_text.config(state=tk.DISABLED)
        if result.errors:
            self._set_status(f"编译失败 — {len(result.errors)} 个错误", ok=False)
        elif result.warnings:
            self._set_status(
                f"编译完成 — {len(result.warnings)} 个警告",
                ok=True,
                warn=True,
            )
        return result.success

    def _compile_only(self) -> None:
        self._save_file()
        self._set_status("正在编译...", "info")
        self.update_idletasks()
        res = Compiler().compile(self._get_source(), optimize=True, run=False)
        ok = self._show_diagnostics(res)
        if ok:
            out_py = self.current_file.with_suffix(".py") if self.current_file else WORKSPACE / "main.py"
            out_py.write_text(result.target_code, encoding="utf-8")
            self._set_text(self.output_text, f"编译成功\n目标代码 → {out_py}")
            if not result.warnings:
                self._set_status("编译成功")
        else:
            self._set_text(self.output_text, "编译失败，请查看错误面板")

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

    def _gui_warn(self, message: str) -> None:
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, message + "\n")
        self.output_text.config(state=tk.DISABLED)
        self.output_text.see(tk.END)

    def _run_compiled(self, code: str) -> None:
        reset_handlers()
        set_input_handler(self._gui_input)
        set_write_handler(self._on_write_notify)
        set_warn_handler(self._gui_warn)

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
            import traceback
            win.gui_output(f"\n[运行错误] {type(e).__name__}: {e}\n")
            err_flag = True
        finally:
            win.run_finish(not err_flag)

    def _run_compiled(self, code: str) -> None:
        reset_handlers()
        self.current_run_window = RunWindow(self)
        win = self.current_run_window

        import compiler.runtime as rt
        def rt_input(prompt):
            return win.gui_input(prompt)
        def rt_write(path, content):
            win.gui_output(f"\n[写入文件] {path} 内容: {content}\n")
        def rt_warn(msg):
            win.gui_warn(msg)

        rt.set_input_handler(rt_input)
        rt.set_write_handler(rt_write)
        rt.set_warn_handler(rt_warn)

        t = threading.Thread(target=self._run_code_thread, args=(code, win), daemon=True)
        t.start()
        self._set_status("程序运行中...", "info")

    def _compile_and_run(self) -> None:
        self._save_file()
        result = Compiler().compile(self._get_source(), optimize=True, run=False)
        if not self._show_diagnostics(result):
            self._set_text(self.output_text, "编译失败，无法运行")
            return
        if self.current_file:
            self.current_file.with_suffix(".py").write_text(res.target_code, encoding="utf-8")
        self._run_compiled(res.target_code)

    def _run(self) -> None:
        self._compile_and_run()


def main() -> None:
    app = MiniLangIDE()
    app.mainloop()


if __name__ == "__main__":
    main()