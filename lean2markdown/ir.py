"""Intermediate Representation (IR) for Lean2Markdown.

Separates Lean 4 syntactic/elaborated declarations from mathematical expression ASTs
so multiple frontends (Lean 4 elaborator or native Python parser) can feed multiple
output generators (Markdown, HTML, LaTeX).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Diagnostics & Warnings
# ---------------------------------------------------------------------------

@dataclass
class ConversionWarning:
    """Non-fatal diagnostic reported during parsing, analysis, or rendering."""

    code: str
    message: str
    line: int = 0
    column: int = 0
    source_snippet: str = ""


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@dataclass
class Comment:
    """Represents a Lean 4 comment (`--`, `/- -/`, `/-- -/`, `/-! -/`)."""

    kind: str  # "line", "block", "doc", "module_doc"
    text: str
    raw: str
    start_line: int
    end_line: int
    indent: int = 0


# ---------------------------------------------------------------------------
# Mathematical Expression IR (AST)
# ---------------------------------------------------------------------------

@dataclass
class MathExpr:
    """Base class for mathematical expression IR nodes."""


@dataclass
class SymbolExpr(MathExpr):
    name: str


@dataclass
class NumberExpr(MathExpr):
    value: str


@dataclass
class StringLitExpr(MathExpr):
    value: str


@dataclass
class UnaryOpExpr(MathExpr):
    op: str
    operand: MathExpr
    precedence: int = 75


@dataclass
class BinaryOpExpr(MathExpr):
    op: str
    left: MathExpr
    right: MathExpr
    precedence: int = 50


@dataclass
class AppExpr(MathExpr):
    func: MathExpr
    args: List[MathExpr]


@dataclass
class QuantifierExpr(MathExpr):
    kind: str  # "forall", "exists", "exists_unique"
    binders: List[Tuple[List[str], Optional[MathExpr]]]  # [(["x", "y"], TypeExpr)]
    body: MathExpr


@dataclass
class LambdaExpr(MathExpr):
    params: List[Tuple[List[str], Optional[MathExpr]]]
    body: MathExpr


@dataclass
class BigOpExpr(MathExpr):
    kind: str  # "sum", "prod", "int", "lim", "bigcup", "bigcap"
    binder: str
    domain: Optional[MathExpr]
    body: MathExpr


@dataclass
class SetBuilderExpr(MathExpr):
    var: str
    domain: Optional[MathExpr]
    predicate: MathExpr


@dataclass
class TupleExpr(MathExpr):
    elements: List[MathExpr]
    angle_brackets: bool = False  # ⟨a, b⟩ vs (a, b)


@dataclass
class ListLitExpr(MathExpr):
    elements: List[MathExpr]


@dataclass
class MatrixExpr(MathExpr):
    rows: List[List[MathExpr]]


@dataclass
class LetMathExpr(MathExpr):
    name: str
    type_annot: Optional[MathExpr]
    value: MathExpr
    body: MathExpr


@dataclass
class IfMathExpr(MathExpr):
    condition: MathExpr
    then_branch: MathExpr
    else_branch: MathExpr


@dataclass
class MatchMathExpr(MathExpr):
    scrutinee: MathExpr
    arms: List[Tuple[str, MathExpr]]


@dataclass
class TypeAnnotExpr(MathExpr):
    expr: MathExpr
    type_expr: MathExpr


@dataclass
class RawFallbackExpr(MathExpr):
    """Fallback node when an expression cannot be safely converted to LaTeX."""

    raw_lean: str
    reason: str = ""


# ---------------------------------------------------------------------------
# Proof & Declaration IR
# ---------------------------------------------------------------------------

@dataclass
class Binder:
    """Parameter, implicit argument, or typeclass constraint."""

    kind: str  # "explicit", "implicit", "strict_implicit", "instance"
    names: List[str]
    type_raw: str
    type_ir: Optional[MathExpr] = None
    raw: str = ""


@dataclass
class StructField:
    name: str
    type_raw: str
    type_ir: Optional[MathExpr] = None
    default_value: Optional[str] = None
    doc_comment: Optional[Comment] = None
    inline_comment: Optional[str] = None
    line: int = 0


@dataclass
class InductiveConstructor:
    name: str
    signature_raw: str
    signature_ir: Optional[MathExpr] = None
    doc_comment: Optional[Comment] = None
    inline_comment: Optional[str] = None
    line: int = 0


@dataclass
class CalcStep:
    lhs_raw: str
    relation: str
    rhs_raw: str
    justification: str
    line: int
    lhs_ir: Optional[MathExpr] = None
    rhs_ir: Optional[MathExpr] = None
    comments: List[Comment] = field(default_factory=list)


@dataclass
class ProofStep:
    step_id: str
    kind: str  # "tactic", "have", "let", "obtain", "show", "suffices", "calc", "branch", "comment", "term"
    tactic_name: str
    args: str
    raw_code: str
    line: int
    end_line: int
    indent: int
    explanation: str = ""
    math_latex: str = ""
    reliable: bool = True  # False if tactic cannot be reliably explained
    leading_comments: List[Comment] = field(default_factory=list)
    inline_comment: Optional[str] = None
    calc_steps: List[CalcStep] = field(default_factory=list)
    substeps: List["ProofStep"] = field(default_factory=list)


@dataclass
class Declaration:
    kind: str  # theorem, lemma, def, abbrev, opaque, axiom, example, structure, class, inductive, instance, notation, infix, prefix, postfix
    name: str
    qualified_name: str = ""
    modifiers: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    universe_params: List[str] = field(default_factory=list)
    binders: List[Binder] = field(default_factory=list)
    return_type_raw: str = ""
    return_type_ir: Optional[MathExpr] = None
    body_raw: str = ""
    body_ir: Optional[MathExpr] = None
    is_proposition: bool = False
    is_tactic_proof: bool = False
    namespace: str = ""
    section: str = ""
    start_line: int = 0
    end_line: int = 0
    doc_comment: Optional[Comment] = None
    leading_comments: List[Comment] = field(default_factory=list)
    fields: List[StructField] = field(default_factory=list)
    constructors: List[InductiveConstructor] = field(default_factory=list)
    proof_steps: List[ProofStep] = field(default_factory=list)
    nested_declarations: List["Declaration"] = field(default_factory=list)
    raw_source: str = ""
    elaborated: bool = False  # True if enriched by Lean 4 elaborator


@dataclass
class TopLevelDirective:
    kind: str  # "import", "open", "variable", "universe", "set_option", "namespace", "section", "end", "command", "comment", "module_doc"
    text: str
    line: int
    end_line: int
    namespace: str = ""
    comment: Optional[Comment] = None


@dataclass
class DocumentIR:
    """Complete intermediate representation of a parsed Lean 4 file."""

    source_name: str
    total_lines: int
    backend: str = "parser"  # "lean4" or "parser"
    imports: List[Tuple[int, str]] = field(default_factory=list)
    opens: List[Tuple[int, str]] = field(default_factory=list)
    variables: List[Tuple[int, str]] = field(default_factory=list)
    universes: List[Tuple[int, str]] = field(default_factory=list)
    module_docs: List[Comment] = field(default_factory=list)
    declarations: List[Declaration] = field(default_factory=list)
    directives: List[TopLevelDirective] = field(default_factory=list)
    warnings: List[ConversionWarning] = field(default_factory=list)
    raw_source: str = ""
