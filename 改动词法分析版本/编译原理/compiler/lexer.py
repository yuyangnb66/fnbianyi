from __future__ import annotations

import json
import re
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
        return f"Token({self.kind:<12} {self.value!r:<10} L{self.line}:C{self.col})"

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

        # 存储每个pattern对应的DFA及其元数据(优先级越高数字越小)
        self.pattern_dfas: List[Tuple[DFA, str, bool, int]] = []

        # 为每个pattern生成DFA
        for priority, spec in enumerate(self.rules["patterns"]):
            name = spec["name"]
            regex = spec["regex"]
            skip = spec.get("skip", False)

            # 展开字符集引用 - 关键改进：不再展开为|链，而是保留字符集标记
            processed_regex = self._process_charsets(regex)

            self._trace(f"[PROCESSED] {name}: {regex} -> {processed_regex}")

            # 生成NFA
            parser = RegexParser(processed_regex, self.charsets)
            nfa = parser.to_nfa()

            # 转换为DFA
            dfa = RegexParser.nfa_to_dfa(nfa)

            # 标记DFA的接受状态对应的token类型和优先级
            for state in dfa.states:
                if nfa.accept in state.nfa_states:
                    state.is_accept = True
                    state.token_type = name
                    state.priority = priority

            self.pattern_dfas.append((dfa, name, skip, priority)) 
            # AAAAAAA
            self._trace(f"[COMPILED] Pattern '{name}' -> DFA with {len(dfa.states)} states")

        # 预排序操作符和关键字（最长匹配优先）
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
        
    # AAAAAAAA
    def _trace(self, msg: str) -> None:
        if self.trace:
            print(msg)
        
    def _process_charsets(self, pattern: str) -> str:
        # 先处理最长的字符集名称，避免短名称覆盖长名称
        for name in sorted(self.charsets.keys(), key=len, reverse=True):
            # 使用特殊标记{{name}}表示字符集
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
        """使用给定的DFA从当前位置进行匹配，返回最长匹配的字符串"""
        current_state = dfa.start
        last_accept_pos = -1
        current_pos = self.pos

        while current_pos < len(self.source):
            char = self.source[current_pos]
            
            # 检查当前状态是否有该字符的转移
            if char in current_state.transitions:
                current_state = current_state.transitions[char]
                current_pos += 1
                
                # 如果当前状态是接受状态，记录位置
                if current_state.is_accept:
                    last_accept_pos = current_pos
            else:
                break

        # 如果有接受状态，返回匹配的字符串
        if last_accept_pos != -1:
            return self.source[self.pos:last_accept_pos]
        return None

    def next_token(self) -> Optional[Token]:
        while self.pos < len(self.source):
            start_line, start_col = self.line, self.col

            # AAAAAAAAAA
            self._trace(f"\n[POS] L{start_line}:C{start_col}, char={self._current()!r}")

            # 匹配操作符（最长匹配优先）
            for op, kind in self.operators:
                if self.source.startswith(op, self.pos):
                    self._trace(f"[OP MATCH] {op} -> {kind}")
                    self._advance(len(op))
                    return Token(kind, op, start_line, start_col)

            # 匹配关键字（最长匹配优先）
            for kw, kind in self.keywords:
                if not self.source.startswith(kw, self.pos):
                    continue

                end_pos = self.pos + len(kw)
                # 确保关键字后面不是字母、数字或下划线
                if end_pos < len(self.source):
                    ch = self.source[end_pos]
                    if ch.isalnum() or ch == "_":
                        continue

                # AAAAAAAA
                self._trace(f"[KW MATCH] {kw} -> {kind}")
                self._advance(len(kw))
                return Token(kind, kw, start_line, start_col)


            # 使用DFA匹配所有patterns
            best_match: Optional[str] = None
            best_pattern: Optional[Tuple[DFA, str, bool, int]] = None
            best_length = 0
            best_priority = float('inf')

            for pattern_info in self.pattern_dfas:
                dfa, name, skip, priority = pattern_info
                match = self._match_dfa(dfa)
                
                if match is not None:
                    match_len = len(match)
                    # 最长匹配优先，长度相同则优先级高的优先
                    if (match_len > best_length) or (match_len == best_length and priority < best_priority):
                        best_match = match
                        best_pattern = pattern_info
                        best_length = match_len
                        best_priority = priority

            if best_match is not None and best_pattern is not None:
                dfa, name, skip, priority = best_pattern
                # AAAAAAAAAA
                self._trace(f"[DFA MATCH] {name} -> {best_match!r} (length={best_length}, priority={priority})")
                
                # 跳过空白符等不需要的token
                if skip:
                    self._advance(len(best_match))
                    continue

                # 验证数字格式
                if name in ("INT_LIT", "FLOAT_LIT"):
                    self._validate_number(best_match, start_line, start_col)

                # 验证标识符不能以数字开头
                if name == "IDENT" and best_match[0].isdigit():
                    # AAAAAAA
                    self._trace("[ERROR] IDENT starts with digit")
                    self._add_error(
                        f"标识符 '{best_match}' 不能以数字开头",
                        start_line,
                        start_col,
                        "E006"
                    )
                    self._advance(len(best_match))
                    return Token("ERROR", best_match, start_line, start_col)

                self._advance(len(best_match))
                return Token(name, best_match, start_line, start_col)

            # 无法识别的字符
            ch = self._current()
            if not ch:
                break

            # AAAAAAA
            self._trace(f"[UNKNOWN] {ch!r}")

            self._add_error(
                f"无法识别的字符 {ch!r}",
                start_line,
                start_col,
                "E001"
            )
            self._advance(1)
            return Token("ERROR", ch, start_line, start_col)

        # AAAAAA
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
        # print(tokens)
        return LexResult(tokens=tokens, errors=list(self.errors))

    def __iter__(self) -> Iterator[Token]:
        return iter(self.tokenize().tokens)


class NFAState:
    _counter = 0

    def __init__(self):
        self.id = NFAState._counter
        NFAState._counter += 1

        # 普通边：可以是单个字符或字符集合
        self.transitions: Dict[Union[str, frozenset], Set[NFAState]] = {}

        # ε边：set of states
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
    # 使用"."作为连接符，最稳定可靠
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
            "\\}": "}"
        }

    def _tokenize(self) -> List[str]:
        """将正则表达式拆分为token列表，正确处理转义字符和字符集标记"""
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

    def add_concat(self) -> List[str]:
        """在token列表中插入显式的连接符"""
        tokens = self._tokenize()
        result = []
        
        for i in range(len(tokens)):
            token = tokens[i]
            result.append(token)
            
            if i == len(tokens) - 1:
                continue
                
            next_token = tokens[i+1]
            
            # 判断是否需要插入连接符
            # 左边可以是：普通字符、转义字符、字符集、右括号、闭包运算符
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
            
            # 右边可以是：普通字符、转义字符、字符集、左括号
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

    def to_postfix(self) -> List[str]:
        """将正则表达式转换为后缀表达式（支持字符集转移）"""
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
    
    def to_nfa(self) -> NFA:
        """根据后缀表达式构建NFA - 支持字符集转移"""
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
    
    @staticmethod
    def nfa_to_dfa(nfa: NFA) -> DFA:
        """将NFA转换为DFA（子集构造法）- 支持字符集转移"""
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
                    elif sym == ("CJK",):
                        for code in range(0x4E00, 0x9FFF + 1):
                            char = chr(code)

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

"""
if __name__ == "__main__":
    print("========== MiniLang Lexer (NFA/DFA Based) ==========")
    print("输入源码（输入 EOF 单独一行结束）\n")

    lines = []
    while True:
        try:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
        except EOFError:
            break

    source = "\n".join(lines)

    print("\n========== 源码 ==========")
    print(source)

    print("\n========== 开始词法分析 ==========\n")

    try:
        lexer = Lexer(source, trace=True)
        result = lexer.tokenize()

        print("\n========== 最终 Token 流 ==========")
        for tok in result.tokens:
            print(tok)

        print("\n========== Token 总数 ==========")
        print(len(result.tokens))

        if result.errors:
            print("\n========== 错误 ==========")
            for e in result.errors:
                print(e)
        else:
            print("\n无词法错误")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n词法分析失败: {e}")

"""