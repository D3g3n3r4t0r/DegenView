from dataclasses import dataclass, field


class Expr:
    pass


@dataclass
class NumberLit(Expr):
    value: float


@dataclass
class StringLit(Expr):
    value: str


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class NaLit(Expr):
    pass


@dataclass
class Identifier(Expr):
    name: str  # dotted, e.g. "ta.ema", "close", "strategy.long"


@dataclass
class HistoryRef(Expr):
    base: Expr
    offset: Expr


@dataclass
class Call(Expr):
    func_name: str
    args: list[Expr]
    kwargs: dict[str, Expr]
    line_no: int = 0


@dataclass
class Unary(Expr):
    op: str
    operand: Expr


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class Ternary(Expr):
    cond: Expr
    if_true: Expr
    if_false: Expr


class Stmt:
    pass


@dataclass
class Assign(Stmt):
    name: str
    expr: Expr
    is_var: bool
    line_no: int


@dataclass
class Reassign(Stmt):
    name: str
    expr: Expr
    line_no: int


@dataclass
class TupleAssign(Stmt):
    names: list[str]
    expr: Expr
    line_no: int


@dataclass
class ExprStmt(Stmt):
    expr: Expr
    line_no: int


@dataclass
class If(Stmt):
    cond: Expr
    body: list = field(default_factory=list)
    elifs: list = field(default_factory=list)  # list[(Expr, list[Stmt])]
    else_body: list | None = None
    line_no: int = 0
