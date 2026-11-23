"""MathExpr IR -> LaTeX renderer with operator precedence, domain conventions, and safe fallbacks."""

import re
from typing import Dict, List, Optional, Tuple

from .ir import (
    AppExpr,
    BigOpExpr,
    BinaryOpExpr,
    Binder,
    CalcStep,
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

SYMBOL_MAP: Dict[str, str] = {
    "Nat": r"\mathbb{N}",
    "ℕ": r"\mathbb{N}",
    "Int": r"\mathbb{Z}",
    "ℤ": r"\mathbb{Z}",
    "Rat": r"\mathbb{Q}",
    "ℚ": r"\mathbb{Q}",
    "Real": r"\mathbb{R}",
    "ℝ": r"\mathbb{R}",
    "Complex": r"\mathbb{C}",
    "ℂ": r"\mathbb{C}",
    "ℙ": r"\mathbb{P}",
    "𝔽": r"\mathbb{F}",
    "ℍ": r"\mathbb{H}",
    "Prop": r"\mathrm{Prop}",
    "Type": r"\mathrm{Type}",
    "Sort": r"\mathrm{Sort}",
    "Bool": r"\mathrm{Bool}",
    "True": r"\top",
    "False": r"\bot",
    "⊤": r"\top",
    "⊥": r"\bot",
    "∅": r"\varnothing",
    "∞": r"\infty",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "ϵ": r"\epsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\varphi",
    "ϕ": r"\phi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
}

BINARY_OP_LATEX: Dict[str, str] = {
    "+": "+",
    "-": "-",
    "*": r"\cdot",
    "·": r"\cdot",
    "×": r"\times",
    "⊗": r"\otimes",
    "⊕": r"\oplus",
    "±": r"\pm",
    "∘": r"\circ",
    "=": "=",
    "≠": r"\neq",
    "!=": r"\neq",
    "<": "<",
    ">": ">",
    "≤": r"\leq",
    "<=": r"\leq",
    "≥": r"\geq",
    ">=": r"\geq",
    "≡": r"\equiv",
    "≈": r"\approx",
    "≃": r"\simeq",
    "≅": r"\cong",
    "∼": r"\sim",
    "∣": r"\mid",
    "∤": r"\nmid",
    "∈": r"\in",
    "∉": r"\notin",
    "⊆": r"\subseteq",
    "⊂": r"\subset",
    "⊇": r"\supseteq",
    "⊃": r"\supset",
    "∪": r"\cup",
    "∩": r"\cap",
    "∖": r"\setminus",
    "\\": r"\setminus",
    "•": r"\cdot",
    "+ᵥ": r"+_{\mathrm{v}}",
    "''": r"''",
    "∧": r"\land",
    "/\\": r"\land",
    "&&": r"\land",
    "∨": r"\lor",
    "\\/": r"\lor",
    "||": r"\lor",
    "→": r"\rightarrow",
    "->": r"\rightarrow",
    "↔": r"\leftrightarrow",
    "<->": r"\leftrightarrow",
    "++": r"\mathbin{+\!\!+}",
    "::": r"\mathbin{::}",
    "%": r"\bmod",
}

STANDARD_MATH_FUNCS = {
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "log", "ln", "exp", "lim", "limsup", "liminf",
    "max", "min", "sup", "inf", "det", "gcd", "lcm", "dim", "ker", "deg",
}

SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def format_symbol(name: str) -> str:
    """Formats a Lean identifier into valid, readable LaTeX."""
    if not name:
        return ""
    if name in SYMBOL_MAP:
        return SYMBOL_MAP[name]

    if "." in name:
        base = name.rsplit(".", 1)[-1]
        if base in STANDARD_MATH_FUNCS:
            return "\\" + base
        if name == "Real.pi":
            return r"\pi"
        if name == "Complex.I":
            return "i"

    if name in STANDARD_MATH_FUNCS:
        return "\\" + name

    sub_match = re.match(r"^([A-Za-zα-ωΑ-Ω]+)([₀₁₂₃₄₅₆₇₈₉]+)$", name)
    if sub_match:
        stem, digits = sub_match.groups()
        stem_tex = SYMBOL_MAP.get(stem, stem if len(stem) == 1 else r"\mathrm{" + stem + "}")
        return f"{stem_tex}_{{{digits.translate(SUBSCRIPT_DIGITS)}}}"

    if len(name) == 1 and name.isalpha():
        return name
    if len(name) == 2 and name[0].isalpha() and name[1] in ("'", "′"):
        return f"{name[0]}'"

    escaped = name.replace("_", r"\_")
    if "_" in name or "." in name or len(name) >= 2:
        return r"\mathrm{" + escaped + "}"
    return escaped


def _needs_parens(child: MathExpr, parent_prec: int, is_right: bool = False) -> bool:
    if isinstance(child, BinaryOpExpr):
        if child.precedence < parent_prec:
            return True
        if is_right and child.precedence == parent_prec:
            return True
    if isinstance(child, (QuantifierExpr, LambdaExpr, LetMathExpr, IfMathExpr)):
        return parent_prec > 20
    return False


def render_math_expr(expr: Optional[MathExpr]) -> Tuple[str, bool]:
    """Renders a MathExpr IR node to LaTeX. Returns (latex_str, is_fallback)."""
    if expr is None:
        return "", False

    if isinstance(expr, RawFallbackExpr):
        return expr.raw_lean, True

    if isinstance(expr, NumberExpr):
        return expr.value, False

    if isinstance(expr, StringLitExpr):
        safe = expr.value.replace("_", r"\_").replace("{", r"\{").replace("}", r"\}")
        return r"\text{" + safe + "}", False

    if isinstance(expr, SymbolExpr):
        return format_symbol(expr.name), False

    if isinstance(expr, UnaryOpExpr):
        inner, fb = render_math_expr(expr.operand)
        if fb:
            return f"{expr.op} {inner}", True
        if expr.op in ("¬", "!"):
            if isinstance(expr.operand, (BinaryOpExpr, QuantifierExpr)):
                return rf"\neg ({inner})", False
            return rf"\neg {inner}", False
        if expr.op == "√":
            return rf"\sqrt{{{inner}}}", False
        if expr.op == "-":
            if isinstance(expr.operand, BinaryOpExpr) and expr.operand.precedence < expr.precedence:
                return f"-({inner})", False
            return f"-{inner}", False
        return f"{expr.op}{inner}", False

    if isinstance(expr, BinaryOpExpr):
        l_tex, l_fb = render_math_expr(expr.left)
        r_tex, r_fb = render_math_expr(expr.right)
        if l_fb or r_fb:
            return f"{l_tex} {expr.op} {r_tex}", True

        if expr.op == "/":
            return rf"\frac{{{l_tex}}}{{{r_tex}}}", False

        if expr.op == "^":
            if _needs_parens(expr.left, expr.precedence):
                l_tex = f"({l_tex})"
            return f"{l_tex}^{{{r_tex}}}", False

        if expr.op in ("→", "->") and isinstance(expr.left, TypeAnnotExpr):
            return rf"\prod_{{{l_tex}}} {r_tex}", False

        if _needs_parens(expr.left, expr.precedence, is_right=False):
            l_tex = f"({l_tex})"
        if _needs_parens(expr.right, expr.precedence, is_right=True):
            r_tex = f"({r_tex})"

        op_tex = BINARY_OP_LATEX.get(expr.op, expr.op)
        return f"{l_tex} {op_tex} {r_tex}", False

    if isinstance(expr, AppExpr):
        if isinstance(expr.func, SymbolExpr) and expr.func.name == "__SET_ENUM__":
            rendered = [render_math_expr(a) for a in expr.args]
            if any(fb for _, fb in rendered):
                return "{" + ", ".join(t for t, _ in rendered) + "}", True
            return r"\{" + ", ".join(t for t, _ in rendered) + r"\}", False

        if isinstance(expr.func, SymbolExpr):
            fname = expr.func.name
            if fname in ("deriv", "HasDerivAt") and len(expr.args) >= 2:
                f_tex, _ = render_math_expr(expr.args[0])
                x_tex, _ = render_math_expr(expr.args[1])
                return rf"\frac{{d}}{{d{x_tex}}}\left({f_tex}\right)", False
            if fname in ("Tendsto", "Filter.Tendsto") and len(expr.args) >= 3:
                f_tex, _ = render_math_expr(expr.args[0])
                l1_tex, _ = render_math_expr(expr.args[1])
                l2_tex, _ = render_math_expr(expr.args[2])
                return rf"\lim_{{{l1_tex}}} {f_tex} = {l2_tex}", False
            if fname in ("abs", "Real.abs") and len(expr.args) == 1:
                a_tex, _ = render_math_expr(expr.args[0])
                return rf"\left|{a_tex}\right|", False
            if fname == "norm" and len(expr.args) == 1:
                a_tex, _ = render_math_expr(expr.args[0])
                return rf"\left\|{a_tex}\right\|", False
            if fname in ("Real.sqrt", "Nat.sqrt", "sqrt") and len(expr.args) == 1:
                a_tex, _ = render_math_expr(expr.args[0])
                return rf"\sqrt{{{a_tex}}}", False
            if fname in ("Finset.sum", "tsum") and len(expr.args) >= 2:
                dom_tex, _ = render_math_expr(expr.args[0])
                fn_tex, _ = render_math_expr(expr.args[1])
                return rf"\sum_{{{dom_tex}}} {fn_tex}", False
            if fname in ("Finset.prod", "tprod") and len(expr.args) >= 2:
                dom_tex, _ = render_math_expr(expr.args[0])
                fn_tex, _ = render_math_expr(expr.args[1])
                return rf"\prod_{{{dom_tex}}} {fn_tex}", False

        f_tex, f_fb = render_math_expr(expr.func)
        rendered_args = [render_math_expr(a) for a in expr.args]
        if f_fb or any(fb for _, fb in rendered_args):
            return f"{f_tex} " + " ".join(t for t, _ in rendered_args), True
        args_str = ", ".join(t for t, _ in rendered_args)
        return f"{f_tex}({args_str})", False

    if isinstance(expr, QuantifierExpr):
        q_tex = {
            "forall": r"\forall",
            "exists": r"\exists",
            "exists_unique": r"\exists!",
        }.get(expr.kind, r"\forall")
        b_parts: List[str] = []
        for names, ty in expr.binders:
            n_tex = ", ".join(format_symbol(n) for n in names)
            if ty is not None:
                t_tex, _ = render_math_expr(ty)
                if isinstance(ty, BinaryOpExpr) and ty.op in ("∈", "≤", "<", "≥", ">"):
                    b_parts.append(t_tex)
                else:
                    b_parts.append(rf"{n_tex} \in {t_tex}")
            else:
                b_parts.append(n_tex)
        body_tex, body_fb = render_math_expr(expr.body)
        if body_fb:
            return f"{q_tex} {', '.join(b_parts)}, {body_tex}", True
        return rf"{q_tex} {', '.join(b_parts)},\ {body_tex}", False

    if isinstance(expr, LambdaExpr):
        p_parts: List[str] = []
        for names, ty in expr.params:
            n_tex = ", ".join(format_symbol(n) for n in names)
            if ty is not None:
                t_tex, _ = render_math_expr(ty)
                p_parts.append(f"{n_tex} : {t_tex}")
            else:
                p_parts.append(n_tex)
        body_tex, body_fb = render_math_expr(expr.body)
        if body_fb:
            return f"fun {' '.join(p_parts)} => {body_tex}", True
        params_str = ", ".join(p_parts)
        if len(expr.params) > 1:
            params_str = f"({params_str})"
        return rf"{params_str} \mapsto {body_tex}", False

    if isinstance(expr, BigOpExpr):
        op_cmd = {
            "sum": r"\sum",
            "prod": r"\prod",
            "int": r"\int",
            "lim": r"\lim",
            "bigcup": r"\bigcup",
            "bigcap": r"\bigcap",
        }.get(expr.kind, r"\sum")
        sub = format_symbol(expr.binder)
        if expr.domain is not None:
            dom_tex, _ = render_math_expr(expr.domain)
            if expr.kind == "int":
                sub = dom_tex
            else:
                sub = rf"{sub} \in {dom_tex}" if sub else dom_tex
        body_tex, body_fb = render_math_expr(expr.body)
        if body_fb:
            return f"{op_cmd}_{{{sub}}} {body_tex}", True
        if expr.kind == "int" and expr.binder:
            return rf"{op_cmd}_{{{sub}}} {body_tex}\, d{format_symbol(expr.binder)}", False
        return rf"{op_cmd}_{{{sub}}} {body_tex}", False

    if isinstance(expr, SetBuilderExpr):
        v_tex = format_symbol(expr.var)
        p_tex, p_fb = render_math_expr(expr.predicate)
        if expr.domain is not None:
            d_tex, _ = render_math_expr(expr.domain)
            return rf"\left\{{ {v_tex} \in {d_tex} \;\middle|\; {p_tex} \right\}}", p_fb
        return rf"\left\{{ {v_tex} \;\middle|\; {p_tex} \right\}}", p_fb

    if isinstance(expr, TupleExpr):
        rendered = [render_math_expr(e) for e in expr.elements]
        fb = any(f for _, f in rendered)
        inner = ", ".join(t for t, _ in rendered)
        if expr.angle_brackets:
            return rf"\langle {inner} \rangle", fb
        return f"({inner})", fb

    if isinstance(expr, ListLitExpr):
        rendered = [render_math_expr(e) for e in expr.elements]
        fb = any(f for _, f in rendered)
        return "[" + ", ".join(t for t, _ in rendered) + "]", fb

    if isinstance(expr, MatrixExpr):
        row_strs: List[str] = []
        for row in expr.rows:
            cells = [render_math_expr(c)[0] for c in row]
            row_strs.append(" & ".join(cells))
        return "\\begin{pmatrix}\n" + " \\\\\n".join(row_strs) + "\n\\end{pmatrix}", False

    if isinstance(expr, LetMathExpr):
        v_tex, _ = render_math_expr(expr.value)
        b_tex, b_fb = render_math_expr(expr.body)
        n_tex = format_symbol(expr.name)
        return rf"\text{{let }} {n_tex} = {v_tex} \text{{ in }} {b_tex}", b_fb

    if isinstance(expr, IfMathExpr):
        c_tex, _ = render_math_expr(expr.condition)
        t_tex, _ = render_math_expr(expr.then_branch)
        e_tex, _ = render_math_expr(expr.else_branch)
        return (
            "\\begin{cases}\n"
            f"{t_tex} & \\text{{if }} {c_tex}, \\\\\n"
            f"{e_tex} & \\text{{otherwise.}}\n"
            "\\end{cases}"
        ), False

    if isinstance(expr, MatchMathExpr):
        rows = []
        for pat, arm_expr in expr.arms:
            a_tex, _ = render_math_expr(arm_expr)
            pat_tex = pat.replace("_", r"\_")
            rows.append(rf"{a_tex} & \text{{when }} \mathrm{{{pat_tex}}}")
        return "\\begin{cases}\n" + " \\\\\n".join(rows) + "\n\\end{cases}", False

    if isinstance(expr, TypeAnnotExpr):
        e_tex, e_fb = render_math_expr(expr.expr)
        t_tex, t_fb = render_math_expr(expr.type_expr)
        return f"{e_tex} : {t_tex}", e_fb or t_fb

    return str(expr), True


TYPE_PROSE_NAMES = {
    "Nat": "natural numbers",
    "ℕ": "natural numbers",
    "Int": "integers",
    "ℤ": "integers",
    "Rat": "rational numbers",
    "ℚ": "rational numbers",
    "Real": "real numbers",
    "ℝ": "real numbers",
    "Complex": "complex numbers",
    "ℂ": "complex numbers",
    "Prop": "propositions",
}


def binders_to_prose_and_latex(binders: List[Binder], show_implicit: bool = False) -> Tuple[str, List[str]]:
    """Produces a natural-language context sentence and a list of LaTeX assumptions."""
    quantified_clauses: List[str] = []
    assumptions: List[str] = []
    typeclasses: List[str] = []

    for b in binders:
        t_tex, is_fb = render_math_expr(b.type_ir)
        if not t_tex and b.type_raw:
            t_tex = b.type_raw

        if b.kind == "instance":
            typeclasses.append(f"\\({t_tex}\\)" if not is_fb else f"`{b.type_raw}`")
            continue

        is_hypothesis = (
            len(b.names) == 1
            and (
                b.names[0].startswith("h")
                or any(op in b.type_raw for op in ("=", "≤", "<", "≥", ">", "≠", "∈", "⊆", "∧", "∨", "↔", "∀", "∃", "∣"))
            )
        )

        if is_hypothesis:
            h_name = format_symbol(b.names[0])
            if is_fb:
                assumptions.append(f"\\({h_name}\\): `{b.type_raw}`")
            else:
                assumptions.append(f"\\({t_tex}\\)")
        else:
            names_tex = ", ".join(format_symbol(n) for n in b.names)
            raw_type = b.type_raw.strip()
            if raw_type in TYPE_PROSE_NAMES and names_tex:
                quantified_clauses.append(f"{TYPE_PROSE_NAMES[raw_type]} \\({names_tex}\\)")
            elif names_tex and t_tex:
                if is_fb:
                    quantified_clauses.append(f"\\({names_tex}\\) of type `{b.type_raw}`")
                elif "→" in raw_type or "->" in raw_type:
                    quantified_clauses.append(f"\\({names_tex} : {t_tex}\\)")
                else:
                    quantified_clauses.append(f"\\({names_tex} \\in {t_tex}\\)")
            elif t_tex:
                quantified_clauses.append(f"\\({t_tex}\\)")

    parts: List[str] = []
    if typeclasses:
        parts.append("Let " + ", ".join(typeclasses) + " be given.")
    if quantified_clauses:
        parts.append("For all " + ", ".join(quantified_clauses) + ",")
    if assumptions:
        if len(assumptions) == 1:
            parts.append(f"assuming {assumptions[0]},")
        else:
            parts.append("assuming " + " and ".join(assumptions) + ",")

    return " ".join(parts), assumptions


def calc_steps_to_latex(steps: List[CalcStep]) -> str:
    """Renders a `calc` proof chain into a LaTeX `aligned` block."""
    if not steps:
        return ""
    lines: List[str] = []
    for idx, st in enumerate(steps):
        rel = BINARY_OP_LATEX.get(st.relation, st.relation)
        rhs_tex, _ = render_math_expr(st.rhs_ir) if st.rhs_ir else (st.rhs_raw, False)
        just = st.justification.strip()
        if just.startswith("by "):
            just = just[3:].strip()
        just_tex = ""
        if just:
            safe_just = just.replace("_", r"\_").replace("{", r"\{").replace("}", r"\}")
            just_tex = rf" && \text{{(by }} \mathrm{{{safe_just}}} \text{{)}}"
        if idx == 0 and (st.lhs_ir or st.lhs_raw):
            lhs_tex, _ = render_math_expr(st.lhs_ir) if st.lhs_ir else (st.lhs_raw, False)
            lines.append(f"{lhs_tex} &\\; {rel} \\; {rhs_tex}{just_tex}")
        else:
            lines.append(f"&\\; {rel} \\; {rhs_tex}{just_tex}")
    return "\\begin{aligned}\n" + " \\\\\n".join(lines) + "\n\\end{aligned}"
