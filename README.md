# MiniLang 简单编译器

参考 [CompilationPrinciple](https://github.com/qianqianjun/CompilationPrinciple) 项目的词法/语法分析思路，实现一个**完整但精炼**的教学用编译器，涵盖编译原理课程的全部核心阶段。

## 编译流水线

```
源码 (.ml) → 词法分析 → 语法分析 → 语义分析 → 中间代码(TAC) → 优化 → 目标代码(Python)
```

| 阶段 | 模块 | 说明 |
|------|------|------|
| 词法分析 | `compiler/lexer.py` | 自实现 NFA/DFA 正则引擎，从 `grammar/tokens.json` 加载字符集规则 |
| 语法分析 | `compiler/parser.py` | 递归下降，依据 `grammar/grammar.json` 的 BNF |
| 语义分析 | `compiler/semantic.py` | 符号表、作用域、类型检查 |
| 中间代码 | `compiler/tac.py` | 三地址码 (Three-Address Code) |
| 优化 | `compiler/optimizer.py` | 常量折叠、复制传播、死代码消除 |
| 目标代码 | `compiler/codegen.py` | 生成可执行的 Python 代码 |

## 快速开始

需要 Python 3.10+，**无需安装额外依赖**（使用内置 Tkinter）。

```bash
python -m compiler.main
```

在桌面编辑器中：

1. 编写 MiniLang 代码（默认 `workspace/main.ml`）
2. **F5** 编译并运行 — `input` 会弹窗读入
3. `print` 显示在下方，`write` 写入 `workspace/output/`
4. **Ctrl+S** 保存

### 命令行

```bash
# 编译并运行
python -m compiler.main workspace/main.ml --run

# 查看中间结果
python -m compiler.main workspace/main.ml --dump all

# 词法器调试 trace
python -m compiler.main workspace/main.ml --trace

# 跳过优化
python -m compiler.main workspace/main.ml --no-opt --run
```

## 语言特性

`int` / `float` / `string`、函数（含递归）、`if` / `else if` / `else`、`while` / `for`、`break` / `continue`、数组、`string[i]`、`len()`、`input`、`print`（支持多参数同一行输出）、`printn`（不换行）、`write`。

### 一行读多个数（类似 `scanf`）

```c
input(n, x, "> ");          // 一行输入: 2 3
input(line, "> ");          // 一行字符串: 10 20 30
t = getint(line, 0);       // 取第 1 个数 (下标从 0)
t = getint(line, 1);       // 取第 2 个数
```

## 项目结构

```
fnbianyi/
├── compiler/              # 编译器各阶段
├── grammar/               # 词法/语法规则
├── editor/gui.py          # 桌面 IDE（默认入口）
├── tests/                 # 测试
├── assets/                # 设计笔记与分析文档
└── workspace/             # 用户源码与 write 输出
    ├── main.ml
    └── output/
```

## 与参考项目的对应关系

| 参考项目 | 本项目 |
|----------|--------|
| Java DFA 词法分析 | 自实现 NFA/DFA 词法分析 + `tokens.json` |
| Python LL1/LR 分析器 | 递归下降 + `grammar.json` |
| （无） | 语义分析、TAC、优化、代码生成 |
