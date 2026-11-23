"""Step-by-step Lean 4 proof & tactic analyzer.

Parses `by` tactic blocks, `calc` chains, structured subgoals (`·`, `case`, `| ... =>`),
intermediate assertions (`have`, `let`, `obtain`, `show`, `suffices`), and preserves all
leading and inline comments. Never fabricates mathematical reasoning for unknown tactics.
"""

import re
from typing import Dict, List, Optional, Tuple

from .expr_parser import parse_math_expr
from .ir import CalcStep, Comment, ConversionWarning, ProofStep
from .latex_renderer import calc_steps_to_latex, render_math_expr

TACTIC_TEMPLATES: Dict[str, str] = {
    "rfl": "By reflexivity.",
    "simp": "By simplification{args_note}.",
    "simp_all": "By simplifying all hypotheses and the goal{args_note}.",
    "dsimp": "By definitional simplification{args_note}.",
    "ring": "By polynomial normalization (ring axioms).",
    "ring_nf": "By normalizing polynomial expressions into ring normal form.",
    "linarith": "By linear arithmetic{args_note}.",
    "nlinarith": "By nonlinear arithmetic{args_note}.",
    "omega": "By Presburger arithmetic (linear integer/natural arithmetic).",
    "norm_num": "By numerical normalization and evaluation.",
    "positivity": "By positivity of the constituent terms.",
    "field_simp": "By clearing denominators and simplifying field expressions{args_note}.",
    "exact": "By the supplied proof term {math_arg}.",
    "apply": "Applying {math_arg} reduces the goal to its premises.",
    "refine": "Refining the goal using {math_arg}.",
    "assumption": "By an existing assumption in the local context.",
    "contradiction": "By contradiction from inconsistent hypotheses.",
    "exfalso": "It suffices to derive a contradiction (ex falso quodlibet).",
    "trivial": "The goal holds trivially.",
    "decide": "By decidable computation.",
    "tauto": "By propositional tautology.",
    "aesop": "By automated proof search (details omitted; verify manually if needed).",
    "constructor": "By proving each required component separately.",
    "left": "Proving the left disjunct.",
    "right": "Proving the right disjunct.",
    "use": "Exhibiting the witness {math_arg}.",
    "exists": "Exhibiting the witness {math_arg}.",
    "intro": "Introduce arbitrary element(s) or hypothesis {raw_arg}.",
    "intros": "Introduce arbitrary elements or hypotheses {raw_arg}.",
    "rintro": "Introduce and destructure {raw_arg}.",
    "rw": "Rewrite using {raw_arg}.",
    "rewrite": "Rewrite using {raw_arg}.",
    "nth_rw": "Rewrite the specified occurrence(s) using {raw_arg}.",
    "erw": "Rewrite up to definitional equality using {raw_arg}.",
    "simp_rw": "Iteratively rewrite and simplify using {raw_arg}.",
    "induction": "Proceed by mathematical induction on {math_arg}.",
    "cases": "Proceed by case analysis on {math_arg}.",
    "rcases": "Destructure by cases on {raw_arg}.",
    "by_cases": "Split into cases depending on whether {math_arg} holds.",
    "by_contra": "Proceed by contradiction{args_note}.",
    "contrapose": "Proceed by proving the contrapositive.",
    "push_neg": "Push negations inward through logical connectives and quantifiers.",
    "ext": "By extensionality{args_note}.",
    "funext": "By function extensionality{args_note}.",
    "congr": "By congruence of the applied function/constructor.",
    "specialize": "Specialize hypothesis {raw_arg}.",
    "generalize": "Generalize {raw_arg}.",
    "revert": "Move {raw_arg} back into the goal.",
    "subst": "Substitute equality {raw_arg} throughout the context.",
    "injection": "By injectivity of the constructor on {raw_arg}.",
    "split_ifs": "Split on the conditional (`if ... then ... else`) branches.",
    "gcongr": "By generalized congruence for monotone relations.",
    "continuity": "By continuity of the constituent functions.",
    "measurability": "By measurability of the constituent functions.",
    "unfold": "Unfold the definition of {raw_arg}.",
    "change": "Rewrite the goal to the definitionally equal statement {math_arg}.",
    "clear": "Drop unused hypothesis {raw_arg} from the local context.",
    "sorry": "**Proof omitted (`sorry`) — requires a complete formal proof.**",
}

CALC_REL_RE = re.compile(r"^\s*(.*?)\s*(=|≤|≥|<|>|≠|<=|>=|!=|⊆|⊂|⊇|≡|≈|≃|↔|→|∣)\s*(.*?)\s*:=\s*(.*)$")
CALC_CONT_RE = re.compile(r"^\s*_\s*(=|≤|≥|<|>|≠|<=|>=|!=|⊆|⊂|⊇|≡|≈|≃|↔|→|∣)\s*(.*?)\s*:=\s*(.*)$")


def _strip_inline_comment(line: str) -> Tuple[str, Optional[str]]:
    """Splits a single Lean line into (code_part, inline_comment_text_or_None)."""
    in_str = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str and ch == "-" and i + 1 < n and line[i + 1] == "-":
            return line[:i].rstrip(), line[i + 2:].strip()
        i += 1
    return line.rstrip(), None


def _explain_tactic(tactic_name: str, args: str, line: int) -> Tuple[str, str, bool, List[ConversionWarning]]:
    """Produces (explanation, math_latex, reliable, warnings) for a tactic invocation."""
    warnings: List[ConversionWarning] = []
    base = tactic_name.rstrip("!")

    if base == "have":
        m = re.match(r"^(?:([A-Za-z0-9_']+)\s*)?:\s*(.+?)(?:\s*:=\s*(.*))?$", args)
        if m:
            hname, prop, proof_hint = m.group(1) or "", m.group(2).strip(), (m.group(3) or "").strip()
            ir, w = parse_math_expr(prop, line)
            warnings.extend(w)
            tex, fb = render_math_expr(ir)
            stmt = f"`{prop}`" if fb else f"\\({tex}\\)"
            label = f" \\({hname}\\)" if hname else ""
            expl = f"Establish intermediate claim{label}: {stmt}."
            if proof_hint and proof_hint != "by":
                expl += f" (justified by `{proof_hint}`)"
            return expl, "" if fb else tex, True, warnings
        return f"Establish intermediate claim `{args}`.", "", True, warnings

    if base == "let":
        m = re.match(r"^([A-Za-z0-9_']+)(?:\s*:\s*([^:=]+))?\s*:=\s*(.+)$", args)
        if m:
            vname, vval = m.group(1), m.group(3).strip()
            ir, w = parse_math_expr(vval, line)
            warnings.extend(w)
            tex, fb = render_math_expr(ir)
            val_str = f"`{vval}`" if fb else f"\\({tex}\\)"
            return f"Define local shorthand \\({vname} = \\) {val_str}.", "" if fb else f"{vname} = {tex}", True, warnings
        return f"Define local binding `{args}`.", "", True, warnings

    if base == "obtain":
        return f"Extract witness/components via `{args}`.", "", True, warnings

    if base == "show":
        ir, w = parse_math_expr(args, line)
        warnings.extend(w)
        tex, fb = render_math_expr(ir)
        stmt = f"`{args}`" if fb else f"\\({tex}\\)"
        return f"Reframe the current goal as {stmt}.", "" if fb else tex, True, warnings

    if base == "suffices":
        m = re.match(r"^(?:([A-Za-z0-9_']+)\s*:\s*)?(.+?)(?:\s+by\s*.*)?$", args)
        prop = m.group(2).strip() if m else args
        ir, w = parse_math_expr(prop, line)
        warnings.extend(w)
        tex, fb = render_math_expr(ir)
        stmt = f"`{prop}`" if fb else f"\\({tex}\\)"
        return f"It suffices to show {stmt}.", "" if fb else tex, True, warnings

    if base in TACTIC_TEMPLATES:
        tmpl = TACTIC_TEMPLATES[base]
        args_note = f" using `{args}`" if args else ""
        raw_arg = f"`{args}`" if args else "the appropriate terms"
        math_arg = raw_arg
        math_latex = ""
        if "{math_arg}" in tmpl and args:
            clean_arg = re.split(r"\s+with\b", args, maxsplit=1)[0].strip()
            ir, w = parse_math_expr(clean_arg, line)
            warnings.extend(w)
            tex, fb = render_math_expr(ir)
            if not fb and tex:
                math_arg = f"\\({tex}\\)"
                math_latex = tex
        expl = tmpl.format(args_note=args_note, raw_arg=raw_arg, math_arg=math_arg)
        reliable = base not in ("aesop", "sorry")
        return expl, math_latex, reliable, warnings

    warnings.append(
        ConversionWarning(
            code="UNKNOWN_TACTIC",
            message=f"Tactic `{tactic_name}` is not recognized; proof step requires manual explanation.",
            line=line,
            source_snippet=f"{tactic_name} {args}".strip()[:80],
        )
    )
    return (
        f"Proof step using tactic `{tactic_name}` (automated mathematical explanation unavailable; requires manual explanation).",
        "",
        False,
        warnings,
    )


def analyze_proof_body(body_raw: str, start_line: int, is_tactic: bool) -> Tuple[List[ProofStep], List[ConversionWarning]]:
    """Analyzes a Lean 4 proof body into structured ProofSteps while preserving every comment."""
    warnings: List[ConversionWarning] = []
    steps: List[ProofStep] = []

    if not body_raw or not body_raw.strip():
        return steps, warnings

    if not is_tactic:
        clean_term = body_raw.strip()
        ir, w = parse_math_expr(clean_term, start_line)
        warnings.extend(w)
        tex, fb = render_math_expr(ir)
        expl = (
            f"Direct proof term: \\({tex}\\)."
            if not fb and tex
            else f"Direct proof term `{clean_term}` (see Lean source for details)."
        )
        steps.append(
            ProofStep(
                step_id="1",
                kind="term",
                tactic_name="term",
                args=clean_term,
                raw_code=clean_term,
                line=start_line,
                end_line=start_line + body_raw.count("\n"),
                indent=0,
                explanation=expl,
                math_latex="" if fb else tex,
                reliable=not fb,
            )
        )
        return steps, warnings

    raw_lines = body_raw.splitlines()
    pending_comments: List[Comment] = []
    step_counter = 0
    i = 0
    total = len(raw_lines)

    while i < total:
        raw_ln = raw_lines[i]
        cur_line_no = start_line + i
        stripped = raw_ln.strip()
        indent = len(raw_ln) - len(raw_ln.lstrip(" "))

        if not stripped:
            i += 1
            continue

        if stripped.startswith("--"):
            pending_comments.append(
                Comment("line", stripped[2:].strip(), raw_ln, cur_line_no, cur_line_no, indent)
            )
            i += 1
            continue

        if stripped.startswith("/-"):
            block_lines = [raw_ln]
            b_start = cur_line_no
            depth = stripped.count("/-") - stripped.count("-/")
            while depth > 0 and i + 1 < total:
                i += 1
                block_lines.append(raw_lines[i])
                depth += raw_lines[i].count("/-") - raw_lines[i].count("-/")
            full_raw = "\n".join(block_lines)
            inner = full_raw.strip()
            if inner.startswith("/-") and inner.endswith("-/"):
                inner = inner[2:-2].strip()
            pending_comments.append(Comment("block", inner, full_raw, b_start, start_line + i, indent))
            i += 1
            continue

        code_part, inline_comment = _strip_inline_comment(raw_ln)
        code_stripped = code_part.strip()
        if not code_stripped:
            if inline_comment:
                pending_comments.append(
                    Comment("line", inline_comment, raw_ln, cur_line_no, cur_line_no, indent)
                )
            i += 1
            continue

        if code_stripped.startswith("| ") or code_stripped.startswith("case ") or code_stripped.startswith("·"):
            step_counter += 1
            if code_stripped.startswith("·"):
                sub_code = code_stripped[1:].strip()
                if sub_code:
                    t_parts = sub_code.split(None, 1)
                    t_name = t_parts[0]
                    t_args = t_parts[1] if len(t_parts) > 1 else ""
                    expl, m_tex, rel, w = _explain_tactic(t_name, t_args, cur_line_no)
                    warnings.extend(w)
                    steps.append(
                        ProofStep(
                            step_id=str(step_counter),
                            kind="branch",
                            tactic_name=t_name,
                            args=t_args,
                            raw_code=code_stripped,
                            line=cur_line_no,
                            end_line=cur_line_no,
                            indent=indent,
                            explanation=f"**Subgoal:** {expl}",
                            math_latex=m_tex,
                            reliable=rel,
                            leading_comments=pending_comments,
                            inline_comment=inline_comment,
                        )
                    )
                else:
                    steps.append(
                        ProofStep(
                            step_id=str(step_counter),
                            kind="branch",
                            tactic_name="subgoal",
                            args="",
                            raw_code=code_stripped,
                            line=cur_line_no,
                            end_line=cur_line_no,
                            indent=indent,
                            explanation="**Subgoal:**",
                            reliable=True,
                            leading_comments=pending_comments,
                            inline_comment=inline_comment,
                        )
                    )
                pending_comments = []
                i += 1
                continue

            branch_match = re.match(r"^(?:\|\s*|case\s+)(.+?)\s*=>\s*(.*)$", code_stripped)
            if branch_match:
                case_label = branch_match.group(1).strip()
                rest_tactic = branch_match.group(2).strip()
                expl = f"**Case `{case_label}`:**"
                m_tex = ""
                rel = True
                if rest_tactic:
                    t_parts = rest_tactic.split(None, 1)
                    sub_expl, m_tex, rel, w = _explain_tactic(
                        t_parts[0], t_parts[1] if len(t_parts) > 1 else "", cur_line_no
                    )
                    warnings.extend(w)
                    expl = f"**Case `{case_label}`:** {sub_expl}"
                steps.append(
                    ProofStep(
                        step_id=str(step_counter),
                        kind="branch",
                        tactic_name="case",
                        args=case_label,
                        raw_code=code_stripped,
                        line=cur_line_no,
                        end_line=cur_line_no,
                        indent=indent,
                        explanation=expl,
                        math_latex=m_tex,
                        reliable=rel,
                        leading_comments=pending_comments,
                        inline_comment=inline_comment,
                    )
                )
                pending_comments = []
                i += 1
                continue

        if code_stripped == "calc" or code_stripped.startswith("calc "):
            step_counter += 1
            calc_indent = indent
            calc_steps: List[CalcStep] = []
            calc_raw_lines = [raw_ln]
            calc_start = cur_line_no
            first_rest = code_stripped[4:].strip()
            if first_rest:
                m = CALC_REL_RE.match(first_rest)
                if m:
                    lhs_ir, w1 = parse_math_expr(m.group(1), cur_line_no)
                    rhs_ir, w2 = parse_math_expr(m.group(3), cur_line_no)
                    warnings.extend(w1 + w2)
                    calc_steps.append(
                        CalcStep(
                            lhs_raw=m.group(1).strip(),
                            relation=m.group(2).strip(),
                            rhs_raw=m.group(3).strip(),
                            justification=m.group(4).strip(),
                            line=cur_line_no,
                            lhs_ir=lhs_ir,
                            rhs_ir=rhs_ir,
                        )
                    )
            i += 1
            local_calc_comments: List[Comment] = []
            while i < total:
                c_raw = raw_lines[i]
                c_line_no = start_line + i
                c_stripped = c_raw.strip()
                c_indent = len(c_raw) - len(c_raw.lstrip(" "))
                if not c_stripped:
                    i += 1
                    continue
                if c_indent <= calc_indent and not c_stripped.startswith("_"):
                    break
                if c_stripped.startswith("--"):
                    local_calc_comments.append(
                        Comment("line", c_stripped[2:].strip(), c_raw, c_line_no, c_line_no, c_indent)
                    )
                    calc_raw_lines.append(c_raw)
                    i += 1
                    continue
                c_code, c_inl = _strip_inline_comment(c_raw)
                c_code_s = c_code.strip()
                m_cont = CALC_CONT_RE.match(c_code_s)
                m_full = CALC_REL_RE.match(c_code_s)
                if m_cont:
                    rhs_ir, w2 = parse_math_expr(m_cont.group(2), c_line_no)
                    warnings.extend(w2)
                    if c_inl:
                        local_calc_comments.append(Comment("line", c_inl, c_raw, c_line_no, c_line_no, c_indent))
                    calc_steps.append(
                        CalcStep(
                            lhs_raw="",
                            relation=m_cont.group(1).strip(),
                            rhs_raw=m_cont.group(2).strip(),
                            justification=m_cont.group(3).strip(),
                            line=c_line_no,
                            rhs_ir=rhs_ir,
                            comments=local_calc_comments,
                        )
                    )
                    local_calc_comments = []
                    calc_raw_lines.append(c_raw)
                    i += 1
                elif m_full and not calc_steps:
                    lhs_ir, w1 = parse_math_expr(m_full.group(1), c_line_no)
                    rhs_ir, w2 = parse_math_expr(m_full.group(3), c_line_no)
                    warnings.extend(w1 + w2)
                    if c_inl:
                        local_calc_comments.append(Comment("line", c_inl, c_raw, c_line_no, c_line_no, c_indent))
                    calc_steps.append(
                        CalcStep(
                            lhs_raw=m_full.group(1).strip(),
                            relation=m_full.group(2).strip(),
                            rhs_raw=m_full.group(3).strip(),
                            justification=m_full.group(4).strip(),
                            line=c_line_no,
                            lhs_ir=lhs_ir,
                            rhs_ir=rhs_ir,
                            comments=local_calc_comments,
                        )
                    )
                    local_calc_comments = []
                    calc_raw_lines.append(c_raw)
                    i += 1
                else:
                    break

            calc_latex = calc_steps_to_latex(calc_steps)
            steps.append(
                ProofStep(
                    step_id=str(step_counter),
                    kind="calc",
                    tactic_name="calc",
                    args="",
                    raw_code="\n".join(calc_raw_lines),
                    line=calc_start,
                    end_line=start_line + i - 1,
                    indent=calc_indent,
                    explanation="By the following chain of equalities/inequalities:",
                    math_latex=calc_latex,
                    reliable=bool(calc_steps),
                    leading_comments=pending_comments,
                    inline_comment=inline_comment,
                    calc_steps=calc_steps,
                )
            )
            pending_comments = []
            continue

        sub_tactics = [s.strip() for s in re.split(r"\s*(?:<;>|;)\s*", code_stripped) if s.strip()]
        for sub_idx, stac in enumerate(sub_tactics):
            step_counter += 1
            parts = stac.split(None, 1)
            t_name = parts[0]
            t_args = parts[1] if len(parts) > 1 else ""
            expl, m_tex, rel, w = _explain_tactic(t_name, t_args, cur_line_no)
            warnings.extend(w)
            kind = t_name if t_name in ("have", "let", "obtain", "show", "suffices") else "tactic"
            steps.append(
                ProofStep(
                    step_id=str(step_counter),
                    kind=kind,
                    tactic_name=t_name,
                    args=t_args,
                    raw_code=stac,
                    line=cur_line_no,
                    end_line=cur_line_no,
                    indent=indent,
                    explanation=expl,
                    math_latex=m_tex,
                    reliable=rel,
                    leading_comments=pending_comments if sub_idx == 0 else [],
                    inline_comment=inline_comment if sub_idx == len(sub_tactics) - 1 else None,
                )
            )
        pending_comments = []
        i += 1

    if pending_comments:
        step_counter += 1
        steps.append(
            ProofStep(
                step_id=str(step_counter),
                kind="comment",
                tactic_name="comment",
                args="",
                raw_code="",
                line=pending_comments[0].start_line,
                end_line=pending_comments[-1].end_line,
                indent=pending_comments[0].indent,
                explanation="",
                reliable=True,
                leading_comments=pending_comments,
            )
        )

    return steps, warnings
