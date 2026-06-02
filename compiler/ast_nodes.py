"""MiniLang 抽象语法树节点定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class Program:
    statements: List[Stmt]


class Stmt:
    pass


@dataclass
class DeclStmt(Stmt):
    type_name: str
    name: str
    line: int = 0


@dataclass
class AssignStmt(Stmt):
    name: str
    value: Expr
    line: int = 0


@dataclass
class IfStmt(Stmt):
    condition: Expr
    then_block: Block
    else_block: Optional[Block] = None
    line: int = 0


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: Block
    line: int = 0


@dataclass
class PrintStmt(Stmt):
    value: Expr
    line: int = 0


@dataclass
class Block(Stmt):
    statements: List[Stmt] = field(default_factory=list)


class Expr:
    type_name: str = "unknown"


@dataclass
class IntLit(Expr):
    value: int

    def __post_init__(self):
        self.type_name = "int"


@dataclass
class FloatLit(Expr):
    value: float

    def __post_init__(self):
        self.type_name = "float"


@dataclass
class VarExpr(Expr):
    name: str
    type_name: str = "unknown"


@dataclass
class UnaryExpr(Expr):
    op: str
    operand: Expr
    type_name: str = "unknown"


@dataclass
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr
    type_name: str = "unknown"


@dataclass
class RelExpr(Expr):
    op: str
    left: Expr
    right: Expr
    type_name: str = "int"
