"""Recursive-descent + Pratt parser for Lean 4 mathematical expressions into MathExpr IR.

Preserves operator precedence, associativity, binder scopes, quantifiers, lambdas,
big operators (∑, ∏, ∫), set-builder notation, matrices, dependent types, and falls
back safely to RawFallbackExpr on unsupported syntax.
"""

from typing import List, Optional, Tuple

from .ir import (
    AppExpr,
    BigOpExpr,
    BinaryOpExpr,
    ConversionWarning,
    IfMathExpr,
    LambdaExpr,
    LetMathExpr,
    ListLitExpr,
    MatchMathExpr,
    MathExpr,
    MatrixExpr,
    NumberExpr,
    QuantifierExpr,
    RawFallbackExpr,
    SetBuilderExpr,
    StringLitExpr,
    SymbolExpr,
    TupleExpr,
    TypeAnnotExpr,
    UnaryOpExpr,
)
from .lexer import Token, tokenize_lean

# Operator precedence table (higher binds tighter)
BINARY_PRECEDENCE = {
    "↔": (20, "right"),
    "<->": (20, "right"),
    "→": (25, "right"),
    "->": (25, "right"),
    "∨": (30, "right"),
    "\\/": (30, "right"),
    "||": (30, "right"),
    "∧": (35, "right"),
    "/\\": (35, "right"),
    "&&": (35, "right"),
    "=": (50, "none"),
    "≠": (50, "none"),
    "!=": (50, "none"),
    "<": (50, "none"),
    ">": (50, "none"),
    "≤": (50, "none"),
    "<=": (50, "none"),
    "≥": (50, "none"),
    ">=": (50, "none"),
    "∈": (50, "none"),
    "∉": (50, "none"),
    "⊆": (50, "none"),
    "⊂": (50, "none"),
    "⊇": (50, "none"),
    "⊃": (50, "none"),
    "≡": (50, "none"),
    "≈": (50, "none"),
    "≃": (50, "none"),
    "≅": (50, "none"),
    "∣": (50, "none"),
    "∤": (50, "none"),
    "∼": (50, "none"),
    "<|": (10, "right"),
    "|>": (10, "left"),
    "∪": (65, "left"),
    "∩": (70, "left"),
    "∖": (65, "left"),
    "\\": (65, "left"),
    "++": (65, "right"),
    "::": (67, "right"),
    "+": (65, "left"),
    "+ᵥ": (65, "left"),
    "-": (65, "left"),
    "±": (65, "left"),
    "⊕": (65, "left"),
    "*": (70, "left"),
    "·": (70, "left"),
    "•": (73, "right"),
    "×": (70, "right"),
    "⊗": (70, "left"),
    "/": (70, "left"),
    "%": (70, "left"),
    "''": (80, "right"),
    "^": (80, "right"),
    "∘": (90, "right"),
}

PREFIX_OPS = {
    "¬": 40,
    "!": 40,
    "-": 75,
    "√": 85,
}

QUANTIFIER_TOKENS = {"∀", "forall", "∃", "exists", "∃!"}
BIGOP_TOKENS = {"∑": "sum", "∏": "prod", "∫": "int", "⋃": "bigcup", "⋂": "bigcap"}

STOP_TOKENS = {
    "EOF", "RPAREN", "RBRACE", "RBRACK", "SRBRACE", "RANGLE",
    "COMMA", "SEMI", "PIPE",
}
STOP_KEYWORDS = {"then", "else", "in", "with", "where", "by", "do"}


class _ExprParser:
    def __init__(self, tokens: List[Token], raw_source: str, base_line: int = 0):
        # Filter out comments and newlines inside expressions
        self.tokens = [t for t in tokens if t.kind not in ("COMMENT", "NEWLINE")]
        self.pos = 0
        self.raw_source = raw_source
        self.base_line = base_line
        self.warnings: List[ConversionWarning] = []

    def peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]

    def advance(self) -> Token:
        tok = self.peek()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def match_val(self, *vals: str) -> bool:
        if self.peek().value in vals:
            self.advance()
            return True
        return False

    def match_kind(self, *kinds: str) -> bool:
        if self.peek().kind in kinds:
            self.advance()
            return True
        return False

    def parse_expr(self, min_prec: int = 0) -> MathExpr:
        left = self.parse_prefix()

        while True:
            tok = self.peek()
            if tok.kind == "EOF":
                break

            # Type annotation `e : T` at low precedence (only if min_prec == 0)
            if tok.kind == "COLON" and min_prec <= 10:
                # Avoid swallowing `:` in binder lists handled externally
                break

            # Binary operator?
            if tok.value in BINARY_PRECEDENCE:
                prec, assoc = BINARY_PRECEDENCE[tok.value]
                if prec < min_prec:
                    break
                op_tok = self.advance()
                next_min = prec + 1 if assoc == "left" else prec
                right = self.parse_expr(next_min)
                left = BinaryOpExpr(op=op_tok.value, left=left, right=right, precedence=prec)
                continue

            break

        return left

    def parse_prefix(self) -> MathExpr:
        tok = self.peek()

        # Quantifiers: ∀ x : T, P x  |  ∃ (x y : ℕ), x + y = 0
        if tok.value in QUANTIFIER_TOKENS:
            return self.parse_quantifier()

        # Lambda: fun x y => body  |  λ x : T, body
        if tok.value in ("fun", "λ"):
            return self.parse_lambda()

        # Big operators: ∑ i ∈ s, f i  |  ∏ i ∈ s, f i  |  ∫ x in a..b, f x
        if tok.value in BIGOP_TOKENS:
            return self.parse_bigop()

        # let x := v; body  or  let x : T := v in body
        if tok.value == "let":
            return self.parse_let()

        # if c then t else e
        if tok.value == "if":
            return self.parse_if()

        # match x with | p => e
        if tok.value == "match":
            return self.parse_match()

        # Prefix unary operators: ¬, -, √
        if tok.value in PREFIX_OPS:
            op = self.advance().value
            prec = PREFIX_OPS[op]
            operand = self.parse_expr(prec)
            return UnaryOpExpr(op=op, operand=operand, precedence=prec)

        return self.parse_application()

    def _can_start_atom(self, tok: Token) -> bool:
        if tok.kind in ("IDENT", "NUMBER", "STRING", "LPAREN", "LBRACK", "LBRACE", "LANGLE"):
            if tok.kind == "IDENT" and tok.value in STOP_KEYWORDS:
                return False
            if tok.value in QUANTIFIER_TOKENS or tok.value in BIGOP_TOKENS:
                return False
            if tok.value in ("fun", "λ", "let", "if", "match"):
                return False
            return True
        if tok.value == "![":
            return True
        return False

    def parse_application(self) -> MathExpr:
        func = self.parse_postfix()

        # Check for dependent function type: `(x : α) → β x`
        if isinstance(func, TypeAnnotExpr) and self.peek().value in ("→", "->"):
            # Keep it as BinaryOpExpr("→", TypeAnnotExpr, ...)
            return func

        args: List[MathExpr] = []
        while self._can_start_atom(self.peek()):
            # Stop if this is a binary operator or keyword
            if self.peek().value in BINARY_PRECEDENCE:
                break
            args.append(self.parse_postfix())

        if not args:
            return func
        return AppExpr(func=func, args=args)

    def parse_postfix(self) -> MathExpr:
        """Parses an atom followed by postfix projections (`.1`, `.fst`) or inverse/superscripts (`⁻¹`, `²`)."""
        expr = self.parse_atom()
        while True:
            if self.peek().value == "." and self.peek(1).kind in ("IDENT", "NUMBER"):
                self.advance()
                field_tok = self.advance()
                expr = BinaryOpExpr(op=".", left=expr, right=SymbolExpr(field_tok.value), precedence=95)
            elif self.peek().value == "⁻¹":
                self.advance()
                expr = BinaryOpExpr(op="^", left=expr, right=NumberExpr("-1"), precedence=85)
            elif self.peek().value in ("²", "³", "ⁿ"):
                sup = {"²": "2", "³": "3", "ⁿ": "n"}[self.advance().value]
                expr = BinaryOpExpr(op="^", left=expr, right=SymbolExpr(sup) if sup == "n" else NumberExpr(sup), precedence=85)
            else:
                break
        return expr

    def parse_atom(self) -> MathExpr:
        tok = self.peek()

        if tok.kind == "NUMBER":
            self.advance()
            return NumberExpr(tok.value)

        if tok.kind == "STRING":
            self.advance()
            return StringLitExpr(tok.value)

        if tok.kind == "IDENT":
            self.advance()
            return SymbolExpr(tok.value)

        # Matrix literal: ![![a, b], ![c, d]] or ![[a, b], [c, d]]
        if tok.value == "![":
            return self.parse_matrix_or_vec()

        # Parenthesized expression, tuple, or typed binder `(x : T)`
        if tok.kind == "LPAREN":
            self.advance()
            if self.peek().kind == "RPAREN":
                self.advance()
                return TupleExpr([])
            first = self.parse_expr(0)
            # Typed binder `(x : T)` or `(x y : T)`
            if self.peek().kind == "COLON":
                self.advance()
                ty = self.parse_expr(0)
                self.match_kind("RPAREN")
                return TypeAnnotExpr(expr=first, type_expr=ty)
            # Tuple `(a, b, c)`
            if self.peek().kind == "COMMA":
                elems = [first]
                while self.match_kind("COMMA"):
                    if self.peek().kind == "RPAREN":
                        break
                    elems.append(self.parse_expr(0))
                self.match_kind("RPAREN")
                return TupleExpr(elems, angle_brackets=False)
            self.match_kind("RPAREN")
            return first

        # Angle bracket tuple `⟨a, b⟩`
        if tok.kind == "LANGLE":
            self.advance()
            elems: List[MathExpr] = []
            if self.peek().kind != "RANGLE":
                elems.append(self.parse_expr(0))
                while self.match_kind("COMMA"):
                    if self.peek().kind == "RANGLE":
                        break
                    elems.append(self.parse_expr(0))
            self.match_kind("RANGLE")
            return TupleExpr(elems, angle_brackets=True)

        # List literal `[a, b, c]`
        if tok.kind == "LBRACK":
            self.advance()
            elems = []
            if self.peek().kind != "RBRACK":
                elems.append(self.parse_expr(0))
                while self.match_kind("COMMA"):
                    if self.peek().kind == "RBRACK":
                        break
                    elems.append(self.parse_expr(0))
            self.match_kind("RBRACK")
            return ListLitExpr(elems)

        # Set literal or set-builder `{x ∈ S | P x}` or `{x : T | P x}` or `{a, b}`
        if tok.kind == "LBRACE":
            return self.parse_set_expr()

        # Fallback for unexpected token
        bad = self.advance()
        return SymbolExpr(bad.value)

    def parse_set_expr(self) -> MathExpr:
        self.advance()  # consume `{`
        if self.peek().kind == "RBRACE":
            self.advance()
            return SymbolExpr("∅")

        # Save state to distinguish set-builder `{x ∈ S | P}` / `{x : T | P}` / `{x | P}` from `{a, b}`
        saved = self.pos
        if self.peek().kind == "IDENT":
            var_name = self.advance().value
            domain: Optional[MathExpr] = None
            if self.peek().value == "∈":
                self.advance()
                domain = self.parse_expr(0)
            elif self.peek().kind == "COLON":
                self.advance()
                domain = self.parse_expr(0)
            if self.peek().kind == "PIPE":
                self.advance()
                pred = self.parse_expr(0)
                self.match_kind("RBRACE")
                return SetBuilderExpr(var=var_name, domain=domain, predicate=pred)
        # Backtrack and parse as set enumeration `{a, b, c}`
        self.pos = saved
        elems = [self.parse_expr(0)]
        while self.match_kind("COMMA"):
            if self.peek().kind == "RBRACE":
                break
            elems.append(self.parse_expr(0))
        self.match_kind("RBRACE")
        return AppExpr(SymbolExpr("__SET_ENUM__"), elems)

    def parse_matrix_or_vec(self) -> MathExpr:
        self.advance()  # consume `![`
        rows: List[List[MathExpr]] = []
        flat: List[MathExpr] = []
        is_matrix = False
        while self.peek().kind not in ("RBRACK", "EOF"):
            if self.peek().value == "![" or self.peek().kind == "LBRACK":
                is_matrix = True
                self.advance()
                row: List[MathExpr] = []
                while self.peek().kind not in ("RBRACK", "EOF"):
                    row.append(self.parse_expr(0))
                    if not self.match_kind("COMMA"):
                        break
                self.match_kind("RBRACK")
                rows.append(row)
            else:
                flat.append(self.parse_expr(0))
            if not self.match_kind("COMMA"):
                break
        self.match_kind("RBRACK")
        if is_matrix:
            return MatrixExpr(rows=rows)
        return MatrixExpr(rows=[flat]) if flat else ListLitExpr([])

    def _parse_binder_group(self, stop_vals: Tuple[str, ...]) -> List[Tuple[List[str], Optional[MathExpr]]]:
        binders: List[Tuple[List[str], Optional[MathExpr]]] = []
        while self.peek().kind != "EOF" and self.peek().value not in stop_vals:
            tok = self.peek()
            if tok.kind in ("LPAREN", "LBRACE"):
                close_kind = "RPAREN" if tok.kind == "LPAREN" else "RBRACE"
                self.advance()
                names: List[str] = []
                while self.peek().kind == "IDENT":
                    names.append(self.advance().value)
                ty: Optional[MathExpr] = None
                if self.peek().kind == "COLON":
                    self.advance()
                    ty = self.parse_expr(0)
                elif self.peek().value in ("∈", "≤", "<", "≥", ">"):
                    # Bounded quantifier like `(x ∈ s)`
                    op = self.advance().value
                    rhs = self.parse_expr(0)
                    ty = BinaryOpExpr(op=op, left=SymbolExpr(names[0] if names else "_"), right=rhs)
                self.match_kind(close_kind)
                if names:
                    binders.append((names, ty))
            elif tok.kind == "IDENT":
                names = []
                while self.peek().kind == "IDENT" and self.peek().value not in stop_vals:
                    names.append(self.advance().value)
                ty = None
                if self.peek().kind == "COLON":
                    self.advance()
                    ty = self.parse_expr(0)
                elif self.peek().value in ("∈", "≤", "<", "≥", ">") and len(names) == 1:
                    op = self.advance().value
                    rhs = self.parse_expr(0)
                    ty = BinaryOpExpr(op=op, left=SymbolExpr(names[0]), right=rhs)
                if names:
                    binders.append((names, ty))
                break
            else:
                break
        return binders

    def parse_quantifier(self) -> MathExpr:
        tok = self.advance()
        kind = "forall" if tok.value in ("∀", "forall") else "exists"
        if tok.value == "∃!":
            kind = "exists_unique"
        binders = self._parse_binder_group((",",))
        self.match_kind("COMMA")
        body = self.parse_expr(0)
        return QuantifierExpr(kind=kind, binders=binders, body=body)

    def parse_lambda(self) -> MathExpr:
        self.advance()  # consume `fun` or `λ`
        params = self._parse_binder_group(("=>", "↦", ","))
        self.match_val("=>", "↦", ",")
        body = self.parse_expr(0)
        return LambdaExpr(params=params, body=body)

    def parse_bigop(self) -> MathExpr:
        tok = self.advance()
        kind = BIGOP_TOKENS[tok.value]
        binder = ""
        domain: Optional[MathExpr] = None
        if self.peek().kind == "IDENT":
            binder = self.advance().value
            if self.peek().value in ("∈", "in"):
                self.advance()
                domain = self.parse_expr(0)
            elif self.peek().kind == "COLON":
                self.advance()
                domain = self.parse_expr(0)
        self.match_kind("COMMA")
        body = self.parse_expr(0)
        return BigOpExpr(kind=kind, binder=binder, domain=domain, body=body)

    def parse_let(self) -> MathExpr:
        self.advance()  # consume `let`
        name = self.advance().value if self.peek().kind == "IDENT" else "_"
        ty: Optional[MathExpr] = None
        if self.peek().kind == "COLON":
            self.advance()
            ty = self.parse_expr(0)
        self.match_val(":=")
        val = self.parse_expr(0)
        if self.peek().kind == "SEMI" or self.peek().value == "in":
            self.advance()
        body = self.parse_expr(0) if self.peek().kind != "EOF" else SymbolExpr(name)
        return LetMathExpr(name=name, type_annot=ty, value=val, body=body)

    def parse_if(self) -> MathExpr:
        self.advance()  # consume `if`
        cond = self.parse_expr(0)
        self.match_val("then")
        then_b = self.parse_expr(0)
        self.match_val("else")
        else_b = self.parse_expr(0)
        return IfMathExpr(condition=cond, then_branch=then_b, else_branch=else_b)

    def parse_match(self) -> MathExpr:
        self.advance()  # consume `match`
        scrut = self.parse_expr(0)
        self.match_val("with")
        arms: List[Tuple[str, MathExpr]] = []
        while self.match_kind("PIPE"):
            pat_tokens: List[str] = []
            while self.peek().kind != "EOF" and self.peek().value != "=>":
                pat_tokens.append(self.advance().value)
            self.match_val("=>")
            arm_expr = self.parse_expr(0)
            arms.append((" ".join(pat_tokens).strip(), arm_expr))
        return MatchMathExpr(scrutinee=scrut, arms=arms)


def parse_math_expr(expr_text: str, line: int = 0) -> Tuple[MathExpr, List[ConversionWarning]]:
    """Parses a Lean 4 expression string into a MathExpr AST with safe fallback."""
    cleaned = expr_text.strip()
    if not cleaned:
        return SymbolExpr(""), []

    tokens, _, lex_warnings = tokenize_lean(cleaned)
    warnings = list(lex_warnings)

    # Check balanced delimiters before parsing to avoid misleading LaTeX
    stack: List[str] = []
    pairs = {"(": ")", "{": "}", "[": "]", "⟨": "⟩"}
    closers = set(pairs.values())
    unbalanced = False
    for t in tokens:
        if t.kind in ("COMMENT", "STRING", "NEWLINE", "EOF"):
            continue
        if t.value in pairs:
            stack.append(pairs[t.value])
        elif t.value == "![":
            stack.append("]")
        elif t.value in closers:
            if not stack or stack[-1] != t.value:
                unbalanced = True
                break
            stack.pop()
    if unbalanced or stack:
        warnings.append(
            ConversionWarning(
                code="UNBALANCED_EXPR",
                message="Unbalanced delimiters in expression; using safe Lean fallback.",
                line=line,
                source_snippet=cleaned[:80],
            )
        )
        return RawFallbackExpr(raw_lean=cleaned, reason="Unbalanced delimiters"), warnings

    # Detect unsupported meta/macro syntax that shouldn't be turned into misleading LaTeX
    if any(tok in cleaned for tok in ("`(", "macro_rules", "elab ", "syntax ")):
        warnings.append(
            ConversionWarning(
                code="UNSUPPORTED_MACRO_EXPR",
                message="Meta/macro expression cannot be safely rendered as mathematical LaTeX; using Lean fallback.",
                line=line,
                source_snippet=cleaned[:80],
            )
        )
        return RawFallbackExpr(raw_lean=cleaned, reason="Unsupported macro/meta expression"), warnings

    try:
        parser = _ExprParser(tokens, cleaned, base_line=line)
        ast = parser.parse_expr(0)
        warnings.extend(parser.warnings)
        # If significant unconsumed tokens remain, fall back safely
        remaining = [t for t in parser.tokens[parser.pos:] if t.kind != "EOF"]
        if len(remaining) > 2:
            warnings.append(
                ConversionWarning(
                    code="PARTIAL_EXPR_PARSE",
                    message=f"Expression had unparsed trailing tokens (`{' '.join(t.value for t in remaining[:4])}`); using safe Lean fallback.",
                    line=line,
                    source_snippet=cleaned[:80],
                )
            )
            return RawFallbackExpr(raw_lean=cleaned, reason="Partial parse"), warnings
        return ast, warnings
    except Exception as exc:
        warnings.append(
            ConversionWarning(
                code="EXPR_PARSE_ERROR",
                message=f"Could not parse expression ({exc}); using safe Lean fallback.",
                line=line,
                source_snippet=cleaned[:80],
            )
        )
        return RawFallbackExpr(raw_lean=cleaned, reason=str(exc)), warnings
