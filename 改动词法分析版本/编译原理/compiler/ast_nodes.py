# MiniLang 抽象语法树节点定义

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Program:
    functions: List["FuncDecl"] = field(default_factory=list)
    statements: List["Stmt"] = field(default_factory=list)


class Stmt:
    pass


@dataclass
class FuncDecl(Stmt):
    return_type: str
    name: str
    params: List[Tuple[str, str]]
    body: "Block"
    line: int = 0


@dataclass
class DeclStmt(Stmt):
    type_name: str
    name: str
    array_size: Optional[int] = None
    line: int = 0


@dataclass
class AssignStmt(Stmt):
    name: str
    value: "Expr"
    index: Optional["Expr"] = None
    line: int = 0


@dataclass
class IfStmt(Stmt):
    condition: "Expr"
    then_block: "Block"
    else_block: Optional["Block"] = None
    line: int = 0


@dataclass
class WhileStmt(Stmt):
    condition: "Expr"
    body: "Block"
    line: int = 0


@dataclass
class ForStmt(Stmt):
    init: Optional[AssignStmt]
    condition: "Expr"
    update: Optional[AssignStmt]
    body: "Block"
    line: int = 0


@dataclass
class ReturnStmt(Stmt):
    value: Optional["Expr"]
    line: int = 0


@dataclass
class BreakStmt(Stmt):
    line: int = 0


@dataclass
class ContinueStmt(Stmt):
    line: int = 0


@dataclass
class InputStmt(Stmt):
    names: List[str]
    prompt: Optional[Expr] = None
    type_names: List[str] = field(default_factory=list)
    line: int = 0

    @property
    def name(self) -> str:
        return self.names[0] if self.names else ""


@dataclass
class WriteStmt(Stmt):
    path: Expr
    value: Expr
    line: int = 0


@dataclass
class PrintStmt(Stmt):
    values: List["Expr"]
    newline: bool = True
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
class StringLit(Expr):
    value: str

    def __post_init__(self):
        self.type_name = "string"


@dataclass
class VarExpr(Expr):
    name: str
    type_name: str = "unknown"


@dataclass
class ArrayAccessExpr(Expr):
    name: str
    index: Expr
    type_name: str = "unknown"


@dataclass
class CallExpr(Expr):
    name: str
    args: List[Expr] = field(default_factory=list)
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
