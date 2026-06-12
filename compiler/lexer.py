# 词法分析器 — 将源代码转换为 Token 序列，基于 DFA/NFA 实现最长匹配与优先级解析。"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple, Dict, Set, Union

from .errors import CompileDiagnostic, Severity, Stage, diagnostic

@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.kind:<12} {self.value!r:<10} L{self.line}:C{self.col})"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value, "line": self.line, "col": self.col}


class LexerError(Exception):
    pass


@dataclass
class LexResult:
    tokens: List[Token] = field(default_factory=list)
    errors: List[CompileDiagnostic] = field(default_factory=list)
    warnings: List[CompileDiagnostic] = field(default_factory=list)


class Lexer:
    MAX_ERRORS = 100
    MAX_WARNINGS = 100
    MAX_TOKEN_LEN = 2000

    def __init__(self, source: str, rules_path: Optional[Path] = None, trace: bool = False):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.errors: List[CompileDiagnostic] = []
        self.warnings: List[CompileDiagnostic] = []
        rules_path = rules_path or Path(__file__).parent.parent / "grammar" / "tokens.json"
        self.rules = self._load_rules(rules_path)
        self.charsets = self.rules.get("charsets", {})
        self.trace = trace

        self.float_dfa = None
        self.int_dfa = None
        self.pattern_dfas: List[Tuple[DFA, str, bool, int]] = []
        self.first_char_map: Dict[str, List[Tuple[DFA, str, bool, int]]] = {}
        self.safe_patterns: List[Tuple[DFA, str, bool, int]] = []

        for priority, spec in enumerate(self.rules["patterns"]):
            name = spec["name"]
            regex = spec["regex"]
            skip = spec.get("skip", False)

            processed_regex = self._process_charsets(regex)
            self._trace(f"[PROCESSED] {name}: {regex} -> {processed_regex}")

            parser = RegexParser(processed_regex, self.charsets)
            nfa = parser.to_nfa()
            dfa = RegexParser.nfa_to_dfa(nfa)

            for state in dfa.states:
                if nfa.accept in state.nfa_states:
                    state.is_accept = True
                    state.token_type = name
                    state.priority = priority

            dfa_entry = (dfa, name, skip, priority)
            self.pattern_dfas.append(dfa_entry)

            # 区分数字DFA
            if name == "FLOAT_LIT":
                self.float_dfa = dfa_entry
            elif name == "INT_LIT":
                self.int_dfa = dfa_entry
            elif name not in ("FLOAT_LIT", "INT_LIT"):
                self.safe_patterns.append(dfa_entry)

            self._trace(f"[COMPILED] Pattern '{name}' -> DFA with {len(dfa.states)} states")

        # 构建首字符映射
        for dfa, name, skip, priority in self.pattern_dfas:
            if dfa.start and dfa.start.transitions:
                for char in dfa.start.transitions.keys():
                    if char not in self.first_char_map:
                        self.first_char_map[char] = []
                    self.first_char_map[char].append((dfa, name, skip, priority))

        self.operators = sorted(
            self.rules.get("operators", {}).items(),
            key=lambda x: -len(x[0])
        )
        self.keywords = sorted(
            self.rules.get("keywords", {}).items(),
            key=lambda x: -len(x[0])
        )

    @staticmethod
    def _load_rules(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"词法规则文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _trace(self, msg: str) -> None:
        if self.trace:
            print(msg)

    def _process_charsets(self, pattern: str) -> str:
        # 按长度降序排列，确保较长的名称（如 nonl_blank）优先于较短的名称（如 blank）被匹配
        sorted_names = sorted(self.charsets.keys(), key=len, reverse=True)
    
        pattern_regex = '|'.join(re.escape(name) for name in sorted_names)
        
        # 定义替换回调函数
        def replace_match(match):
            matched_name = match.group(0)
            # 将匹配到的独立名称包裹上 {{}}
            return f"{{{{{matched_name}}}}}"
        
        return re.sub(r'\b(' + pattern_regex + r')\b', replace_match, pattern)
    
    
    def _current(self) -> str:
        return self.source[self.pos: self.pos + 1] if self.pos < len(self.source) else ""

    # 统一字符前进逻辑：所有场景必须调用，保证游标稳定
    def _advance(self, n: int = 1) -> None:
        for _ in range(n):
            if self.pos < len(self.source) and self.source[self.pos] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1

    # 错误收集接口
    def _add_error(self, message: str, line: int, col: int, code: str = "E101", suggestion: Optional[str] = None) -> None:
        if len(self.errors) >= self.MAX_ERRORS:
            return
        self.errors.append(
            diagnostic(Stage.LEXER, message, line=line, col=col, code=code, suggestion=suggestion or "")
        )

    # 警告收集接口
    def _add_warn(self, message: str, line: int, col: int, code: str = "W100", suggestion: Optional[str] = None) -> None:
        if len(self.warnings) >= self.MAX_WARNINGS:
            return
        self.warnings.append(
            diagnostic(Stage.LEXER, message, line=line, col=col, code=code, severity=Severity.WARNING, suggestion=suggestion or "")
        )

    def _validate_number(self, text: str, line: int, col: int) -> bool:
        if text.count(".") > 1:
            self._add_error(
                f"非法数字 '{text}'：包含多个小数点",
                line, col, "E102",
                "检查是否误写为小数或表达式"
            )
            return False

        if text.endswith("."):
            self._add_error(
                f"非法数字 '{text}'：小数点后缺少数字",
                line, col, "E103",
                "补充小数部分"
            )
            return False

        try:
            float(text)
        except ValueError:
            self._add_error(
                f"数字格式 '{text}'非法",
                line, col, "E104",
                "检查是否混入非法字符（如 12a、1..2）"
            )
            return False

        return True

    def _match_dfa(self, dfa: DFA, start_pos: int, max_len: int = None) -> Tuple[Optional[str], int]:
        if max_len is None:
            max_len = self.MAX_TOKEN_LEN
        current_state = dfa.start
        last_accept_pos = -1
        total_len = len(self.source)
        current_idx = start_pos

        while current_idx < total_len and (current_idx - start_pos) < max_len:
            char = self.source[current_idx]
            if char not in current_state.transitions:
                break
            current_state = current_state.transitions[char]
            current_idx += 1
            if current_state.is_accept:
                last_accept_pos = current_idx

        if (current_idx - start_pos) >= self.MAX_TOKEN_LEN and last_accept_pos != -1:
            self._add_warn(
                f"Token 长度超出最大限制({self.MAX_TOKEN_LEN})",
                self.line, self.col, "E110",
                "请缩短标识符/字面量长度"
            )

        if last_accept_pos == -1:
            return None, 0
        match_str = self.source[start_pos:last_accept_pos]
        return match_str, last_accept_pos - start_pos

    def next_token(self) -> Optional[Token]:
        source_total = len(self.source)
        if self.pos > source_total * 2:
            self._add_error(
                "词法分析器游标异常，检测到无限循环，强制终止",
                self.line, self.col, "E100",
                "请检查源码是否有语法错误导致词法分析器卡死"
            )
            return None

        while self.pos < source_total:
            start_line, start_col = self.line, self.col
            current_char = self._current()
            self._trace(f"\n[POS] L{start_line}:C{start_col}, char={current_char!r}")

            # 1. 字符串字面量（最高优先级）
            if current_char == '"':
                quote_char = current_char
                self._advance(1)
                string_value = []
                escaped = False
                is_unclosed = False

                while self.pos < source_total:
                    ch = self._current()
                    if escaped:
                        escape_map = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f'}
                        string_value.append(escape_map.get(ch, ch))
                        escaped = False
                        self._advance(1)
                    elif ch == quote_char:
                        self._advance(1)
                        self._trace(f"[STRING MATCH] {''.join(string_value)!r}")
                        return Token("STRING_LIT", ''.join(string_value), start_line, start_col)
                    elif ch == '\n':
                        self._add_error(
                            f"未闭合的字符串字面量（在第{start_line}行开始）",
                            start_line, start_col, "E107",
                            "请在字符串末尾添加对应的双引号 \""
                        )
                        is_unclosed = True
                        break
                    else:
                        string_value.append(ch)
                        self._advance(1)

                # 文件末尾仍未闭合
                if not is_unclosed and self.pos >= source_total:
                    self._add_error(
                        f"未闭合的字符串字面量（在第{start_line}行开始，文件末尾结束）",
                        start_line, start_col, "E107",
                        "请在字符串末尾添加对应的双引号 \""
                    )
                    is_unclosed = True

                err_content = ''.join(string_value)
                return Token("ERROR", err_content, start_line, start_col)

            # 2. 数字匹配
            if current_char.isdigit() or (current_char == '.' and self.pos + 1 < source_total and self.source[self.pos+1].isdigit()):
                float_text, float_len = self._match_dfa(self.float_dfa[0], self.pos) if self.float_dfa else (None, 0)
                if float_text:
                    self._validate_number(float_text, start_line, start_col)
                    self._advance(float_len)
                    return Token("FLOAT_LIT", float_text, start_line, start_col)

                int_text, int_len = self._match_dfa(self.int_dfa[0], self.pos) if self.int_dfa else (None, 0)
                if int_text:
                    self._validate_number(int_text, start_line, start_col)
                    self._advance(int_len)
                    return Token("INT_LIT", int_text, start_line, start_col)

                # DFA匹配失败：当前字符为非法数字，单字符ERROR
                self._advance(1)
                return Token("ERROR", current_char, start_line, start_col)

            # 3. 运算符匹配（最长优先）
            for op, kind in self.operators:
                if self.source.startswith(op, self.pos):
                    self._trace(f"[OP MATCH] {op} -> {kind}")
                    self._advance(len(op))
                    return Token(kind, op, start_line, start_col)

            # 4. 关键字匹配（最长优先）
            for kw, kind in self.keywords:
                if self.source.startswith(kw, self.pos):
                    end_pos = self.pos + len(kw)
                    if end_pos < source_total:
                        next_ch = self.source[end_pos]
                        if next_ch.isalnum() or next_ch == "_":
                            continue
                    self._trace(f"[KW MATCH] {kw} -> {kind}")
                    self._advance(len(kw))
                    return Token(kind, kw, start_line, start_col)

            # 5. DFA匹配
            best_match: Optional[str] = None
            best_len = 0
            best_skip = False
            candidate_dfas = self.first_char_map.get(current_char, [])
            if not candidate_dfas:
                candidate_dfas = self.safe_patterns

            for pattern_info in candidate_dfas:
                dfa, name, skip, priority = pattern_info
                if name in ("FLOAT_LIT", "INT_LIT"):
                    continue
                match_txt, match_len = self._match_dfa(dfa, self.pos)
                if not match_txt or match_len == 0:
                    continue
                if match_len > best_len:
                    best_match = match_txt
                    best_len = match_len
                    best_skip = skip

            if best_match and best_len > 0:
                self._trace(f"[DFA MATCH] -> {best_match!r} (len={best_len})")
                # 空白/跳过类Token
                if best_skip:
                    self._advance(best_len)
                    continue

                if len(best_match) == 0:
                    self._add_error(
                        "空标识符不合法",
                        start_line, start_col, "E108",
                        "请输入合法的标识符，由字母、数字、下划线组成"
                    )
                    self._advance(best_len)
                    return Token("ERROR", "", start_line, start_col)

                has_err = False
                if re.search(r"[^a-zA-Z0-9_]", best_match):
                    self._add_error(
                        f"标识符 '{best_match}' 含非法字符",
                        start_line, start_col, "E106",
                        "仅允许字母、数字、下划线"
                    )
                    has_err = True
                elif best_match[0].isdigit():
                    self._add_error(
                        f"标识符 '{best_match}' 不能以数字开头",
                        start_line, start_col, "E105",
                        "以字母或下划线开头"
                    )
                    has_err = True

                if has_err:
                    self._advance(best_len)
                    return Token("ERROR", best_match, start_line, start_col)

                # 合法标识符
                self._advance(best_len)
                return Token("IDENT", best_match, start_line, start_col)

            # 6. 无法识别的字符：统一单字符ERROR，最小粒度错误标记
            self._trace(f"[UNKNOWN] {current_char!r}")
            if self.pos + 1 < source_total:
                next_ch = self.source[self.pos + 1]
                if not (next_ch.isalnum() or next_ch in "_ \t\r\n"):
                    self._add_error(
                        f"连续非法字符 '{current_char}{next_ch}'",
                        start_line, start_col, "E106",
                        "检查是否输入错误的符号组合"
                    )
                    # 连续非法字符一次性消费两个，避免重复报错
                    self._advance(2)
                    return Token("ERROR", current_char + next_ch, start_line, start_col)
            else:
                self._add_error(
                    f"无法识别的字符 '{current_char}'",
                    start_line, start_col, "E101",
                    "检查是否拼写错误或使用了不支持的符号"
                )

            # 单字符消费 + 单字符ERROR
            self._advance(1)
            return Token("ERROR", current_char, start_line, start_col)

        self._trace("[EOF]")
        return None

    def tokenize(self) -> LexResult:
        tokens: List[Token] = []
        while True:
            tok = self.next_token()
            if tok is None:
                break
            tokens.append(tok)
        tokens.append(Token("EOF", "", self.line, self.col))
        return LexResult(tokens=tokens, errors=list(self.errors), warnings=list(self.warnings))

    def __iter__(self) -> Iterator[Token]:
        return iter(self.tokenize().tokens)


class NFAState:
    _counter = 0

    def __init__(self):
        self.id = NFAState._counter
        NFAState._counter += 1
        # 普通边：可以是单个字符或字符集合
        self.transitions: Dict[Union[str, frozenset], Set[NFAState]] = {}
        # ε边
        self.epsilon: Set[NFAState] = set()

    def add_transition(self, symbol: Union[str, frozenset], state: NFAState) -> None:
        if symbol not in self.transitions:
            self.transitions[symbol] = set()
        self.transitions[symbol].add(state)

    def add_epsilon(self, state: NFAState) -> None:
        self.epsilon.add(state)

    def __repr__(self) -> str:
        return f"NFAState({self.id})"


class NFA:
    def __init__(self, start: NFAState, accept: NFAState):
        self.start = start
        self.accept = accept

    def __repr__(self) -> str:
        return f"NFA(start={self.start.id}, accept={self.accept.id})"


class DFAState:
    def __init__(self, nfa_states: Set[NFAState]):
        self.nfa_states = frozenset(nfa_states)
        self.transitions: Dict[str, DFAState] = {}
        self.is_accept = False
        self.token_type: Optional[str] = None  # 接受状态对应的token类型
        self.priority: int = float('inf')      # 优先级，越小越高

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DFAState):
            return False
        return self.nfa_states == other.nfa_states

    def __hash__(self) -> int:
        return hash(self.nfa_states)

    def __repr__(self) -> str:
        ids = sorted(s.id for s in self.nfa_states)
        return f"DFAState({ids}, accept={self.is_accept}, token={self.token_type})"


class DFA:
    def __init__(self):
        self.start: Optional[DFAState] = None
        self.states: List[DFAState] = []

    def __repr__(self) -> str:
        return f"DFA(start={self.start}, states={len(self.states)})"


class RegexParser:
    # 使用"."作为连接符
    CONCAT = "."
    PRIORITY = {
        "|": 1,
        CONCAT: 2,
        "*": 3,
        "+": 3,
        "?": 3
    }

    def __init__(self, regex: str, charsets: Dict[str, str] = None):
        self.regex = regex
        self.charsets = charsets or {}
        # 转义字符映射
        self.escape_chars = {
            "\\.": ".",
            "\\|": "|",
            "\\*": "*",
            "\\+": "+",
            "\\?": "?",
            "\\(": "(",
            "\\)": ")",
            "\\\\": "\\",
            "\\{": "{",
            "\\}": "}",
            "\\'": "'",
            '\\"': '"'
        }

    # 将正则表达式拆分为token列表，正确处理转义字符和字符集标记
    def _tokenize(self) -> List[str]:
        tokens = []
        i = 0
        n = len(self.regex)

        while i < n:
            # 处理字符集标记 {{name}}
            if self.regex[i] == "{" and i + 3 < n and self.regex[i:i+2] == "{{":
                end = self.regex.find("}}", i)
                if end != -1:
                    charset_name = self.regex[i+2:end]
                    tokens.append(f"{{{{{charset_name}}}}}")
                    i = end + 2
                    continue

            # 处理转义字符
            if self.regex[i] == "\\" and i + 1 < n:
                tokens.append(self.regex[i:i+2])
                i += 2
            else:
                # 普通字符或元字符
                tokens.append(self.regex[i])
                i += 1

        return tokens

    # 在token列表中插入显式的连接符
    def add_concat(self) -> List[str]:
        tokens = self._tokenize()
        result = []

        for i in range(len(tokens)):
            token = tokens[i]
            result.append(token)

            if i == len(tokens) - 1:
                continue

            next_token = tokens[i+1]

            # 判断是否需要插入连接符
            left_can_concat = (
                # 普通字符（非元字符）
                (len(token) == 1 and token not in "()|*+?.")
                # 转义字符
                or len(token) == 2
                # 字符集标记
                or token.startswith("{{") and token.endswith("}}")
                # 右括号
                or token == ")"
                # 闭包运算符
                or token in "*+?"
            )

            right_can_concat = (
                # 普通字符（非元字符）
                (len(next_token) == 1 and next_token not in ")|*+?.")
                # 转义字符
                or len(next_token) == 2
                # 字符集标记
                or next_token.startswith("{{") and next_token.endswith("}}")
                # 左括号
                or next_token == "("
            )

            if left_can_concat and right_can_concat:
                result.append(self.CONCAT)

        return result

    # 将正则表达式转换为后缀表达式（支持字符集转移）
    def to_postfix(self) -> List[str]:
        tokens = self.add_concat()
        output = []
        stack = []

        self._trace(f"[TOKENS] {tokens}")

        for token in tokens:
            if token == "(":
                stack.append(token)
            elif token == ")":
                while stack and stack[-1] != "(":
                    output.append(stack.pop())
                if not stack:
                    raise ValueError("正则表达式括号不匹配")
                stack.pop()  # 弹出左括号
            elif token in self.PRIORITY:
                # 处理运算符优先级
                while (
                    stack
                    and stack[-1] != "("
                    and self.PRIORITY[stack[-1]] >= self.PRIORITY[token]
                ):
                    output.append(stack.pop())
                stack.append(token)
            else:
                # 普通字符、转义字符或字符集
                output.append(token)

        # 弹出栈中剩余的运算符
        while stack:
            if stack[-1] == "(":
                raise ValueError("正则表达式括号不匹配")
            output.append(stack.pop())

        self._trace(f"[后缀表达式] {output}")
        return output

    def _trace(self, msg: str) -> None:
        # 内部调试用
        pass

    # 根据后缀表达式构建NFA（支持字符集转移）
    def to_nfa(self) -> NFA:
        postfix = self.to_postfix()
        stack: List[NFA] = []

        for token in postfix:
            if token == self.CONCAT:
                # 连接操作：n1的接受状态ε转移到n2的开始状态
                if len(stack) < 2:
                    raise ValueError(f"无效的连接操作，栈大小: {len(stack)}，后缀表达式: {postfix}")
                n2 = stack.pop()
                n1 = stack.pop()
                n1.accept.add_epsilon(n2.start)
                stack.append(NFA(n1.start, n2.accept))
            elif token == "|":
                # 或操作：创建新的开始和接受状态
                if len(stack) < 2:
                    raise ValueError(f"无效的或操作，栈大小: {len(stack)}，后缀表达式: {postfix}")
                n2 = stack.pop()
                n1 = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n1.start)
                s.add_epsilon(n2.start)
                n1.accept.add_epsilon(e)
                n2.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            elif token == "*":
                # 闭包操作：创建新的开始和接受状态
                if len(stack) < 1:
                    raise ValueError(f"无效的闭包操作，栈大小: {len(stack)}，后缀表达式: {postfix}")
                n = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n.start)
                s.add_epsilon(e)
                n.accept.add_epsilon(n.start)
                n.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            elif token == "+":
                # 正闭包操作：至少出现一次
                if len(stack) < 1:
                    raise ValueError(f"无效的正闭包操作，栈大小: {len(stack)}，后缀表达式: {postfix}")
                n = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n.start)
                n.accept.add_epsilon(n.start)
                n.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            elif token == "?":
                # 可选操作：出现0次或1次
                if len(stack) < 1:
                    raise ValueError(f"无效的可选操作，栈大小: {len(stack)}，后缀表达式: {postfix}")
                n = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n.start)
                s.add_epsilon(e)
                n.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            else:
                # 基本元素：单个字符、转义字符或字符集
                s1 = NFAState()
                s2 = NFAState()

                if token.startswith("{{") and token.endswith("}}"):
                    # 字符集
                    charset_name = token[2:-2]
                    if charset_name in self.charsets:
                        if charset_name == "cjk":
                            chars = ("CJK",)
                        else:
                            chars = frozenset(self.charsets[charset_name])
                        s1.add_transition(chars, s2)
                    else:
                        print()
                        raise ValueError(f"未定义的字符集: {charset_name}")
                elif len(token) == 2 and token[0] == "\\":
                    # 转义字符
                    actual_char = token[1]
                    s1.add_transition(actual_char, s2)
                else:
                    # 普通字符
                    s1.add_transition(token, s2)

                stack.append(NFA(s1, s2))

        if len(stack) != 1:
            raise ValueError(f"正则表达式解析失败，栈大小: {len(stack)}，后缀表达式: {postfix}")

        return stack.pop()

    # 将NFA转换为DFA（子集构造法）
    @staticmethod
    def nfa_to_dfa(nfa: NFA) -> DFA:
        def epsilon_closure(states: Set[NFAState]) -> Set[NFAState]:
            """计算状态集的ε闭包"""
            stack = list(states)
            closure = set(states)

            while stack:
                s = stack.pop()
                for nxt in s.epsilon:
                    if nxt not in closure:
                        closure.add(nxt)
                        stack.append(nxt)
            return closure

        # 初始状态：开始状态的ε闭包
        start_closure = epsilon_closure({nfa.start})
        start_state = DFAState(start_closure)

        dfa = DFA()
        dfa.start = start_state
        dfa.states = [start_state]

        # 使用状态映射表确保唯一性
        state_map: Dict[frozenset[NFAState], DFAState] = {}
        state_map[start_state.nfa_states] = start_state

        unmarked = [start_state]  # 待处理的状态

        while unmarked:
            current_dfa_state = unmarked.pop()

            # 收集所有可能的字符转移
            char_transitions: Dict[str, Set[NFAState]] = {}

            for nfa_state in current_dfa_state.nfa_states:
                for sym, targets in nfa_state.transitions.items():
                    if isinstance(sym, frozenset):
                        # 字符集转移：为每个字符单独添加转移
                        for char in sym:
                            if char not in char_transitions:
                                char_transitions[char] = set()
                            char_transitions[char].update(targets)
                    
                    else:
                        # 单个字符转移
                        if sym not in char_transitions:
                            char_transitions[sym] = set()
                        char_transitions[sym].update(targets)

            # 为每个字符创建新的DFA状态
            for char, nfa_targets in char_transitions.items():
                # 计算目标状态的ε闭包
                target_closure = epsilon_closure(nfa_targets)
                target_key = frozenset(target_closure)

                # 检查是否已经存在这个状态
                if target_key not in state_map:
                    new_dfa_state = DFAState(target_closure)
                    state_map[target_key] = new_dfa_state
                    dfa.states.append(new_dfa_state)
                    unmarked.append(new_dfa_state)
                else:
                    new_dfa_state = state_map[target_key]

                # 添加转移
                current_dfa_state.transitions[char] = new_dfa_state

        return dfa
