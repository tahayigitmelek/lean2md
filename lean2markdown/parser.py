"""Full Lean 4 Declaration & File Parser.

Extracts imports, namespaces, sections, variables, universes, open directives,
docstrings, module docstrings, line/block comments, and all Lean 4 declaration kinds
(`def`, `theorem`, `lemma`, `example`, `structure`, `class`, `inductive`, `instance`,
`axiom`, `opaque`, `abbrev`, `notation`, `infix`, `prefix`, `postfix`) including
binders, dependent types, `where` clauses, and nested declarations.
"""

import re
from typing import List, Optional, Tuple

from .expr_parser import parse_math_expr
from .ir import (
    Binder,
    Comment,
    ConversionWarning,
    Declaration,
    DocumentIR,
    InductiveConstructor,
    StructField,
    TopLevelDirective,
)
from .lexer import tokenize_lean
from .tactic_analyzer import analyze_proof_body

MODIFIERS = {"private", "protected", "noncomputable", "partial", "unsafe", "local", "scoped"}

DECL_KEYWORDS = {
    "theorem", "lemma", "def", "abbrev", "opaque", "axiom", "example",
    "structure", "class", "inductive", "instance",
    "notation", "infix", "infixl", "infixr", "prefix", "postfix",
}

PROPOSITION_KINDS = {"theorem", "lemma", "axiom"}

DIRECTIVE_KEYWORDS = {
    "import", "public", "module", "open", "variable", "variables", "universe", "universes",
    "namespace", "section", "end", "set_option", "attribute",
    "assert_not_exists", "initialize_simps_projections", "alias",
}


def _strip_line_comment(line: str) -> Tuple[str, Optional[str]]:
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


def _find_top_level_char(text: str, target: str) -> int:
    depth = 0
    in_str = False
    for idx, ch in enumerate(text):
        if ch == '"' and (idx == 0 or text[idx - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch in "({[⦃⟨":
            depth += 1
        elif ch in ")}]⦄⟩":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(target, idx):
            if target == ":" and idx + 1 < len(text) and text[idx + 1] == "=":
                continue
            return idx
    return -1


def _find_top_level_assign(text: str) -> int:
    depth = 0
    in_str = False
    for idx in range(len(text) - 1):
        ch = text[idx]
        if ch == '"' and (idx == 0 or text[idx - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch in "({[⦃⟨":
            depth += 1
        elif ch in ")}]⦄⟩":
            depth = max(0, depth - 1)
        elif depth == 0 and text[idx:idx + 2] == ":=":
            return idx
    return -1


def _parse_binders(header: str, line: int) -> Tuple[List[Binder], str, List[ConversionWarning]]:
    """Splits a declaration header (after the name) into (binders, return_type_raw, warnings)."""
    binders: List[Binder] = []
    warnings: List[ConversionWarning] = []
    s = header.strip()
    i = 0
    n = len(s)

    open_to_close = {"(": ")", "{": "}", "[": "]", "⦃": "⦄"}
    open_to_kind = {"(": "explicit", "{": "implicit", "[": "instance", "⦃": "strict_implicit"}

    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break

        if s[i] == ":":
            return binders, s[i + 1:].strip(), warnings

        ch = s[i]
        if ch in open_to_close:
            close_ch = open_to_close[ch]
            kind = open_to_kind[ch]
            start = i
            depth = 1
            i += 1
            while i < n and depth > 0:
                if s[i] == ch:
                    depth += 1
                elif s[i] == close_ch:
                    depth -= 1
                i += 1
            raw_b = s[start:i]
            inner = raw_b[1:-1].strip() if depth == 0 else raw_b[1:].strip()
            names: List[str] = []
            type_raw = inner
            colon_idx = _find_top_level_char(inner, ":")
            if colon_idx != -1:
                names = [nm for nm in inner[:colon_idx].strip().split() if nm]
                type_raw = inner[colon_idx + 1:].strip()
            elif kind == "instance":
                names = []
                type_raw = inner
            else:
                names = [nm for nm in inner.split() if nm]
                type_raw = ""

            type_ir = None
            if type_raw:
                type_ir, w = parse_math_expr(type_raw, line)
                warnings.extend(w)

            binders.append(
                Binder(kind=kind, names=names, type_raw=type_raw, type_ir=type_ir, raw=raw_b)
            )
            continue

        m = re.match(r"([A-Za-z_][A-Za-z0-9_']*)", s[i:])
        if m:
            binders.append(Binder(kind="explicit", names=[m.group(1)], type_raw="", raw=m.group(1)))
            i += len(m.group(1))
            continue

        break

    return binders, s[i:].strip(), warnings


def _split_decl_header_and_body(
    kind: str, decl_text: str, start_line: int
) -> Tuple[str, List[str], List[Binder], str, str, bool, List[ConversionWarning]]:
    """Extracts (name, universe_params, binders, return_type_raw, body_raw, is_tactic, warnings)."""
    warnings: List[ConversionWarning] = []
    s = decl_text.strip()
    while s.startswith("@["):
        end_attr = s.find("]")
        if end_attr == -1:
            break
        s = s[end_attr + 1:].strip()

    tokens_head = s.split(None, 1)
    while tokens_head and tokens_head[0] in MODIFIERS:
        s = tokens_head[1] if len(tokens_head) > 1 else ""
        tokens_head = s.split(None, 1)

    if s.startswith(kind):
        s = s[len(kind):].strip()

    if kind in ("notation", "infix", "infixl", "infixr", "prefix", "postfix"):
        name_m = re.search(r'"([^"]+)"', s)
        name = name_m.group(1) if name_m else kind
        return name, [], [], s, "", False, warnings

    if kind == "example":
        name = f"example_L{start_line}"
        rest = s
        u_params: List[str] = []
    elif kind == "instance":
        # Strip optional `(priority := N)` before instance name
        prio_m = re.match(r"^\(\s*priority\s*:=[^)]+\)\s*(.*)$", s, re.DOTALL)
        if prio_m:
            s = prio_m.group(1).strip()
        if s.startswith("[") or s.startswith("(") or s.startswith("{") or s.startswith(":"):
            name = f"instance_L{start_line}"
            rest = s
            u_params = []
        else:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_'.]*)(?:\.\{([^}]+)\})?(.*)$", s, re.DOTALL)
            name = m.group(1) if m else f"instance_L{start_line}"
            u_params = [u.strip() for u in (m.group(2) or "").split(",") if u.strip()]
            rest = m.group(3).strip() if m else s
    else:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_'.]*)(?:\.\{([^}]+)\})?(.*)$", s, re.DOTALL)
        if m:
            name = m.group(1)
            u_params = [u.strip() for u in (m.group(2) or "").split(",") if u.strip()]
            rest = m.group(3).strip()
        else:
            name = f"{kind}_L{start_line}"
            u_params = []
            rest = s

    if kind in ("structure", "class", "inductive"):
        where_m = re.search(r"\bwhere\b", rest)
        if where_m:
            sig_part = rest[:where_m.start()].strip()
            body_part = rest[where_m.end():].strip()
        else:
            pipe_idx = _find_top_level_char(rest, "|")
            if pipe_idx != -1:
                sig_part = rest[:pipe_idx].strip()
                body_part = rest[pipe_idx:].strip()
            else:
                sig_part = rest
                body_part = ""
        ext_m = re.search(r"\bextends\b(.*)$", sig_part, re.DOTALL)
        extends_note = ""
        if ext_m:
            extends_note = ext_m.group(1).strip()
            sig_part = sig_part[:ext_m.start()].strip()
        binders, ret_type, w = _parse_binders(sig_part, start_line)
        warnings.extend(w)
        if extends_note:
            ret_type = f"extends {extends_note}" + (f" : {ret_type}" if ret_type else "")
        return name, u_params, binders, ret_type, body_part, False, warnings

    assign_idx = _find_top_level_assign(rest)
    where_m = re.search(r"\bwhere\b", rest) if assign_idx == -1 and kind == "instance" else None

    if assign_idx != -1:
        sig_part = rest[:assign_idx].strip()
        body_part = rest[assign_idx + 2:].strip()
    elif where_m:
        sig_part = rest[:where_m.start()].strip()
        body_part = "where\n" + rest[where_m.end():].strip()
    else:
        pipe_idx = _find_top_level_char(rest, "|")
        if pipe_idx != -1 and kind in ("def", "abbrev"):
            sig_part = rest[:pipe_idx].strip()
            body_part = rest[pipe_idx:].strip()
        else:
            sig_part = rest
            body_part = ""

    binders, ret_type, w = _parse_binders(sig_part, start_line)
    warnings.extend(w)

    is_tactic = False
    if body_part.startswith("by") and (len(body_part) == 2 or body_part[2].isspace()):
        is_tactic = True
        body_part = body_part[2:].lstrip(" \t")
        if body_part.startswith("\n"):
            body_part = body_part[1:]
    elif body_part.startswith("calc") and (len(body_part) == 4 or body_part[4].isspace()):
        is_tactic = True

    return name, u_params, binders, ret_type, body_part, is_tactic, warnings


def _parse_struct_fields(body_raw: str, base_line: int) -> Tuple[List[StructField], List[ConversionWarning]]:
    fields: List[StructField] = []
    warnings: List[ConversionWarning] = []
    if not body_raw.strip():
        return fields, warnings

    lines = body_raw.splitlines()
    pending_doc: Optional[Comment] = None
    i = 0
    while i < len(lines):
        raw_ln = lines[i]
        ln_no = base_line + i
        stripped = raw_ln.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("/--"):
            buf = [raw_ln]
            b_start = ln_no
            while "-/" not in raw_ln and i + 1 < len(lines):
                i += 1
                raw_ln = lines[i]
                buf.append(raw_ln)
            txt = "\n".join(buf).strip()
            if txt.startswith("/--") and txt.endswith("-/"):
                txt = txt[3:-2].strip()
            pending_doc = Comment("doc", txt, "\n".join(buf), b_start, base_line + i)
            i += 1
            continue
        if stripped.startswith("--"):
            i += 1
            continue

        code, inl = _strip_line_comment(raw_ln)
        code_s = code.strip()
        colon_idx = _find_top_level_char(code_s, ":")
        if colon_idx != -1:
            fname = code_s[:colon_idx].strip()
            ftype_full = code_s[colon_idx + 1:].strip()
            default_val = None
            def_idx = _find_top_level_assign(ftype_full)
            if def_idx != -1:
                default_val = ftype_full[def_idx + 2:].strip()
                ftype_full = ftype_full[:def_idx].strip()
            t_ir, w = parse_math_expr(ftype_full, ln_no)
            warnings.extend(w)
            fields.append(
                StructField(
                    name=fname,
                    type_raw=ftype_full,
                    type_ir=t_ir,
                    default_value=default_val,
                    doc_comment=pending_doc,
                    inline_comment=inl,
                    line=ln_no,
                )
            )
            pending_doc = None
        i += 1
    return fields, warnings


def _parse_inductive_constructors(body_raw: str, base_line: int) -> Tuple[List[InductiveConstructor], List[ConversionWarning]]:
    ctors: List[InductiveConstructor] = []
    warnings: List[ConversionWarning] = []
    if not body_raw.strip():
        return ctors, warnings

    lines = body_raw.splitlines()
    pending_doc: Optional[Comment] = None
    i = 0
    while i < len(lines):
        raw_ln = lines[i]
        ln_no = base_line + i
        stripped = raw_ln.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("/--"):
            buf = [raw_ln]
            b_start = ln_no
            while "-/" not in raw_ln and i + 1 < len(lines):
                i += 1
                raw_ln = lines[i]
                buf.append(raw_ln)
            txt = "\n".join(buf).strip()
            if txt.startswith("/--") and txt.endswith("-/"):
                txt = txt[3:-2].strip()
            pending_doc = Comment("doc", txt, "\n".join(buf), b_start, base_line + i)
            i += 1
            continue
        if stripped.startswith("--") or stripped.startswith("deriving "):
            i += 1
            continue

        code, inl = _strip_line_comment(raw_ln)
        code_s = code.strip()
        if code_s.startswith("|"):
            code_s = code_s[1:].strip()
        if not code_s:
            i += 1
            continue
        colon_idx = _find_top_level_char(code_s, ":")
        if colon_idx != -1:
            cname = code_s[:colon_idx].strip()
            csig = code_s[colon_idx + 1:].strip()
            sig_ir, w = parse_math_expr(csig, ln_no)
            warnings.extend(w)
        else:
            cname = code_s.split()[0]
            csig = ""
            sig_ir = None
        ctors.append(
            InductiveConstructor(
                name=cname,
                signature_raw=csig,
                signature_ir=sig_ir,
                doc_comment=pending_doc,
                inline_comment=inl,
                line=ln_no,
            )
        )
        pending_doc = None
        i += 1
    return ctors, warnings


def _detect_decl_start(stripped: str) -> Tuple[Optional[str], List[str], List[str]]:
    s = stripped
    attrs: List[str] = []
    mods: List[str] = []

    while s.startswith("@["):
        end_idx = s.find("]")
        if end_idx == -1:
            break
        attrs.append(s[2:end_idx].strip())
        s = s[end_idx + 1:].strip()

    parts = s.split()
    idx = 0
    while idx < len(parts) and parts[idx] in MODIFIERS:
        mods.append(parts[idx])
        idx += 1

    if idx < len(parts):
        base_kw = parts[idx].split(":", 1)[0]
        if base_kw in DECL_KEYWORDS:
            return base_kw, attrs, mods
    return None, attrs, mods


def _is_top_level_starter(line: str) -> bool:
    if not line or line[0].isspace():
        return False
    s = line.strip()
    if not s:
        return False
    if s.startswith(("--", "/-", "@[", "#")):
        return True
    first = s.split()[0].split(":", 1)[0]
    if first in DIRECTIVE_KEYWORDS or first in DECL_KEYWORDS or first in MODIFIERS:
        return True
    return False


def parse_lean_source(source: str, source_name: str = "<stdin>") -> DocumentIR:
    """Parses a complete Lean 4 source file into a DocumentIR."""
    _, _, lex_warnings = tokenize_lean(source)
    lines = source.splitlines()
    doc = DocumentIR(
        source_name=source_name,
        total_lines=len(lines),
        backend="parser",
        warnings=list(lex_warnings),
        raw_source=source,
    )

    namespace_stack: List[str] = []
    section_stack: List[str] = []
    scope_stack: List[Tuple[str, str]] = []

    pending_doc: Optional[Comment] = None
    pending_comments: List[Comment] = []
    pending_attrs: List[str] = []

    i = 0
    n = len(lines)

    def current_ns() -> str:
        return ".".join(namespace_stack)

    def current_sec() -> str:
        return ".".join(section_stack)

    while i < n:
        raw_ln = lines[i]
        ln_no = i + 1
        stripped = raw_ln.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("/-!"):
            b_start = ln_no
            buf = [raw_ln]
            depth = stripped.count("/-") - stripped.count("-/")
            while depth > 0 and i + 1 < n:
                i += 1
                buf.append(lines[i])
                depth += lines[i].count("/-") - lines[i].count("-/")
            full_raw = "\n".join(buf)
            inner = full_raw.strip()
            inner = inner[3:-2].strip() if inner.endswith("-/") else inner[3:].strip()
            c = Comment("module_doc", inner, full_raw, b_start, i + 1)
            doc.module_docs.append(c)
            doc.directives.append(TopLevelDirective("module_doc", inner, b_start, i + 1, current_ns(), c))
            i += 1
            continue

        if stripped.startswith("/--"):
            b_start = ln_no
            buf = [raw_ln]
            depth = stripped.count("/-") - stripped.count("-/")
            while depth > 0 and i + 1 < n:
                i += 1
                buf.append(lines[i])
                depth += lines[i].count("/-") - lines[i].count("-/")
            full_raw = "\n".join(buf)
            inner = full_raw.strip()
            inner = inner[3:-2].strip() if inner.endswith("-/") else inner[3:].strip()
            pending_doc = Comment("doc", inner, full_raw, b_start, i + 1)
            i += 1
            continue

        if stripped.startswith("/-"):
            b_start = ln_no
            buf = [raw_ln]
            depth = stripped.count("/-") - stripped.count("-/")
            while depth > 0 and i + 1 < n:
                i += 1
                buf.append(lines[i])
                depth += lines[i].count("/-") - lines[i].count("-/")
            full_raw = "\n".join(buf)
            inner = full_raw.strip()
            inner = inner[2:-2].strip() if inner.endswith("-/") else inner[2:].strip()
            pending_comments.append(Comment("block", inner, full_raw, b_start, i + 1))
            i += 1
            continue

        if stripped.startswith("--"):
            pending_comments.append(Comment("line", stripped[2:].strip(), raw_ln, ln_no, ln_no))
            i += 1
            continue

        if stripped.startswith("@[") and stripped.endswith("]") and _detect_decl_start(stripped)[0] is None:
            pending_attrs.append(stripped[2:-1].strip())
            i += 1
            continue

        first_word = stripped.split()[0]

        if first_word == "import" or stripped.startswith("public import "):
            imp = stripped.split("import", 1)[1].strip()
            doc.imports.append((ln_no, imp))
            doc.directives.append(TopLevelDirective("import", imp, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if first_word == "open":
            opn = stripped[len("open"):].strip()
            doc.opens.append((ln_no, opn))
            doc.directives.append(TopLevelDirective("open", opn, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if first_word in ("variable", "variables"):
            var_decl = stripped[len(first_word):].strip()
            doc.variables.append((ln_no, var_decl))
            doc.directives.append(TopLevelDirective("variable", var_decl, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if first_word in ("universe", "universes"):
            uni_decl = stripped[len(first_word):].strip()
            doc.universes.append((ln_no, uni_decl))
            doc.directives.append(TopLevelDirective("universe", uni_decl, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if first_word == "namespace":
            ns_name = stripped[len("namespace"):].strip()
            namespace_stack.append(ns_name)
            scope_stack.append(("namespace", ns_name))
            doc.directives.append(TopLevelDirective("namespace", ns_name, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if first_word == "section":
            sec_name = stripped[len("section"):].strip()
            section_stack.append(sec_name)
            scope_stack.append(("section", sec_name))
            doc.directives.append(TopLevelDirective("section", sec_name, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if first_word == "end":
            end_name = stripped[len("end"):].strip()
            if not scope_stack:
                doc.warnings.append(
                    ConversionWarning(
                        code="UNMATCHED_END",
                        message=f"Unmatched `end {end_name}` with no open namespace or section.",
                        line=ln_no,
                        source_snippet=stripped,
                    )
                )
            else:
                sc_kind, sc_name = scope_stack.pop()
                if sc_kind == "namespace" and namespace_stack:
                    namespace_stack.pop()
                elif sc_kind == "section" and section_stack:
                    section_stack.pop()
                if end_name and sc_name and end_name != sc_name:
                    doc.warnings.append(
                        ConversionWarning(
                            code="MISMATCHED_END",
                            message=f"`end {end_name}` does not match open {sc_kind} `{sc_name}`.",
                            line=ln_no,
                            source_snippet=stripped,
                        )
                    )
            doc.directives.append(TopLevelDirective("end", end_name, ln_no, ln_no, current_ns()))
            i += 1
            continue

        if (
            first_word in ("set_option", "attribute", "module", "assert_not_exists", "initialize_simps_projections", "alias")
            or stripped.startswith("#")
            or stripped.startswith("protected alias ")
            or (stripped.startswith("@[expose]") and "section" in stripped)
        ):
            doc.directives.append(TopLevelDirective("command", stripped, ln_no, ln_no, current_ns()))
            i += 1
            continue

        decl_kind, line_attrs, mods = _detect_decl_start(stripped)
        if decl_kind is not None:
            start_ln = ln_no
            decl_lines = [raw_ln]
            i += 1
            while i < n:
                nxt = lines[i]
                if not nxt.strip():
                    look = i + 1
                    while look < n and not lines[look].strip():
                        look += 1
                    if look < n and not _is_top_level_starter(lines[look]):
                        decl_lines.append(nxt)
                        i += 1
                        continue
                    break
                if _is_top_level_starter(nxt):
                    break
                decl_lines.append(nxt)
                i += 1

            end_ln = start_ln + len(decl_lines) - 1
            raw_decl = "\n".join(decl_lines)
            all_attrs = pending_attrs + line_attrs
            pending_attrs = []

            name, u_params, binders, ret_type_raw, body_raw, is_tactic, w_hdr = _split_decl_header_and_body(
                decl_kind, raw_decl, start_ln
            )
            doc.warnings.extend(w_hdr)

            ret_ir = None
            if ret_type_raw and decl_kind not in ("notation", "infix", "infixl", "infixr", "prefix", "postfix", "structure", "class"):
                ret_ir, w_ret = parse_math_expr(ret_type_raw, start_ln)
                doc.warnings.extend(w_ret)

            fields: List[StructField] = []
            ctors: List[InductiveConstructor] = []
            proof_steps = []
            body_ir = None

            body_start_line = start_ln + raw_decl[:max(0, raw_decl.find(body_raw))].count("\n") if body_raw else start_ln

            if decl_kind in ("structure", "class"):
                fields, w_f = _parse_struct_fields(body_raw, body_start_line)
                doc.warnings.extend(w_f)
            elif decl_kind == "inductive":
                ctors, w_c = _parse_inductive_constructors(body_raw, body_start_line)
                doc.warnings.extend(w_c)
            elif decl_kind in ("theorem", "lemma", "example"):
                proof_steps, w_p = analyze_proof_body(body_raw, body_start_line, is_tactic)
                doc.warnings.extend(w_p)
            elif decl_kind in ("def", "abbrev", "instance") and body_raw:
                if is_tactic:
                    proof_steps, w_p = analyze_proof_body(body_raw, body_start_line, True)
                    doc.warnings.extend(w_p)
                elif not body_raw.startswith("where"):
                    body_ir, w_b = parse_math_expr(body_raw, body_start_line)
                    doc.warnings.extend(w_b)

            ns = current_ns()
            qualified = f"{ns}.{name}" if ns and not name.startswith(ns + ".") else name
            is_prop = decl_kind in PROPOSITION_KINDS or (
                decl_kind == "example" and (is_tactic or any(op in ret_type_raw for op in ("=", "≤", "<", "∀", "∃", "→", "↔", "∧", "∨")))
            )

            decl = Declaration(
                kind=decl_kind,
                name=name,
                qualified_name=qualified,
                modifiers=mods,
                attributes=all_attrs,
                universe_params=u_params,
                binders=binders,
                return_type_raw=ret_type_raw,
                return_type_ir=ret_ir,
                body_raw=body_raw,
                body_ir=body_ir,
                is_proposition=is_prop,
                is_tactic_proof=is_tactic,
                namespace=ns,
                section=current_sec(),
                start_line=start_ln,
                end_line=end_ln,
                doc_comment=pending_doc,
                leading_comments=pending_comments,
                fields=fields,
                constructors=ctors,
                proof_steps=proof_steps,
                raw_source=raw_decl,
            )
            doc.declarations.append(decl)
            pending_doc = None
            pending_comments = []
            continue

        doc.warnings.append(
            ConversionWarning(
                code="UNRECOGNIZED_TOP_LEVEL",
                message=f"Unrecognized top-level construct starting with `{first_word}`; preserved as raw directive.",
                line=ln_no,
                source_snippet=stripped[:80],
            )
        )
        doc.directives.append(TopLevelDirective("command", stripped, ln_no, ln_no, current_ns()))
        i += 1

    if scope_stack:
        for sc_kind, sc_name in scope_stack:
            doc.warnings.append(
                ConversionWarning(
                    code="UNCLOSED_SCOPE",
                    message=f"Unclosed `{sc_kind} {sc_name}` at end of file.",
                    line=n,
                )
            )

    return doc
