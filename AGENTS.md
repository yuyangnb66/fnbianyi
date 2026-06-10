# AGENTS.md — MiniLang 编译器

## 项目概览

MiniLang 是一个教学用编译器，将类 C 语言翻译为可执行的 Python 代码。纯 Python 3.10+ 标准库实现，**零外部依赖**。

## 扩展名约定

- `.ml` — MiniLang 源文件
- 编译产物 `<源文件>.py`（可通过 `-o` 覆盖）

## 关键命令

```bash
# 桌面 IDE（无参数时默认入口）
python -m compiler.main

# 编译（生成 .py）
python -m compiler.main workspace/main.ml

# 编译并运行
python -m compiler.main workspace/main.ml --run

# 打印中间结果（tokens/ast/tac/opt/all）
python -m compiler.main workspace/main.ml --dump all

# 跳过优化
python -m compiler.main workspace/main.ml --no-opt --run

# 指定输出路径
python -m compiler.main workspace/main.ml -o out/app.py

# 打印词法器 NFA/DFA 逐 token 匹配过程
python -m compiler.main workspace/main.ml --trace

# 运行唯一测试：解析器错误恢复（需 3 秒内完成 35 个恶意输入）
python tests/test_parser_recovery.py
```

## 重要：不要做的事

- **不要 pip install 任何东西** — 项目无依赖，不需要虚拟环境
- **不要尝试 pytest / unittest** — 只有一个独立的 `test_parser_recovery.py`，用 `python` 直接运行
- **不要运行 lint / typecheck / formatter** — 项目无任何相关配置
- **不要修改 `workspace/*.py`** — 编译产物，已被 `.gitignore` 忽略
- **不要破坏解析器的恐慌恢复机制** — 解析器保证不会在恶意输入上挂死，测试用 3 秒超时验证。若修改 `parser.py`，必须重新运行 `python tests/test_parser_recovery.py`
- **不要在 `tokens.json` 中用 PCRE 正则**（如 `\d`、`[a-z]`）— 词法器使用自实现 NFA/DFA 引擎，仅支持字符集语法（`digit`、`letter`、`|`、`*`、`+`、`?`、`()`、`\x` 转义）。字面点号需写 `\.`

## 架构要点

### 编译流水线

```
源码(.ml) → lexer.py → parser.py → semantic.py → tac.py → optimizer.py → codegen.py → Python(.py)
              ↑            ↑
         tokens.json   grammar.json
```

各阶段顺序不可改变：前阶段出错会中断流水线（如语义错误不会继续生成目标代码）。

### 词法器（NFA/DFA 引擎）

词法器使用自实现的 NFA/DFA 正则引擎（`compiler/lexer.py` 中的 `RegexParser`、`NFA`、`DFA` 类），**非 Python `re` 模块**。流程：`tokens.json` 中的字符集正则 → Shunting-yard 中缀转后缀 → Thompson 构造 NFA → 子集构造 DFA → 最长匹配取 token。详细原理见 `assets/词法器对比分析.md`。

### 目录职责

| 目录 | 用途 | 注意 |
|------|------|------|
| `compiler/` | 编译器模块 | 无外部导入，纯 stdlib |
| `grammar/` | `tokens.json`（词法规则）、`grammar.json`（BNF 语法） | 由编译器运行时加载 |
| `editor/gui.py` | Tkinter 桌面 IDE | 无头环境下 Tkinter 可能不可用 |
| `workspace/` | 用户源码 (`*.ml`) 与 `write()` 输出 (`output/`) | 默认 IDE 打开 `workspace/main.ml` |
| `tests/` | 包含 `test_parser_recovery.py` | |
| `assets/` | 设计笔记与词法器分析 | 已被 gitignore |
| `改动词法分析版本/` | 旧版 DFA 词法器参考副本 | 来自 merge，仅作参考 |

### 代码生成双路径

`codegen.py` 对函数体和主程序体使用**不同的生成策略**：
- 函数 → AST 逐节点遍历（`_gen_function_ast`）
- 主程序体 → 基于 TAC 的标签分发循环（`_gen_blocks`）

修改代码生成时两者都需要考虑。

### 运行时内置函数

`compiler/runtime.py` 提供生成代码依赖的全局函数：`ml_input`、`ml_write`、`ml_getint`、`ml_split_line`。生成代码中的 `print()`、`input()` 等调用即为标准 Python。

### 错误处理约定

- 词法/语法/语义阶段会尽最大可能收集**所有错误**后返回（而非遇到第一个错误就停止）
- 词法器错误上限：50 条（`Lexer.MAX_ERRORS`）
- 所有错误通过 `compiler/errors.py` 的 `CompileDiagnostic` 结构传递

## 入口逻辑

`compiler/main.py` 的 `main()`：
1. `--gui` 或无源文件 → 启动 Tkinter IDE
2. 有源文件 → 编译流水线
3. `--dump` → 打印中间结果到 stdout
4. `--run` → 编译后 `exec()` 执行生成的 Python 代码
