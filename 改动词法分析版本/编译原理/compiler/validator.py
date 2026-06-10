"""静态检查 — 在词法 Token 流上尽可能多地发现结构/风格问题。"""

from __future__ import annotations

from typing import List, Set

from .errors import CompileDiagnostic, Severity, Stage, diagnostic
from .lexer import Token

STMT_START = {"INT", "FLOAT", "IF", "WHILE", "PRINT", "PRINTN", "IDENT", "LBRACE", "RBRACE"}


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
                diagnostic(Stage.VALIDATOR, "源程序为空", code="W001", severity=Severity.WARNING)
            )
        for i, line in enumerate(source.splitlines(), 1):
            if "\t" in line:
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        "建议使用空格而非 Tab 缩进",
                        line=i,
                        col=line.index("\t") + 1,
                        severity=Severity.WARNING,
                        code="W002",
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
                    )
                )
        return diags

    def _check_brackets(self, tokens: List[Token]) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        stack: List[tuple[str, Token]] = []
        pairs = {"(": ")", "{": "}", "[": "]"}
        inv = {v: k for k, v in pairs.items()}
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
                            Stage.SYNTAX,
                            f"多余的闭合符号 '{ch}'，没有对应的开始符号",
                            line=tok.line,
                            col=tok.col,
                            code="E101",
                        )
                    )
                else:
                    open_ch, open_tok = stack.pop()
                    if pairs[open_ch] != ch:
                        diags.append(
                            diagnostic(
                                Stage.SYNTAX,
                                f"括号不匹配：'{open_ch}' (L{open_tok.line}) 与 '{ch}' 配对错误",
                                line=tok.line,
                                col=tok.col,
                                code="E102",
                            )
                        )

        for open_ch, open_tok in stack:
            diags.append(
                diagnostic(
                    Stage.SYNTAX,
                    f"未闭合的 '{open_ch}'",
                    line=open_tok.line,
                    col=open_tok.col,
                    code="E103",
                )
            )
        return diags

    def _check_tokens(self, tokens: List[Token]) -> List[CompileDiagnostic]:
        diags: List[CompileDiagnostic] = []
        keywords = {"int", "float", "if", "else", "while", "print", "printn", "return"}

        for i, tok in enumerate(tokens):
            if tok.kind == "ERROR":
                diags.append(
                    diagnostic(
                        Stage.LEXER,
                        f"非法字符或无法识别的词法单元: {tok.value!r}",
                        line=tok.line,
                        col=tok.col,
                        code="E001",
                    )
                )
            if tok.kind == "IDENT" and tok.value in keywords:
                diags.append(
                    diagnostic(
                        Stage.LEXER,
                        f"关键字 '{tok.value}' 不能作为普通标识符使用",
                        line=tok.line,
                        col=tok.col,
                        code="E002",
                    )
                )
            if tok.kind == "INT_LIT" and len(tok.value) > 1 and tok.value.startswith("0"):
                diags.append(
                    diagnostic(
                        Stage.VALIDATOR,
                        f"整数字面量 '{tok.value}' 有前导零，可能不符合预期",
                        line=tok.line,
                        col=tok.col,
                        severity=Severity.WARNING,
                        code="W010",
                    )
                )
            if i + 1 < len(tokens):
                cur, nxt = tok, tokens[i + 1]
                if cur.kind in ("INT_LIT", "FLOAT_LIT", "IDENT", "RPAREN", "RBRACE") and nxt.kind in (
                    "INT_LIT",
                    "FLOAT_LIT",
                    "IDENT",
                    "LPAREN",
                ):
                    if cur.kind == "IDENT" and nxt.kind == "LPAREN":
                        continue
                    if cur.kind == "IDENT" and nxt.kind == "LBRACKET":
                        continue
                    if cur.kind == "RBRACE" and nxt.kind in ("IDENT", "INT", "FLOAT", "STRING", "IF", "WHILE", "FOR", "PRINT", "PRINTN"):
                        continue
                    diags.append(
                        diagnostic(
                            Stage.SYNTAX,
                            f"'{cur.value}' 与 '{nxt.value}' 之间缺少运算符或分隔符",
                            line=nxt.line,
                            col=nxt.col,
                            code="E104",
                        )
                    )
                if cur.kind == "ASSIGN" and nxt.kind == "ASSIGN":
                    diags.append(
                        diagnostic(
                            Stage.SYNTAX,
                            "检测到连续的 '='，是否想写 '==' 比较运算？",
                            line=cur.line,
                            col=cur.col,
                            code="E105",
                        )
                    )
                if cur.kind in ("PLUS", "MINUS", "STAR", "SLASH") and nxt.kind in (
                    "PLUS",
                    "MINUS",
                    "STAR",
                    "SLASH",
                    "SEMI",
                    "RPAREN",
                ):
                    diags.append(
                        diagnostic(
                            Stage.SYNTAX,
                            f"运算符 '{cur.value}' 后缺少操作数",
                            line=nxt.line,
                            col=nxt.col,
                            code="E106",
                        )
                    )
                if cur.kind == "SEMI" and nxt.kind == "SEMI":
                    diags.append(
                        diagnostic(
                            Stage.VALIDATOR,
                            "连续的分号 ';;'，存在空语句",
                            line=nxt.line,
                            col=nxt.col,
                            severity=Severity.WARNING,
                            code="W011",
                        )
                    )
                if cur.kind in ("INT", "FLOAT") and nxt.kind != "IDENT":
                    diags.append(
                        diagnostic(
                            Stage.SYNTAX,
                            f"类型声明 '{cur.value}' 后应跟变量名",
                            line=nxt.line,
                            col=nxt.col,
                            code="E107",
                        )
                    )
                if cur.kind == "ELSE" and nxt.kind != "LBRACE":
                    diags.append(
                        diagnostic(
                            Stage.SYNTAX,
                            "'else' 后应跟代码块 '{ ... }'",
                            line=nxt.line,
                            col=nxt.col,
                            code="E108",
                        )
                    )
        return diags

    def _check_statements(self, tokens: List[Token]) -> List[CompileDiagnostic]:
        """仅在主语句层级检查缺分号，跳过括号/控制结构内部。"""
        diags: List[CompileDiagnostic] = []
        depth = 0
        for i, tok in enumerate(tokens):
            if tok.kind in ("LPAREN", "LBRACE"):
                depth += 1
            elif tok.kind in ("RPAREN", "RBRACE"):
                depth = max(0, depth - 1)
            if depth > 0 or tok.kind not in ("IDENT", "INT_LIT", "FLOAT_LIT", "RPAREN", "STRING_LIT"):
                continue
            if tok.kind == "RBRACE":
                continue
            j = i + 1
            while j < len(tokens) and tokens[j].kind in (
                "PLUS", "MINUS", "STAR", "SLASH", "IDENT", "INT_LIT", "FLOAT_LIT",
                "LPAREN", "RPAREN", "LBRACKET", "RBRACKET", "STRING_LIT", "COMMA",
            ):
                j += 1
            if any(tokens[k].kind == "SEMI" for k in range(i + 1, j)):
                continue
            if j < len(tokens) and tokens[j].kind in STMT_START and tokens[j].kind != "RBRACE":
                if tokens[i].line != tokens[j].line:
                    diags.append(
                        diagnostic(
                            Stage.SYNTAX,
                            "语句末尾可能缺少分号 ';'",
                            line=tokens[j].line,
                            col=tokens[j].col,
                            severity=Severity.WARNING,
                            code="W109",
                        )
                    )
        return diags
