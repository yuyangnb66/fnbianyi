"""词法分析器 — 从 grammar/tokens.json 加载规则，将源码切分为 Token 流。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r}, L{self.line})"


class LexerError(Exception):
    pass


class Lexer:
    def __init__(self, source: str, rules_path: Optional[Path] = None):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        rules_path = rules_path or Path(__file__).parent.parent / "grammar" / "tokens.json"
        self.rules = self._load_rules(rules_path)

    @staticmethod
    def _load_rules(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

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

    def _match_regex(self, pattern: str) -> Optional[str]:
        m = re.match(pattern, self.source[self.pos :], re.DOTALL)
        if m:
            text = m.group(0)
            self._advance(len(text))
            return text
        return None

    def next_token(self) -> Optional[Token]:
        while self.pos < len(self.source):
            start_line, start_col = self.line, self.col

            # 1. 跳过空白与注释
            skipped = False
            for spec in self.rules.get("patterns", []):
                if not spec.get("skip"):
                    continue
                text = self._match_regex(spec["regex"])
                if text is not None:
                    skipped = True
                    break
            if skipped:
                continue

            # 2. 运算符（长匹配优先）
            for op, kind in sorted(
                self.rules.get("operators", {}).items(), key=lambda x: -len(x[0])
            ):
                if self.source.startswith(op, self.pos):
                    self._advance(len(op))
                    return Token(kind, op, start_line, start_col)

            # 3. 关键字（优先于标识符）
            for kw, kind in self.rules.get("keywords", {}).items():
                if re.match(rf"{re.escape(kw)}\b", self.source[self.pos :]):
                    self._advance(len(kw))
                    return Token(kind, kw, start_line, start_col)

            # 4. 字面量与其他模式
            for spec in self.rules.get("patterns", []):
                if spec.get("skip"):
                    continue
                text = self._match_regex(spec["regex"])
                if text is not None:
                    return Token(spec["name"], text, start_line, start_col)

            ch = self._current()
            if not ch:
                break
            raise LexerError(f"无法识别的字符 {ch!r}，位置 L{start_line}:C{start_col}")
        return None

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while True:
            tok = self.next_token()
            if tok is None:
                break
            tokens.append(tok)
        tokens.append(Token("EOF", "", self.line, self.col))
        return tokens

    def __iter__(self) -> Iterator[Token]:
        return iter(self.tokenize())
