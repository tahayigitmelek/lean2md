"""Markdown + LaTeX Document Generator for Lean2Markdown."""

import re
from typing import TYPE_CHECKING, List

from ..ir import Declaration, DocumentIR, ProofStep
from ..latex_renderer import (
    binders_to_prose_and_latex,
    format_symbol,
    render_math_expr,
)

if TYPE_CHECKING:
    from ..pipeline import ConversionConfig


def _humanize_name(name: str) -> str:
    """Converts a Lean identifier like `add_comm_example` into a readable title."""
    short = name.rsplit(".", 1)[-1]
    if short.startswith("example_L") or short.startswith("instance_L"):
        return short
    words = [w for w in re.split(r"[_]+", short) if w]
    if not words:
        return short
    return " ".join(w[0].upper() + w[1:] if len(w) > 1 else w.upper() for w in words)


def _render_proof_steps_md(steps: List[ProofStep], show_comments: bool) -> List[str]:
    """Renders step-by-step human-readable proof walkthrough in Markdown + LaTeX."""
    lines: List[str] = []
    if not steps:
        lines.append("*Proof omitted or empty.*")
        return lines

    # Single simple tactic -> concise paragraph (like "The result follows by...")
    if (
        len(steps) == 1
        and steps[0].kind == "tactic"
        and not steps[0].leading_comments
        and not steps[0].inline_comment
        and steps[0].reliable
    ):
        lines.append(steps[0].explanation)
        return lines

    step_num = 0
    for st in steps:
        if show_comments and st.leading_comments:
            for c in st.leading_comments:
                if c.text:
                    lines.append(f"> *Note (L{c.start_line}):* {c.text}")
                    lines.append("")

        if st.kind == "comment":
            continue

        if st.kind == "calc":
            step_num += 1
            lines.append(f"{step_num}. {st.explanation}")
            if st.math_latex:
                lines.append("")
                lines.append("\\[")
                lines.append(st.math_latex)
                lines.append("\\]")
            if show_comments:
                for cs in st.calc_steps:
                    for cc in cs.comments:
                        if cc.text:
                            lines.append(f"   > *Comment (L{cc.start_line}):* {cc.text}")
            if show_comments and st.inline_comment:
                lines.append(f"   - *Comment:* {st.inline_comment}")
            continue

        step_num += 1
        indent_prefix = "   " if st.indent >= 4 and st.kind != "branch" else ""
        bullet = f"{step_num}." if not indent_prefix else "-"
        entry = f"{indent_prefix}{bullet} {st.explanation}"
        if show_comments and st.inline_comment:
            entry += f" *(Note: {st.inline_comment})*"
        lines.append(entry)

    return lines


def _render_declaration_md(
    decl: Declaration,
    label_prefix: str,
    number: int,
    cfg: "ConversionConfig",
) -> List[str]:
    """Renders a single Declaration block into Markdown + LaTeX."""
    out: List[str] = []
    human_title = _humanize_name(decl.name)
    num_str = f" {number}" if cfg.number_theorems else ""
    ns_badge = f" (`{decl.qualified_name}`)" if decl.qualified_name and decl.qualified_name != decl.name else f" (`{decl.name}`)"

    out.append(f"### {label_prefix}{num_str}: {human_title}{ns_badge}")
    out.append("")

    # Docstring
    if cfg.show_docstrings and decl.doc_comment and decl.doc_comment.text:
        out.append(decl.doc_comment.text)
        out.append("")

    # Leading comments
    if cfg.show_comments and decl.leading_comments:
        for c in decl.leading_comments:
            if c.text:
                out.append(f"> {c.text}")
        out.append("")

    # Notation / infix / prefix / postfix
    if decl.kind in ("notation", "infix", "infixl", "infixr", "prefix", "postfix"):
        out.append(f"Custom `{decl.kind}` rule:")
        out.append("")
        out.append("```lean")
        out.append(decl.raw_source)
        out.append("```")
        out.append("")
        return out

    # Structure / Class
    if decl.kind in ("structure", "class"):
        prose, _ = binders_to_prose_and_latex(decl.binders)
        if prose:
            out.append(prose)
            out.append("")
        if decl.return_type_raw:
            out.append(f"**Signature:** `{decl.return_type_raw}`")
            out.append("")
        if decl.fields:
            out.append("| Field | Type | Notes |")
            out.append("| :--- | :--- | :--- |")
            for f in decl.fields:
                t_tex, is_fb = render_math_expr(f.type_ir)
                type_cell = f"`{f.type_raw}`" if is_fb or not t_tex else f"\\({t_tex}\\)"
                notes = []
                if f.default_value:
                    notes.append(f"default: `{f.default_value}`")
                if cfg.show_docstrings and f.doc_comment and f.doc_comment.text:
                    notes.append(f.doc_comment.text.replace("\n", " "))
                if cfg.show_comments and f.inline_comment:
                    notes.append(f.inline_comment)
                note_cell = "; ".join(notes) if notes else "—"
                out.append(f"| `{f.name}` | {type_cell} | {note_cell} |")
            out.append("")
        return out

    # Inductive type
    if decl.kind == "inductive":
        prose, _ = binders_to_prose_and_latex(decl.binders)
        if prose:
            out.append(prose)
            out.append("")
        if decl.constructors:
            out.append("**Constructors:**")
            out.append("")
            for c in decl.constructors:
                sig_tex, is_fb = render_math_expr(c.signature_ir)
                if c.signature_raw:
                    sig_part = f" : `{c.signature_raw}`" if is_fb or not sig_tex else f" : \\({sig_tex}\\)"
                else:
                    sig_part = ""
                note_parts = []
                if cfg.show_docstrings and c.doc_comment and c.doc_comment.text:
                    note_parts.append(c.doc_comment.text.replace("\n", " "))
                if cfg.show_comments and c.inline_comment:
                    note_parts.append(c.inline_comment)
                note_suffix = f" — *{' '.join(note_parts)}*" if note_parts else ""
                out.append(f"- `{c.name}`{sig_part}{note_suffix}")
            out.append("")
        return out

    # Theorem / Lemma / Example / Axiom / Def / Abbrev / Opaque / Instance
    prose, _ = binders_to_prose_and_latex(decl.binders)
    if prose:
        out.append(prose)
        out.append("")

    # Return type / mathematical statement
    if decl.return_type_raw:
        ret_tex, is_fb = render_math_expr(decl.return_type_ir)
        if is_fb or not ret_tex:
            out.append("```lean")
            out.append(decl.return_type_raw)
            out.append("```")
        else:
            if decl.kind in ("def", "abbrev") and decl.body_ir is not None:
                body_tex, body_fb = render_math_expr(decl.body_ir)
                fn_lhs = format_symbol(decl.name)
                if decl.binders:
                    param_names = [
                        format_symbol(nm)
                        for b in decl.binders
                        if b.kind == "explicit"
                        for nm in b.names
                    ]
                    if param_names:
                        fn_lhs = f"{fn_lhs}({', '.join(param_names)})"
                out.append("\\[")
                if not body_fb and body_tex:
                    if cfg.show_types:
                        out.append(f"{fn_lhs} : {ret_tex} = {body_tex}")
                    else:
                        out.append(f"{fn_lhs} = {body_tex}")
                else:
                    out.append(f"{fn_lhs} : {ret_tex}")
                out.append("\\]")
            else:
                out.append("\\[")
                out.append(ret_tex)
                out.append("\\]")
        out.append("")
    elif decl.kind in ("def", "abbrev") and decl.body_ir is not None:
        body_tex, body_fb = render_math_expr(decl.body_ir)
        if not body_fb and body_tex:
            fn_lhs = format_symbol(decl.name)
            out.append("\\[")
            out.append(f"{fn_lhs} = {body_tex}")
            out.append("\\]")
            out.append("")

    # Proof rendering (for theorems, lemmas, examples, or tactic definitions)
    has_proof = decl.kind in ("theorem", "lemma", "example") or (decl.is_tactic_proof and bool(decl.proof_steps))
    if has_proof and decl.body_raw:
        if cfg.proof_mode == "statement":
            pass  # Mode A: Statement only
        elif cfg.proof_mode == "human":
            out.append("**Proof.**")
            out.append("")
            out.extend(_render_proof_steps_md(decl.proof_steps, cfg.show_comments))
            out.append("")
        elif cfg.proof_mode == "source":
            out.append("**Proof (Lean 4).**")
            out.append("")
            out.append("```lean")
            out.append(decl.raw_source)
            out.append("```")
            out.append("")

    return out


def generate_markdown(doc: DocumentIR, cfg: "ConversionConfig") -> str:
    """Generates a complete, structured Markdown + LaTeX document from a DocumentIR."""
    lines: List[str] = []
    title = cfg.title or f"Mathematical Documentation: {doc.source_name}"
    lines.append(f"# {title}")
    lines.append("")

    # Module docstrings
    if cfg.show_docstrings and doc.module_docs:
        for mdoc in doc.module_docs:
            lines.append(mdoc.text)
            lines.append("")

    # Optional Imports & Context section
    if cfg.include_imports and (doc.imports or doc.opens or doc.variables or doc.universes):
        lines.append("## Context and Imports")
        lines.append("")
        if doc.imports:
            lines.append("**Imports:** " + ", ".join(f"`{imp}`" for _, imp in doc.imports))
            lines.append("")
        if doc.opens:
            lines.append("**Opened Namespaces:** " + ", ".join(f"`{op}`" for _, op in doc.opens))
            lines.append("")
        if doc.universes:
            lines.append("**Universes:** " + ", ".join(f"`{u}`" for _, u in doc.universes))
            lines.append("")
        if doc.variables:
            lines.append("**Variables:**")
            lines.append("")
            for _, v in doc.variables:
                lines.append(f"- `{v}`")
            lines.append("")

    # Partition declarations into clean academic sections
    defs = [d for d in doc.declarations if d.kind in ("def", "abbrev", "opaque")]
    structs = [d for d in doc.declarations if d.kind in ("structure", "class", "inductive")]
    theorems = [d for d in doc.declarations if d.kind == "theorem"]
    lemmas = [d for d in doc.declarations if d.kind == "lemma"]
    examples = [d for d in doc.declarations if d.kind == "example"]
    axioms_insts = [d for d in doc.declarations if d.kind in ("axiom", "instance")]
    notations = [d for d in doc.declarations if d.kind in ("notation", "infix", "infixl", "infixr", "prefix", "postfix")]

    if cfg.include_definitions and structs:
        lines.append("## Structures and Types")
        lines.append("")
        for idx, d in enumerate(structs, 1):
            label = {"structure": "Structure", "class": "Typeclass", "inductive": "Inductive Type"}[d.kind]
            lines.extend(_render_declaration_md(d, label, idx, cfg))

    if cfg.include_definitions and defs:
        lines.append("## Definitions")
        lines.append("")
        for idx, d in enumerate(defs, 1):
            label = {"def": "Definition", "abbrev": "Abbreviation", "opaque": "Opaque Definition"}[d.kind]
            lines.extend(_render_declaration_md(d, label, idx, cfg))

    if notations:
        lines.append("## Custom Notation")
        lines.append("")
        for idx, d in enumerate(notations, 1):
            lines.extend(_render_declaration_md(d, "Notation", idx, cfg))

    if cfg.include_theorems and theorems:
        lines.append("## Theorems")
        lines.append("")
        for idx, d in enumerate(theorems, 1):
            lines.extend(_render_declaration_md(d, "Theorem", idx, cfg))

    if cfg.include_theorems and lemmas:
        lines.append("## Lemmas")
        lines.append("")
        for idx, d in enumerate(lemmas, 1):
            lines.extend(_render_declaration_md(d, "Lemma", idx, cfg))

    if cfg.include_theorems and examples:
        lines.append("## Examples")
        lines.append("")
        for idx, d in enumerate(examples, 1):
            lines.extend(_render_declaration_md(d, "Example", idx, cfg))

    if axioms_insts:
        lines.append("## Axioms and Instances")
        lines.append("")
        for idx, d in enumerate(axioms_insts, 1):
            label = "Axiom" if d.kind == "axiom" else "Instance"
            lines.extend(_render_declaration_md(d, label, idx, cfg))

    if cfg.include_source and doc.raw_source.strip():
        lines.append("## Original Lean Source")
        lines.append("")
        lines.append("```lean")
        lines.append(doc.raw_source.rstrip())
        lines.append("```")
        lines.append("")

    if cfg.verbose and doc.warnings:
        lines.append("## Conversion Warnings")
        lines.append("")
        for w in doc.warnings:
            loc = f"Line {w.line}: " if w.line else ""
            lines.append(f"- `[{w.code}]` {loc}{w.message}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
