"""Standalone Compilable LaTeX (.tex) Generator for Lean2Markdown."""

import re
from typing import TYPE_CHECKING, List

from ..ir import Declaration, DocumentIR
from ..latex_renderer import binders_to_prose_and_latex, format_symbol, render_math_expr

if TYPE_CHECKING:
    from ..pipeline import ConversionConfig


def _tex_escape(text: str) -> str:
    """Escapes plain text for LaTeX while preserving inline \\(...\\) math segments."""
    parts = re.split(r"(\\\(.*?\\\))", text)
    out: List[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            out.append(part)
            continue
        s = part.replace("\\", r"\textbackslash{}")
        for ch, rep in (
            ("&", r"\&"),
            ("%", r"\%"),
            ("$", r"\$"),
            ("#", r"\#"),
            ("_", r"\_"),
            ("{", r"\{"),
            ("}", r"\}"),
            ("~", r"\textasciitilde{}"),
            ("^", r"\textasciicircum{}"),
        ):
            s = s.replace(ch, rep)
        # Convert inline markdown `code` -> \texttt{code}
        s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
        out.append(s)
    return "".join(out)


def _render_decl_tex(decl: Declaration, env: str, cfg: "ConversionConfig") -> List[str]:
    out: List[str] = []
    title_opt = _tex_escape(decl.qualified_name or decl.name)
    out.append(f"\\begin{{{env}}}[{title_opt}]")

    if cfg.show_docstrings and decl.doc_comment and decl.doc_comment.text:
        out.append(_tex_escape(decl.doc_comment.text))
        out.append("")

    prose, _ = binders_to_prose_and_latex(decl.binders)
    if prose:
        out.append(_tex_escape(prose))

    if decl.return_type_raw:
        ret_tex, is_fb = render_math_expr(decl.return_type_ir)
        if is_fb or not ret_tex:
            out.append("\\begin{verbatim}")
            out.append(decl.return_type_raw)
            out.append("\\end{verbatim}")
        else:
            if decl.kind in ("def", "abbrev") and decl.body_ir is not None:
                body_tex, body_fb = render_math_expr(decl.body_ir)
                fn_lhs = format_symbol(decl.name)
                if not body_fb and body_tex:
                    out.append("\\[")
                    out.append(f"{fn_lhs} : {ret_tex} = {body_tex}")
                    out.append("\\]")
                else:
                    out.append("\\[")
                    out.append(ret_tex)
                    out.append("\\]")
            else:
                out.append("\\[")
                out.append(ret_tex)
                out.append("\\]")

    if decl.kind in ("structure", "class") and decl.fields:
        out.append("\\begin{itemize}")
        for f in decl.fields:
            t_tex, fb = render_math_expr(f.type_ir)
            t_str = f"\\texttt{{{_tex_escape(f.type_raw)}}}" if fb or not t_tex else f"\\({t_tex}\\)"
            out.append(f"  \\item \\texttt{{{_tex_escape(f.name)}}} : {t_str}")
        out.append("\\end{itemize}")

    if decl.kind == "inductive" and decl.constructors:
        out.append("\\begin{itemize}")
        for c in decl.constructors:
            s_tex, fb = render_math_expr(c.signature_ir)
            s_str = f" : \\({s_tex}\\)" if (not fb and s_tex) else (f" : \\texttt{{{_tex_escape(c.signature_raw)}}}" if c.signature_raw else "")
            out.append(f"  \\item \\texttt{{{_tex_escape(c.name)}}}{s_str}")
        out.append("\\end{itemize}")

    out.append(f"\\end{{{env}}}")

    has_proof = decl.kind in ("theorem", "lemma", "example") and bool(decl.body_raw)
    if has_proof and cfg.proof_mode != "statement":
        out.append("\\begin{proof}")
        if cfg.proof_mode == "source":
            out.append("\\begin{verbatim}")
            out.append(decl.raw_source)
            out.append("\\end{verbatim}")
        else:
            if len(decl.proof_steps) == 1 and decl.proof_steps[0].kind == "tactic":
                out.append(_tex_escape(decl.proof_steps[0].explanation))
            else:
                out.append("\\begin{enumerate}")
                for st in decl.proof_steps:
                    if st.kind == "comment":
                        continue
                    if st.kind == "calc" and st.math_latex:
                        out.append(f"  \\item {_tex_escape(st.explanation)}")
                        out.append("  \\[")
                        out.append(st.math_latex)
                        out.append("  \\]")
                    else:
                        note = f" (\\emph{{{_tex_escape(st.inline_comment)}}})" if (cfg.show_comments and st.inline_comment) else ""
                        out.append(f"  \\item {_tex_escape(st.explanation)}{note}")
                out.append("\\end{enumerate}")
        out.append("\\end{proof}")

    out.append("")
    return out


def generate_latex(doc: DocumentIR, cfg: "ConversionConfig") -> str:
    """Generates a standalone LaTeX document using `amsmath`, `amssymb`, and `amsthm`."""
    title = _tex_escape(cfg.title or f"Mathematical Documentation: {doc.source_name}")
    lines: List[str] = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{amsmath, amssymb, amsthm}",
        r"\usepackage{hyperref}",
        r"",
        r"\newtheorem{theorem}{Theorem}",
        r"\newtheorem{lemma}[theorem]{Lemma}",
        r"\theoremstyle{definition}",
        r"\newtheorem{definition}{Definition}",
        r"\newtheorem{example}{Example}",
        r"\newtheorem{axiom}{Axiom}",
        r"",
        f"\\title{{{title}}}",
        r"\date{}",
        r"",
        r"\begin{document}",
        r"\maketitle",
        r"",
    ]

    if cfg.show_docstrings and doc.module_docs:
        for mdoc in doc.module_docs:
            lines.append(_tex_escape(mdoc.text))
            lines.append("")

    defs = [d for d in doc.declarations if d.kind in ("def", "abbrev", "opaque", "structure", "class", "inductive")]
    theorems = [d for d in doc.declarations if d.kind == "theorem"]
    lemmas = [d for d in doc.declarations if d.kind == "lemma"]
    examples = [d for d in doc.declarations if d.kind == "example"]
    axioms = [d for d in doc.declarations if d.kind == "axiom"]

    if cfg.include_definitions and defs:
        lines.append(r"\section{Definitions and Structures}")
        lines.append("")
        for d in defs:
            lines.extend(_render_decl_tex(d, "definition", cfg))

    if cfg.include_theorems and theorems:
        lines.append(r"\section{Theorems}")
        lines.append("")
        for d in theorems:
            lines.extend(_render_decl_tex(d, "theorem", cfg))

    if cfg.include_theorems and lemmas:
        lines.append(r"\section{Lemmas}")
        lines.append("")
        for d in lemmas:
            lines.extend(_render_decl_tex(d, "lemma", cfg))

    if cfg.include_theorems and examples:
        lines.append(r"\section{Examples}")
        lines.append("")
        for d in examples:
            lines.extend(_render_decl_tex(d, "example", cfg))

    if axioms:
        lines.append(r"\section{Axioms}")
        lines.append("")
        for d in axioms:
            lines.extend(_render_decl_tex(d, "axiom", cfg))

    if cfg.include_source and doc.raw_source.strip():
        lines.append(r"\section{Original Lean Source}")
        lines.append(r"\begin{verbatim}")
        lines.append(doc.raw_source.rstrip())
        lines.append(r"\end{verbatim}")

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"
