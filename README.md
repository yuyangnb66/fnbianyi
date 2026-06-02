# MiniLang 简单编译器

参考 [CompilationPrinciple](https://github.com/qianqianjun/CompilationPrinciple) 项目的词法/语法分析思路，实现一个**完整但精炼**的教学用编译器，涵盖编译原理课程的全部核心阶段。

## 编译流水线

```
源码 (.ml) → 词法分析 → 语法分析 → 语义分析 → 中间代码(TAC) → 优化 → 目标代码(Python)
```

| 阶段 | 模块 | 说明 |
|------|------|------|
| 词法分析 | `compiler/lexer.py` | 从 `grammar/tokens.json` 加载 Token 规则 |
| 语法分析 | `compiler/parser.py` | 递归下降，依据 `grammar/grammar.json` 的 BNF |
| 语义分析 | `compiler/semantic.py` | 符号表、作用域、类型检查 |
| 中间代码 | `compiler/tac.py` | 三地址码 (Three-Address Code) |
| 优化 | `compiler/optimizer.py` | 常量折叠、复制传播、死代码消除 |
| 目标代码 | `compiler/codegen.py` | 生成可执行的 Python 代码 |

## MiniLang 语法示例

```c
int a;
int b;
a = 10;
b = 20;
print(a + b);

while (i <= n) {
    result = result * i;
    i = i + 1;
}

if (x > 10) {
    y = 100;
} else {
    y = 0;
}
```

支持：`int` / `float` 变量声明、`+ - * /` 算术、比较运算、`if-else`、`while`、`print`。

## 快速开始

需要 Python 3.10+。

```bash
# 编译并运行示例
python -m compiler.main examples/hello.ml --run

# 查看完整编译过程
python -m compiler.main examples/factorial.ml --dump all --run

# 指定输出文件
python -m compiler.main examples/if_else.ml -o out.py --run
```

## 项目结构

```
fnbianyi/
├── grammar/                 # 语法规则库
│   ├── tokens.json          # 词法规则（关键字、运算符、正则）
│   └── grammar.json         # BNF 产生式
├── compiler/
│   ├── lexer.py             # 词法分析
│   ├── parser.py            # 语法分析
│   ├── ast_nodes.py         # AST 节点
│   ├── semantic.py          # 语义分析
│   ├── tac.py               # 中间代码生成
│   ├── optimizer.py         # 优化
│   ├── codegen.py           # 目标代码生成
│   ├── compiler.py          # 流水线调度
│   └── main.py              # 命令行入口
└── examples/                # 示例程序
    ├── hello.ml
    ├── factorial.ml
    ├── if_else.ml
    └── float_calc.ml
```

## 与参考项目的对应关系

| 参考项目 | 本项目 |
|----------|--------|
| Java DFA 词法分析 | Python 正则词法分析 + `tokens.json` 规则库 |
| Python LL1/LR 分析器 | 递归下降语法分析 + `grammar.json` BNF 库 |
| （无） | 语义分析、TAC、优化、代码生成 |

## 扩展建议

- 在 `grammar/tokens.json` 中添加新关键字/运算符
- 在 `grammar/grammar.json` 中扩展产生式，并在 `parser.py` 中实现对应解析函数
- 将目标后端改为 x86 汇编或 LLVM IR
