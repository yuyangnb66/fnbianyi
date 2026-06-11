"""静态检查 — 在词法 Token 流上尽可能多地发现结构/风格问题。

统一 E4xx
E401: 多余的闭合符号，没有对应的开始符号
E402: 括号不匹配
E403: 未闭合的括号、大括号或中括号
E404: 语法元素之间缺少运算符或分隔符
E405: 检测到连续的等号 =，疑似误用比较运算符 ==
E406: 运算符后缺少操作数
E407: 类型声明关键字后应跟变量名
E408: else 关键字后未使用大括号包裹代码块

全模块警告 统一 W0xx
W001: 源程序为空
W002: 代码使用 Tab 进行缩进，禁止使用 Tab
W003: 行尾存在多余空白字符
W004: 整数字面量存在前导零，可能不符合预期
W005: 连续分号 ;;，存在空语句
W006: 语句末尾可能缺少分号 ;
"""

from __future__ import annotations

from typing import List, Set

from .errors import CompileDiagnostic, Severity, Stage, diagnostic
from .lexer import Token


# 完整的语句开头关键字集合
STMT_START = frozenset({
    "INT", "FLOAT", "STRING", "BOOL",
    "IF", "WHILE", "FOR",
    "PRINT", "PRINTN", "INPUT", "WRITE",
    "IDENT", "RETURN", "BREAK", "CONTINUE",
    "LBRACE", "RBRACE"
})

# 所有可以出现在表达式中的Token类型
EXPR_TOKENS = frozenset({
    "PLUS", "MINUS", "STAR", "SLASH",
    "AND", "OR", "NOT",
    "EQ", "NE", "LT", "LE", "GT", "GE",
    "IDENT", "INT_LIT", "FLOAT_LIT", "STRING_LIT",
    "LPAREN", "RPAREN", "LBRACKET", "RBRACKET", "COMMA"
})


class StaticValidator:
    def validate(self, source: str, tokens: List[Token]) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        diags.extend(self._check_source(source))
        diags.extend(self._check_brackets(tokens))
        diags.extend(self._check_tokens(tokens))
        diags.extend(self._check_statements(tokens))
        return diags

    def _check_source(self, source: str) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        if not source.strip():
            diags.append(
                diagnostic(
                    Stage.VALIDATOR,
                    "源程序为空",
                    line=1,
                    col=1,
                    code="W001",
                    severity=Severity.WARNING,
                    suggestion="请输入合法的程序代码"
                )
            )
        for i, line in enumerate(source.splitlines(), 1):
            if "\t" in line:
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "代码使用 Tab 进行缩进，禁止使用 Tab",
                        line=i,
                        col=line.index("\t") + 1,
                        severity=Severity.WARNING,
                        code="W002",
                        suggestion="将 Tab 符号替换为空格进行代码缩进"
                    )
                )
            if line.rstrip() != line and line.strip():
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "行尾存在多余空白字符",
                        line=i,
                        col=len(line.rstrip()) + 1,
                        severity=Severity.WARNING,
                        code="W003",
                        suggestion="删除行末尾多余的空格或空白字符"
                    )
                )
        return diags

    def _check_brackets(self, tokens: List[Token]) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        stack: List[tuple[str, Token]] = []
        pairs = {"(": ")", "{": "}", "[": "]"}
        open_kinds = {"LPAREN": "(", "LBRACE": "{", "LBRACKET": "["}
        close_map = {"RPAREN": ")", "RBRACE": "}", "RBRACKET": "]"}

        for tok in tokens:
            if tok.kind in open_kinds:
                stack.append((open_kinds[tok.kind], tok))
            elif tok.kind in close_map:
                ch = close_map[tok.kind]
                if not stack:
                    diags.append(
                        diagnostic(
                            Stage.VALIDATOR,
                            f"多余的闭合符号 '{ch}'，没有对应的开始符号",
                            line=tok.line,
                            col=tok.col,
                            code="E401",
                            suggestion="删除多余的闭合括号、大括号或中括号"
                        )
                    )
                else:
                    open_ch, open_tok = stack[-1]
                    if pairs[open_ch] == ch:
                        stack.pop()
                    else:
                        # 不匹配时不弹出栈顶
                        diags.append(
                            diagnostic(
                                Stage.VALIDATOR,
                                f"括号不匹配：'{open_ch}' (L{open_tok.line}) 与 '{ch}' 配对错误",
                                line=tok.line,
                                col=tok.col,
                                code="E402",
                                suggestion="修改闭合符号，保证左右括号、大括号、中括号一一对应"
                            )
                        )

        for open_ch, open_tok in stack:
            diags.append(
                diagnostic(
                    Stage.VALIDATOR,
                    f"未闭合的 '{open_ch}'",
                    line=open_tok.line,
                    col=open_tok.col,
                    code="E403",
                    suggestion="为当前符号补充对应的闭合符号"
                )
            )
        return diags

    def _check_tokens(self, tokens: List[Token]) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        # 所有需要检查"后缺少操作数"的运算符
        OPERATORS_NEED_OPERAND = frozenset({
            "PLUS", "MINUS", "STAR", "SLASH",
            "AND", "OR", "NOT",
            "EQ", "NE", "LT", "LE", "GT", "GE"
        })
        # 所有类型声明关键字
        TYPE_KEYWORDS = frozenset({"INT", "FLOAT", "STRING", "BOOL"})

        for i, tok in enumerate(tokens):
            if tok.kind == "INT_LIT" and len(tok.value) > 1 and tok.value.startswith("0"):
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        f"整数字面量 '{tok.value}' 有前导零，可能不符合预期",
                        line=tok.line,
                        col=tok.col,
                        severity=Severity.WARNING,
                        code="W004",
                        suggestion="去除数字前面多余的前导零"
                    )
                )
            
            if i + 1 >= len(tokens):
                continue
                
            cur, nxt = tok, tokens[i + 1]
            
            # 检查缺少运算符或分隔符
            if (cur.kind in ("INT_LIT", "FLOAT_LIT", "STRING_LIT", "IDENT", "RPAREN", "RBRACE", "RBRACKET") 
                and nxt.kind in ("INT_LIT", "FLOAT_LIT", "STRING_LIT", "IDENT", "LPAREN", "LBRACKET")):
                # 跳过合法的组合：函数调用、数组访问、语句跟随
                if cur.kind == "IDENT" and nxt.kind == "LPAREN":
                    continue
                if cur.kind == "IDENT" and nxt.kind == "LBRACKET":
                    continue
                if cur.kind == "RBRACE" and nxt.kind in STMT_START:
                    continue
                    
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        f"'{cur.value}' 与 '{nxt.value}' 之间缺少运算符或分隔符",
                        line=nxt.line,
                        col=nxt.col,
                        code="E404",
                        suggestion="在两个元素之间补充运算符、逗号或分号等分隔符"
                    )
                )
            
            # 检查连续等号
            if cur.kind == "ASSIGN" and nxt.kind == "ASSIGN":
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "检测到连续的等号 =，疑似误用比较运算符 ==",
                        line=cur.line,
                        col=cur.col,
                        code="E405",
                        suggestion="若为比较运算请改为 '=='，多余等号请删除"
                    )
                )
            
            # 检查运算符后缺少操作数
            if cur.kind in OPERATORS_NEED_OPERAND and nxt.kind in (
                "PLUS", "MINUS", "STAR", "SLASH",
                "AND", "OR", "NOT",
                "SEMI", "RPAREN", "RBRACE", "RBRACKET", "COMMA"
            ):
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        f"运算符 '{cur.value}' 后缺少操作数",
                        line=nxt.line,
                        col=nxt.col,
                        code="E406",
                        suggestion="在运算符右侧补充变量、数字等合法操作数"
                    )
                )
            
            # 检查连续分号
            if cur.kind == "SEMI" and nxt.kind == "SEMI":
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "连续的分号 ';;'，存在空语句",
                        line=nxt.line,
                        col=nxt.col,
                        severity=Severity.WARNING,
                        code="W005",
                        suggestion="删除多余的分号，避免无效空语句"
                    )
                )
            
            # 检查类型声明后无变量名（支持所有4种类型）
            if cur.kind in TYPE_KEYWORDS and nxt.kind != "IDENT":
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        f"类型声明 '{cur.value}' 后应跟变量名",
                        line=nxt.line,
                        col=nxt.col,
                        code="E407",
                        suggestion="在类型关键字后添加合法的变量名称"
                    )
                )

            if cur.kind == "ELSE" and nxt.kind not in ("LBRACE", "IF"):
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "'else' 后应跟代码块 '{ ... }' 或 'if'",
                        line=nxt.line,
                        col=nxt.col,
                        code="E408",
                        suggestion="在 else 后方使用大括号包裹代码逻辑，或使用 else if",
                    )
                )
        
        return diags

    
    # 检查语句末尾可能缺少分号的情况
    def _check_statements(self, tokens: List[Token]) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        depth = 0
        token_count = len(tokens)

        for i, tok in enumerate(tokens):
            # 只检查最外层语句
            if tok.kind in ("LPAREN", "LBRACE", "LBRACKET"):
                depth += 1
            elif tok.kind in ("RPAREN", "RBRACE", "RBRACKET"):
                depth = max(0, depth - 1)

            # 跳过括号内部、非表达式结尾Token和右大括号
            if depth > 0 or tok.kind not in ("IDENT", "INT_LIT", "FLOAT_LIT", "STRING_LIT", "RPAREN", "RBRACKET"):
                continue
            if tok.kind == "RBRACE":
                continue

            # 扫描到表达式结束位置
            j = i + 1
            while j < token_count and tokens[j].kind in EXPR_TOKENS:
                j += 1

            # 如果表达式内部已经有分号，跳过
            if any(tokens[k].kind == "SEMI" for k in range(i + 1, j)):
                continue

            # 情况1：后面跟着另一个语句开头
            if j < token_count and tokens[j].kind in STMT_START and tokens[j].kind != "RBRACE":
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "语句末尾可能缺少分号 ';'",
                        line=tokens[j].line,
                        col=tokens[j].col,
                        severity=Severity.WARNING,
                        code="W006",
                        suggestion="在当前语句末尾补充分号 ';' 结束语句"
                    )
                )
            # 情况2：到达程序末尾，最后一条语句
            elif j >= token_count:
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "语句末尾可能缺少分号 ';'",
                        line=tok.line,
                        col=tok.col + len(str(tok.value)),
                        severity=Severity.WARNING,
                        code="W006",
                        suggestion="在最后一条语句末尾补充分号 ';' 结束语句"
                    )
                )
        return diags