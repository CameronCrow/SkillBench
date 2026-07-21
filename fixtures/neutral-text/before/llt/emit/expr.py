"""Do-More expression -> Allen-Bradley CPT expression translation (emit-side).

Expression-bearing ops (``MATH`` -> ``CPT``) carry a free-form formula. Do-More writes it
with C-style operators; AB ``CPT`` accepts a *different* operator set, so the formula must be
re-spelled when emitting. This is a target-rendering concern, so it lives emit-side (the IL
carries the expression as authored; see schema ``instruction.expression``).

What ``CPT`` *can* express: arithmetic (``+ - * / **``), grouping, the ``MOD`` operator, and
the math functions (ABS, SQRT, LN, LOG, SIN, ...) — these trig/log functions are expression-only
in Do-More (they never appear as standalone boxes), so they ride here, with the inverse-trig
names re-spelled to AB's grammar (ASIN->ASN, ACOS->ACS, ATAN->ATN), and ``PI()`` substituted with
its literal. ``ROUND(x)`` has no CPT function either, but rounding-to-nearest *is* expressible with
CPT-legal ops, so it is re-spelled (not flagged) to ``(TRN(x + 0.5))`` -- see ``_rewrite_round``.
What it *cannot*: the Do-More range-aggregate / conditional / indirect functions
(AVGR/MAXR/MINR/SUMR/STDEVR/STDEVPR/COUNTIF/SUMIF, MAX/MIN, FRAC, REF) -- AB CPT has no such
functions (range stats are the standalone AVE/STD boxes), so these are flagged for a rung rewrite.
Nor can it express comparisons, equality,
boolean logic, or a conditional/ternary — ``CPT`` computes a single numeric value, not a
boolean and not a branch. Those require a rung-level rewrite (e.g. EQU/CMP + a conditional
move) and are reported, not silently mangled.
"""

from __future__ import annotations

import re

# Do-More operator -> AB CPT operator, for operators with a clean 1:1 infix mapping.
# ``%`` (modulo) -> ``MOD`` is the confirmed case (AB CPT has no ``%``).
_MODULO_RE = re.compile(r"\s*%\s*")

# Do-More math *functions* whose spelling differs from the AB CPT expression grammar. The
# trig/log functions are expression-only in Do-More (``SIN``/``COS``/``ABS``/``SQRT``/... can
# *only* appear inside a MATH expression, never as a standalone box), and AB ``CPT`` accepts the
# same arithmetic-function set (ABS, ACS, ASN, ATN, COS, DEG, LN, LOG, RAD, SIN, SQRT, TAN, ...).
# Most names match 1:1 and pass through untouched; only the three inverse-trig functions are spelled
# differently (Do-More ``ASIN``/``ACOS``/``ATAN`` vs AB ``ASN``/``ACS``/``ATN``). ``SQRT`` matches
# AB's expression spelling (``SQR`` is AB's *standalone* relay instruction, not the expression form).
# Inverse-trig spelling differences plus the truncate-to-integer conversions: Do-More ``TRUNC``
# and ``TOINT`` both truncate a real to its whole part (no rounding) -- AB's expression function
# for that is ``TRN()`` (``TRUNC`` is the v36 standalone-instruction alias). So both re-spell to TRN.
_FUNC_RENAME = {"ASIN": "ASN", "ACOS": "ACS", "ATAN": "ATN", "TRUNC": "TRN", "TOINT": "TRN"}
_FUNC_RENAME_RE = re.compile(r"\b(" + "|".join(_FUNC_RENAME) + r")\b")

# Do-More ``PI()`` -> a numeric literal: AB CPT has no symbolic PI, so substitute the constant
# (a clean re-spell, like ``%``->``MOD``; the value coerces to the destination's REAL precision).
_PI_RE = re.compile(r"\bPI\s*\(\s*\)")
_PI_LITERAL = "3.14159265358979"

# Do-More MATH-expression *functions* that AB CPT cannot express at all -- range aggregates
# (AVGR/MAXR/MINR/SUMR/STDEVR/STDEVPR/COUNTIF/SUMIF), two-value MAX/MIN, the fractional part
# (FRAC), and the indirect read (REF). AB CPT's function set is only the per-element math funcs
# (ABS/trig/log/SQRT/TRN/...); range stats are standalone AB box instructions (AVE/STD), and
# MAX/MIN/FRAC/REF have no CPT analog -- so any use inside an expression needs a rung-level
# rewrite. Listed longest-first so e.g. ``MAXR`` is matched before ``MAX``. Requires a trailing
# ``(`` so a tag merely named ``MAX`` is not flagged.
# ``TOREAL`` (int->real) is deliberately NOT here: AB has no explicit "to real", but it does not need
# one -- a ``MOV``/``CPT`` into a REAL destination auto-converts an integer operand. So ``TOREAL`` is
# *mapped*, not flagged: a whole-expression ``TOREAL(<operand>)`` emits a native ``MOV`` (see
# ``standalone_toreal_operand`` + the emit layer), and a nested use is unwrapped by ``_rewrite_toreal``
# so AB's destination-type promotion does the conversion.
_CPT_UNSUPPORTED_FUNCS = ["STDEVPR", "STDEVR", "COUNTIF", "AVGR", "MAXR", "MINR", "SUMR",
                          "SUMIF", "FRAC", "MAX", "MIN", "REF"]
_CPT_UNSUPPORTED_RE = re.compile(r"\b(" + "|".join(_CPT_UNSUPPORTED_FUNCS) + r")\s*\(")

# Do-More ``TOREAL(x)`` converts an integer to a REAL. AB CPT has no such function, but it does not
# need one: a ``CPT`` whose destination is REAL promotes integer operands automatically. So instead
# of flagging it, ``_rewrite_toreal`` *unwraps* every ``TOREAL(<arg>)`` to ``(<arg>)`` and relies on
# dest-type promotion. (A whole-expression ``TOREAL(<operand>)`` is intercepted earlier by the emit
# layer and rendered as a native ``MOV`` -- see ``standalone_toreal_operand`` below.) The unwrap uses
# a balanced-paren scan (the arg may itself contain parens/functions), mirroring ``_rewrite_round``.
_TOREAL_RE = re.compile(r"\bTOREAL\s*\(")
# A whole-expression ``TOREAL(<operand>)`` where ``<operand>`` is a bare element/literal (an element
# path with optional index/member/bit/byte-cast, or a numeric literal) -- no operators, no nested
# call. Only these can ride a native ``MOV`` (which moves an operand, not an evaluated expression);
# a ``TOREAL`` of an arithmetic expression falls through to the unwrap + dest-type-promotion path.
_STANDALONE_TOREAL_RE = re.compile(r"^\s*TOREAL\s*\(\s*([A-Za-z0-9_.\[\]:]+)\s*\)\s*$")

# Do-More ``ROUND(x)`` rounds to the nearest whole number. AB ``CPT`` has NO ``ROUND`` function
# (its set is ABS/ACS/ASN/ATN/COS/DEG/LN/LOG/RAD/SIN/SQRT/TAN/TRN; ``TRN`` *truncates* toward zero,
# it does not round). But rounding-to-nearest is expressible with CPT-legal ops: for x >= 0,
# ``round(x) == TRN(x + 0.5)``. So instead of degrading the rung, ``_rewrite_round`` re-spells every
# ``ROUND(<arg>)`` to ``(TRN(<arg> + 0.5))`` -- parenthesized so it composes safely inside a larger
# expression. This is EXACT for non-negative x (Do-More/C ``ROUND`` is round-half-away-from-zero,
# which equals round-half-up for x >= 0), which covers the real TankStruct ``ROUND(gallons)`` rungs
# and process values generally; for possibly-negative x the emit layer attaches an informational note
# (round-half-up and round-half-away-from-zero differ only below zero). ``ROUND`` was missed by the
# earlier expression-function help-scan (it isn't in `docs/domore-instruction-triage.md`'s "16 more"
# list) but appears in the real export.
# NOTE: AB's lack of a CPT ROUND is from the Logix instruction reference, not a local L5X decode.
_ROUND_RE = re.compile(r"\bROUND\s*\(")


def expression_uses_round(expr: str) -> bool:
    """True if the (Do-More, as-authored) expression calls ``ROUND(...)``.

    The emit layer uses this to attach an informational note when it re-spells ROUND -- so the
    round-half-up/positive-domain assumption baked into ``_rewrite_round`` is recorded, not silent.
    """
    return bool(_ROUND_RE.search(expr))


def _rewrite_round(expr: str) -> str:
    """Re-spell every ``ROUND(<arg>)`` as the CPT-legal ``(TRN(<arg> + 0.5))``.

    Extracts each ROUND argument by *balanced*-paren scanning (a regex can't, since ``<arg>`` may
    itself contain parens, e.g. ``ROUND((a + b) * c)``), and loops so nested ``ROUND(ROUND(x))`` is
    fully rewritten. An unbalanced ``ROUND(`` is left untouched (it would be malformed anyway).
    """
    out = expr
    while True:
        m = _ROUND_RE.search(out)
        if not m:
            return out
        open_paren = m.end() - 1  # index of ROUND's '('
        depth = 0
        close = None
        for j in range(open_paren, len(out)):
            if out[j] == "(":
                depth += 1
            elif out[j] == ")":
                depth -= 1
                if depth == 0:
                    close = j
                    break
        if close is None:  # unbalanced -- bail rather than loop forever
            return out
        arg = out[open_paren + 1:close]
        out = out[:m.start()] + f"(TRN({arg} + 0.5))" + out[close + 1:]


def expression_uses_toreal(expr: str) -> bool:
    """True if the (Do-More, as-authored) expression calls ``TOREAL(...)``.

    The emit layer uses this to attach an informational note when it renders TOREAL via AB's
    destination-type REAL coercion -- so the int->REAL conversion is recorded, not silent.
    """
    return bool(_TOREAL_RE.search(expr))


def standalone_toreal_operand(expr: str) -> str | None:
    """If ``expr`` is a whole-expression ``TOREAL(<operand>)`` of a bare element/literal, return the
    operand text; else ``None``.

    Only a plain operand (no arithmetic/logic operators, no nested call) qualifies -- those are the
    cases the emit layer renders as a native ``MOV(<operand>, <REAL dest>)`` (AB auto-converts
    int->REAL). A ``TOREAL`` of an arithmetic expression returns ``None`` so the caller instead
    unwraps it (``_rewrite_toreal``) and lets the CPT destination-type promotion do the conversion.
    """
    m = _STANDALONE_TOREAL_RE.match(expr)
    return m.group(1) if m else None


def _rewrite_toreal(expr: str) -> str:
    """Unwrap every ``TOREAL(<arg>)`` to ``(<arg>)`` -- AB has no CPT ``TOREAL``; a REAL destination
    promotes the operand automatically, so the wrapper is redundant once the dest is REAL.

    Uses a balanced-paren scan (the arg may itself contain parens, e.g. ``TOREAL((a + b))``) and
    loops so a nested ``TOREAL(TOREAL(x))`` is fully unwrapped. An unbalanced ``TOREAL(`` is left
    untouched. Parenthesized on unwrap so it composes safely inside a larger expression.
    """
    out = expr
    while True:
        m = _TOREAL_RE.search(out)
        if not m:
            return out
        open_paren = m.end() - 1  # index of TOREAL's '('
        depth = 0
        close = None
        for j in range(open_paren, len(out)):
            if out[j] == "(":
                depth += 1
            elif out[j] == ")":
                depth -= 1
                if depth == 0:
                    close = j
                    break
        if close is None:  # unbalanced -- bail rather than loop forever
            return out
        arg = out[open_paren + 1:close]
        out = out[:m.start()] + f"({arg})" + out[close + 1:]

# Constructs AB CPT cannot express at all (CPT yields a number, not a boolean/branch). Each
# entry is (regex, human label). Order matters: match multi-char operators before single.
_INCOMPATIBLE = [
    (re.compile(r"\bIF\s*\("), "IF(...) conditional"),
    (re.compile(r"=="), "equality (==)"),
    (re.compile(r"!=|<>"), "inequality (!=)"),
    (re.compile(r"<=|>="), "comparison (<=, >=)"),
    # Boolean logic: && || and the unary logical-NOT ! (but not the != already matched above;
    # `!(?!=)` is `!` not followed by `=`). Do-More MATHLAND/MATHLOR/MATHLNOT operators.
    (re.compile(r"&&|\|\||!(?!=)"), "boolean logic (&&, ||, !)"),
    (re.compile(r"\?"), "ternary (?:)"),
]
# Bitwise / shift operators: AB CPT spells these AND/OR/XOR/NOT and has no shift operator.
# We do not auto-translate (precedence and intent need a human); flag for verification.
_BITWISE_RE = re.compile(r"<<|>>|(?<![&|])[&|](?![&|])|\^|~")

# Bare relational < > that are not part of <<, >>, <=, >= (checked after the above).
_RELATIONAL_RE = re.compile(r"(?<![<>=!])[<>](?![<>=])")


def translate_cpt_expression(expr: str) -> tuple[str, list[str]]:
    """Re-spell a Do-More MATH expression for AB ``CPT``.

    Returns ``(translated, issues)``. ``issues`` is a list of human-readable problems: each is
    a construct AB ``CPT`` cannot render, so the caller should raise a review diagnostic and the
    engineer must rewrite the rung. An empty list means the translated expression is CPT-clean.
    """
    out = _MODULO_RE.sub(" MOD ", expr)
    out = _FUNC_RENAME_RE.sub(lambda m: _FUNC_RENAME[m.group(1)], out)
    out = _PI_RE.sub(_PI_LITERAL, out)
    out = _rewrite_round(out)  # ROUND(x) -> (TRN(x + 0.5)); after the other re-spells so <arg> is translated too
    out = _rewrite_toreal(out)  # TOREAL(x) -> (x); AB promotes to REAL by the dest type (nested-use path)

    issues: list[str] = []
    for pattern, label in _INCOMPATIBLE:
        if pattern.search(out):
            issues.append(label)
    if _RELATIONAL_RE.search(out):
        issues.append("relational comparison (<, >)")
    if _BITWISE_RE.search(out):
        issues.append("bitwise/shift operator (spell as AND/OR/XOR/NOT in CPT; no shift op)")
    unsupported = sorted({m.group(1) for m in _CPT_UNSUPPORTED_RE.finditer(out)})
    for fn in unsupported:
        issues.append(f"function {fn}() has no AB CPT equivalent (range stats -> AB AVE/STD box; "
                      f"MAX/MIN/FRAC/REF -> rung rewrite)")

    return out.strip(), issues
