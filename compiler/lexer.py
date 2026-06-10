"""词法分析器 — 基于 NFA/DFA 的正则引擎，从 grammar/tokens.json 加载字符集规则。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple, Dict, Set, Union

from .errors import CompileDiagnostic, Stage, diagnostic


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r}, L{self.line})"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value, "line": self.line, "col": self.col}


class LexerError(Exception):
    pass


@dataclass
class LexResult:
    tokens: List[Token] = field(default_factory=list)
    errors: List[CompileDiagnostic] = field(default_factory=list)


class Lexer:
    MAX_ERRORS = 50

    def __init__(self, source: str, rules_path: Optional[Path] = None, trace: bool = False):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.errors: List[CompileDiagnostic] = []
        rules_path = rules_path or Path(__file__).parent.parent / "grammar" / "tokens.json"
        self.rules = self._load_rules(rules_path)
        self.charsets = self.rules.get("charsets", {})
        self.trace = trace

        self.pattern_dfas: List[Tuple[DFA, str, bool, int]] = []

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

            self.pattern_dfas.append((dfa, name, skip, priority))
            self._trace(f"[COMPILED] Pattern '{name}' -> DFA with {len(dfa.states)} states")

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
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _trace(self, msg: str) -> None:
        if self.trace:
            print(msg)

    def _process_charsets(self, pattern: str) -> str:
        for name in sorted(self.charsets.keys(), key=len, reverse=True):
            pattern = pattern.replace(name, f"{{{{{name}}}}}")
        return pattern

    def _current(self) -> str:
        return self.source[self.pos : self.pos + 1] if self.pos < len(self.source) else ""

    def _advance(self, n: int = 1) -> None:
        for _ in range(n):
            if self.pos < len(self.source) and self.source[self.pos] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1

    def _add_error(self, message: str, line: int, col: int, code: str = "E001") -> None:
        if len(self.errors) >= self.MAX_ERRORS:
            return
        self.errors.append(
            diagnostic(Stage.LEXER, message, line=line, col=col, code=code)
        )

    def _validate_number(self, text: str, line: int, col: int) -> bool:
        if text.count(".") > 1:
            self._add_error(f"非法数字格式 '{text}'（多个小数点）", line, col, "E003")
            return False
        if text.endswith("."):
            self._add_error(f"非法数字格式 '{text}'（小数点后缺少数字）", line, col, "E004")
            return False
        try:
            float(text)
        except ValueError:
            self._add_error(f"非法数字格式 '{text}'", line, col, "E005")
            return False
        return True

    def _match_dfa(self, dfa: DFA) -> Optional[str]:
        current_state = dfa.start
        last_accept_pos = -1
        current_pos = self.pos

        while current_pos < len(self.source):
            char = self.source[current_pos]

            if char in current_state.transitions:
                current_state = current_state.transitions[char]
                current_pos += 1

                if current_state.is_accept:
                    last_accept_pos = current_pos
            else:
                break

        if last_accept_pos != -1:
            return self.source[self.pos:last_accept_pos]
        return None

    def next_token(self) -> Optional[Token]:
        while self.pos < len(self.source):
            start_line, start_col = self.line, self.col

            self._trace(f"\n[POS] L{start_line}:C{start_col}, char={self._current()!r}")

            if self.source.startswith("//", self.pos):
                self._trace(f"[COMMENT] L{start_line}")
                end = self.source.find("\n", self.pos)
                if end == -1:
                    self.pos = len(self.source)
                else:
                    self.pos = end + 1
                    self.line += 1
                    self.col = 1
                continue

            for op, kind in self.operators:
                if self.source.startswith(op, self.pos):
                    self._trace(f"[OP MATCH] {op} -> {kind}")
                    self._advance(len(op))
                    return Token(kind, op, start_line, start_col)

            for kw, kind in self.keywords:
                if not self.source.startswith(kw, self.pos):
                    continue

                end_pos = self.pos + len(kw)
                if end_pos < len(self.source):
                    ch = self.source[end_pos]
                    if ch.isalnum() or ch == "_":
                        continue

                self._trace(f"[KW MATCH] {kw} -> {kind}")
                self._advance(len(kw))
                return Token(kind, kw, start_line, start_col)

            best_match: Optional[str] = None
            best_pattern: Optional[Tuple[DFA, str, bool, int]] = None
            best_length = 0
            best_priority = float('inf')

            for pattern_info in self.pattern_dfas:
                dfa, name, skip, priority = pattern_info
                match = self._match_dfa(dfa)

                if match is not None:
                    match_len = len(match)
                    if (match_len > best_length) or (match_len == best_length and priority < best_priority):
                        best_match = match
                        best_pattern = pattern_info
                        best_length = match_len
                        best_priority = priority

            if best_match is not None and best_pattern is not None:
                dfa, name, skip, priority = best_pattern
                self._trace(f"[DFA MATCH] {name} -> {best_match!r} (length={best_length}, priority={priority})")

                if skip:
                    self._advance(len(best_match))
                    continue

                if name in ("INT_LIT", "FLOAT_LIT"):
                    self._validate_number(best_match, start_line, start_col)

                if name == "IDENT" and best_match[0].isdigit():
                    self._trace("[ERROR] IDENT starts with digit")
                    self._add_error(
                        f"标识符 '{best_match}' 不能以数字开头",
                        start_line,
                        start_col,
                        "E006"
                    )
                    self._advance(len(best_match))
                    return Token("ERROR", best_match, start_line, start_col)

                if name == "STRING_LIT":
                    raw_len = len(best_match)
                    best_match = self._decode_string(best_match)
                    self._advance(raw_len)
                else:
                    self._advance(len(best_match))
                return Token(name, best_match, start_line, start_col)

            ch = self._current()
            if not ch:
                break

            self._trace(f"[UNKNOWN] {ch!r}")

            self._add_error(
                f"无法识别的字符 {ch!r}",
                start_line,
                start_col,
                "E001"
            )
            self._advance(1)
            return Token("ERROR", ch, start_line, start_col)

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
        return LexResult(tokens=tokens, errors=list(self.errors))

    def __iter__(self) -> Iterator[Token]:
        return iter(self.tokenize().tokens)

    @staticmethod
    def _decode_string(text: str) -> str:
        inner = text[1:-1]
        return inner.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')


class NFAState:
    _counter = 0

    def __init__(self):
        self.id = NFAState._counter
        NFAState._counter += 1

        self.transitions: Dict[Union[str, frozenset], Set[NFAState]] = {}

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
        self.token_type: Optional[str] = None
        self.priority: int = float('inf')

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

    def _tokenize(self) -> List[str]:
        tokens = []
        i = 0
        n = len(self.regex)

        while i < n:
            if self.regex[i] == "{" and i + 3 < n and self.regex[i:i+2] == "{{":
                end = self.regex.find("}}", i)
                if end != -1:
                    charset_name = self.regex[i+2:end]
                    tokens.append(f"{{{{{charset_name}}}}}")
                    i = end + 2
                    continue

            if self.regex[i] == "\\" and i + 1 < n:
                tokens.append(self.regex[i:i+2])
                i += 2
            else:
                tokens.append(self.regex[i])
                i += 1

        return tokens

    def add_concat(self) -> List[str]:
        tokens = self._tokenize()
        result = []

        for i in range(len(tokens)):
            token = tokens[i]
            result.append(token)

            if i == len(tokens) - 1:
                continue

            next_token = tokens[i+1]

            left_can_concat = (
                (len(token) == 1 and token not in "()|*+?.")
                or len(token) == 2
                or token.startswith("{{") and token.endswith("}}")
                or token == ")"
                or token in "*+?"
            )

            right_can_concat = (
                (len(next_token) == 1 and next_token not in ")|*+?.")
                or len(next_token) == 2
                or next_token.startswith("{{") and next_token.endswith("}}")
                or next_token == "("
            )

            if left_can_concat and right_can_concat:
                result.append(self.CONCAT)

        return result

    def to_postfix(self) -> List[str]:
        tokens = self.add_concat()
        output = []
        stack = []

        for token in tokens:
            if token == "(":
                stack.append(token)
            elif token == ")":
                while stack and stack[-1] != "(":
                    output.append(stack.pop())
                if not stack:
                    raise ValueError("正则表达式括号不匹配")
                stack.pop()
            elif token in self.PRIORITY:
                while (
                    stack
                    and stack[-1] != "("
                    and self.PRIORITY[stack[-1]] >= self.PRIORITY[token]
                ):
                    output.append(stack.pop())
                stack.append(token)
            else:
                output.append(token)

        while stack:
            if stack[-1] == "(":
                raise ValueError("正则表达式括号不匹配")
            output.append(stack.pop())

        return output

    def to_nfa(self) -> NFA:
        postfix = self.to_postfix()
        stack: List[NFA] = []

        for token in postfix:
            if token == self.CONCAT:
                if len(stack) < 2:
                    raise ValueError(f"无效的连接操作，栈大小: {len(stack)}")
                n2 = stack.pop()
                n1 = stack.pop()
                n1.accept.add_epsilon(n2.start)
                stack.append(NFA(n1.start, n2.accept))
            elif token == "|":
                if len(stack) < 2:
                    raise ValueError(f"无效的或操作，栈大小: {len(stack)}")
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
                if len(stack) < 1:
                    raise ValueError(f"无效的闭包操作，栈大小: {len(stack)}")
                n = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n.start)
                s.add_epsilon(e)
                n.accept.add_epsilon(n.start)
                n.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            elif token == "+":
                if len(stack) < 1:
                    raise ValueError(f"无效的正闭包操作，栈大小: {len(stack)}")
                n = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n.start)
                n.accept.add_epsilon(n.start)
                n.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            elif token == "?":
                if len(stack) < 1:
                    raise ValueError(f"无效的可选操作，栈大小: {len(stack)}")
                n = stack.pop()
                s = NFAState()
                e = NFAState()
                s.add_epsilon(n.start)
                s.add_epsilon(e)
                n.accept.add_epsilon(e)
                stack.append(NFA(s, e))
            else:
                s1 = NFAState()
                s2 = NFAState()

                if token.startswith("{{") and token.endswith("}}"):
                    charset_name = token[2:-2]
                    if charset_name in self.charsets:
                        if charset_name == "cjk":
                            chars = ("CJK",)
                        else:
                            chars = frozenset(self.charsets[charset_name])
                        s1.add_transition(chars, s2)
                    else:
                        raise ValueError(f"未定义的字符集: {charset_name}")
                elif len(token) == 2 and token[0] == "\\":
                    actual_char = token[1]
                    s1.add_transition(actual_char, s2)
                else:
                    s1.add_transition(token, s2)

                stack.append(NFA(s1, s2))

        if len(stack) != 1:
            raise ValueError(f"正则表达式解析失败，栈大小: {len(stack)}")

        return stack.pop()

    @staticmethod
    def nfa_to_dfa(nfa: NFA) -> DFA:
        def epsilon_closure(states: Set[NFAState]) -> Set[NFAState]:
            stack = list(states)
            closure = set(states)

            while stack:
                s = stack.pop()
                for nxt in s.epsilon:
                    if nxt not in closure:
                        closure.add(nxt)
                        stack.append(nxt)
            return closure

        start_closure = epsilon_closure({nfa.start})
        start_state = DFAState(start_closure)

        dfa = DFA()
        dfa.start = start_state
        dfa.states = [start_state]

        state_map: Dict[frozenset[NFAState], DFAState] = {}
        state_map[start_state.nfa_states] = start_state

        unmarked = [start_state]

        while unmarked:
            current_dfa_state = unmarked.pop()

            char_transitions: Dict[str, Set[NFAState]] = {}

            for nfa_state in current_dfa_state.nfa_states:
                for sym, targets in nfa_state.transitions.items():
                    if isinstance(sym, frozenset):
                        for char in sym:
                            if char not in char_transitions:
                                char_transitions[char] = set()
                            char_transitions[char].update(targets)
                    elif sym == ("CJK",):
                        for code in range(0x4E00, 0x9FFF + 1):
                            char = chr(code)

                            if char not in char_transitions:
                                char_transitions[char] = set()

                            char_transitions[char].update(targets)
                    else:
                        if sym not in char_transitions:
                            char_transitions[sym] = set()
                        char_transitions[sym].update(targets)

            for char, nfa_targets in char_transitions.items():
                target_closure = epsilon_closure(nfa_targets)
                target_key = frozenset(target_closure)

                if target_key not in state_map:
                    new_dfa_state = DFAState(target_closure)
                    state_map[target_key] = new_dfa_state
                    dfa.states.append(new_dfa_state)
                    unmarked.append(new_dfa_state)
                else:
                    new_dfa_state = state_map[target_key]

                current_dfa_state.transitions[char] = new_dfa_state

        return dfa
