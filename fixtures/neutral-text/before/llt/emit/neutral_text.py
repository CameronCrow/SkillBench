"""Serialize an IL rung expression tree to Allen-Bradley neutral text.

The IL rung is an expression tree of three node kinds (``schema/il.schema.json``):

* ``instruction`` — a leaf, rendered ``OP(arg0,arg1,...)`` per the opcode registry;
* ``series`` — children juxtaposed (AND): ``XIC(a)XIO(b)OTE(c)``;
* ``branch`` — parallel legs in brackets: ``[leg,leg,...]``; an empty leg (empty
  ``series``) is the leading-comma bypass form ``[,leg]``.

Output is **compact** (no incidental whitespace). Studio 5000's own exports include
spaces inside ``[ ... ]``, but the neutral-text grammar is whitespace-tolerant on import
(``docs/L5X-docs/L5X_MAIN.md`` §4.4), so compact text imports identically and is
deterministic for golden tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from llt import opcodes
from llt.emit import aoi as aoi_mod
from llt.emit.expr import (
    expression_uses_round,
    expression_uses_toreal,
    standalone_toreal_operand,
    translate_cpt_expression,
)

# Actionable, AB-specific guidance for opaque source ops that have NO clean lowering -- the ones
# whose only faithful AB form would be a mistranslation (so the emitter flags them, per the locked
# "never mistranslate" rule) but where the engineer needs a concrete hand-implementation direction.
_OPAQUE_GUIDANCE: dict[str, str] = {
    "SR": "AB BSL/BSR shift the bits of a DINT array, not Do-More's named bit range -- map the "
          "shifted bits to an array tag and reconcile every reference to those bits by hand.",
    "DRUM": "AB SQO is a single-word sequencer; a Do-More DRUM's per-step timers/events/output "
            "masks have no direct SQO form -- rebuild it with SQO plus timers/logic by hand.",
    "PID": "AB PID/PIDE is configured very differently (tuning, scaling, mode) -- re-enter the "
           "loop in Studio using its PID faceplate rather than a mechanical translation.",
    # --- Device / comms I/O: an AB form exists (MSG family) but its faithful config is the
    #     controller/comms plumbing LLT leaves to the engineer (component-scoped export). ---
    "DEVREAD": "reads a register from a configured Do-More Device (@device) -- the AB analog is a "
               "MSG read, but the MESSAGE path/service and comms config are controller-owned (out "
               "of LLT scope). Add a MSG with a MESSAGE tag targeting the equivalent device by hand.",
    "DEVWRITE": "writes a register on a configured Do-More Device (@device) -- the AB analog is a "
                "MSG write, but the MESSAGE path/service and comms config are controller-owned (out "
                "of LLT scope). Add a MSG with a MESSAGE tag targeting the equivalent device by hand.",
    "SETUPIP": "configures the CPU Ethernet TCP/IP parameters -- controller/comms configuration, "
               "which LLT leaves to the engineer. Set the IP in the Logix controller/module "
               "properties, not in ladder.",
    "SETUPNOD": "configures Ethernet node parameters (peer/routing table) for networked comms -- "
                "controller/comms configuration, which LLT leaves to the engineer. Configure the "
                "equivalent node in Studio via MSG/sockets, not in ladder.",
    "SETTIME": "sets the PLC date/time (RTC) -- in Logix the wall clock is the WALLCLOCKTIME "
               "controller object; write it with SSV(WALLCLOCKTIME,...) by hand rather than a "
               "ladder box. Controller-scoped, engineer-owned.",
    "PUBLISH": "publishes MQTT topics (Do-More IoT) -- Logix ladder has no native MQTT instruction; "
               "route it through an EtherNet/IP bridge or a third-party MQTT connector/AOI. No "
               "mechanical lowering.",
    # --- Control flow with no AB ladder primitive: AB routines run start-to-end. ---
    # (EXIT/CONTINUE now lower to AB TND at parse time -- see domore_opcodes.BOX_MAP -- so they no
    # longer reach the opaque tail; only HALT stays opaque, as TND would mistranslate it.)
    "HALT": "halts the containing Program or Task -- AB has no halt instruction; model it as an "
            "engineer-owned fault (assert a fault in a Fault routine) or an interlock, not ladder.",
    # --- File I/O: no component-scoped Logix equivalent. ---
    "FILEOPEN": "opens a file on the Do-More RAMDISK/SD -- Logix has no component-scoped file I/O; "
                "use module-specific MSG or an off-ladder path (SD/OPC) by hand. No mechanical form.",
    "FILEREAD": "reads from a Do-More file handle -- Logix has no component-scoped file I/O; use "
                "module-specific MSG or an off-ladder path (SD/OPC) by hand. No mechanical form.",
    "FILEWRITE": "writes to a Do-More file handle -- Logix has no component-scoped file I/O; use "
                 "module-specific MSG or an off-ladder path (SD/OPC) by hand. No mechanical form.",
    "FILECLOSE": "closes a Do-More file handle -- Logix has no component-scoped file I/O; use "
                 "module-specific MSG or an off-ladder path (SD/OPC) by hand. No mechanical form.",
}

# Opaque ops that are genuinely engineer-owned configuration -- never a failed translation, so a
# hard UNSUPPORTED_INSTRUCTION error is misleading (issue #33). These get a softer, non-error
# structural diagnostic instead and drop out of the error count. Scoped narrowly to SETUPNOD for
# now; do not add ops here speculatively.
_ENGINEER_OWNED_STRUCTURAL: frozenset[str] = frozenset({"SETUPNOD"})

# Opaque printf-to-string ops (issue #31): translatable output-formatting, not a failed translation,
# but with no single-instruction AB form. They degrade to a non-error MANUAL_STRING_COMPOSE
# diagnostic + a `[LLT EMIT: STRING COMPOSE ...]` rung comment that preserves the original format
# (added by emit/string_compose.py's lower_string_compose pass) so the engineer can finish the
# compose by hand -- never a hard error. Kept in sync with string_compose.STRING_COMPOSE_OPS.
_STRING_COMPOSE_STRUCTURAL: frozenset[str] = frozenset({"STRPRINT"})


@dataclass
class Diagnostic:
    """A structured emit-phase diagnostic (mirrors the IL diagnostic shape, phase=emit)."""

    code: str
    severity: str  # "error" | "warning" | "info"
    message: str
    location: dict[str, Any] = field(default_factory=dict)
    phase: str = "emit"
    # The verify-tier flag (issue #91): True for a diagnostic that translated FAITHFULLY and only
    # needs a human to confirm after import (not "might be wrong"). Data-driven -- the diagnostic
    # itself carries the tier, so the UI/export/#90 route by this boolean, never a hardcoded op list.
    # Maps 1:1 to the IL schema's `requiresHumanReview` field, so a persisted diagnostic stays valid.
    requires_human_review: bool = False

    def as_dict(self) -> dict[str, Any]:
        d = {"severity": self.severity, "code": self.code, "phase": self.phase, "message": self.message}
        if self.location:
            d["location"] = self.location
        if self.requires_human_review:
            d["requiresHumanReview"] = True
        return d


def literal_to_text(value: Any) -> str:
    """Render a literal operand value as neutral text (AB uses 1/0 for booleans)."""
    if isinstance(value, bool):  # bool is a subclass of int — check first
        return "1" if value else "0"
    return str(value)


def operand_to_text(operand: dict[str, Any]) -> str:
    """Render one operand: a tag reference (with optional path/bit) or a literal."""
    if "literal" in operand:
        return literal_to_text(operand["literal"])
    text = operand["ref"]
    for seg in operand.get("path", []):
        if "member" in seg:
            text += "." + seg["member"]
        else:  # array subscript: literal int or a variable {ref}
            index = seg["index"]
            text += "[" + (index["ref"] if isinstance(index, dict) else str(index)) + "]"
    if "bit" in operand:
        text += "." + str(operand["bit"])
    return text


def _num(value: Any) -> str:
    """Render a numeric param (preset/accum); fall back to the raw string form."""
    return literal_to_text(value)


def _render_expression(
    expr: str, op: str, diagnostics: list[Diagnostic], here: dict[str, Any]
) -> tuple[str, bool]:
    """Translate an IL expression to AB ``CPT`` operator spelling.

    Returns ``(translated, incompatible)``. When ``incompatible`` is True the expression uses a
    construct AB ``CPT`` cannot render (a conditional, comparison, boolean/bitwise op, or an
    unsupported function), so the caller degrades the leaf to an importable ``NOP()`` placeholder
    (the emitted verbatim ``CPT(dest, IF(...))`` would NOT import) and the rung carries an
    ``LLT EMIT`` comment. The original expression rides on the diagnostic for the hand rewrite.
    """
    if not expr:
        return "", False
    translated, issues = translate_cpt_expression(expr)
    if issues:
        diagnostics.append(Diagnostic(
            "REVIEW_REQUIRED", "warning",
            f"{op} expression contains {', '.join(issues)} -- AB CPT computes a numeric value only "
            f"and cannot express this. Emitted as a NOP() placeholder ('LLT EMIT' rung comment); "
            f"rewrite as rung logic (compares + conditional moves). Original expression: {expr!r}.",
            here))
        return translated, True
    if expression_uses_round(expr):
        # ROUND(x) was re-spelled to (TRN(x + 0.5)) -- exact for x >= 0. Record the assumption as a
        # non-blocking note so a possibly-negative argument gets a human's eye (it does NOT degrade).
        diagnostics.append(Diagnostic(
            "TRANSLATION_NOTE", "info",
            f"{op}: Do-More ROUND(x) rendered as (TRN(x + 0.5)) since AB CPT has no ROUND. Exact for "
            f"x >= 0; if the argument can be negative, verify -- round-half-up and "
            f"round-half-away-from-zero differ below zero.",
            here))
    if expression_uses_toreal(expr):
        # TOREAL(x) nested in a larger expression was unwrapped to (x); AB's CPT promotes the operand
        # to REAL by the destination type, so the conversion is exact -- record it as a non-blocking
        # note (verify the CPT destination tag is REAL). A whole-expression TOREAL never reaches here
        # (the caller intercepts it and emits a native MOV instead).
        diagnostics.append(Diagnostic(
            "TRANSLATION_NOTE", "info",
            f"{op}: Do-More TOREAL(x) unwrapped since AB CPT has no TOREAL -- the integer operand is "
            f"promoted to REAL by the destination type. Exact int->REAL; verify the CPT destination "
            f"is a REAL tag.",
            here))
    return translated, False


def instruction_to_text(
    node: dict[str, Any],
    diagnostics: list[Diagnostic],
    loc: dict[str, Any],
    *,
    aoi: "aoi_mod.AoiUsage | None" = None,
    tag_types: dict[str, str] | None = None,
) -> str:
    """Render an instruction leaf, appending diagnostics for unsupported/provisional ops.

    An AOI-backed op (e.g. ``DLT``) renders as an Add-On Instruction call plus a backing tag,
    using the ``aoi`` accumulator and ``tag_types`` (operand-name → IL type) to pick the AOI;
    without an ``aoi`` context it falls through to the registry path (and is flagged).
    """
    op = node["op"]
    operands = node.get("operands", [])
    params = node.get("params", {})
    here = {**loc, "instructionOp": op}

    if node.get("_stringMoveLowered"):
        # A MOV/FLL into a STRING destination (e.g. a Do-More COPY of a quoted string constant into an
        # SS/SL element) has no valid AB form -- MOV/FLL operate on numeric atoms, never a STRING tag.
        # lower_string_move owns the diagnostic + the `[LLT EMIT: STRING MOVE ...]` rung comment; here we
        # just degrade the leaf to an importable NOP() rather than emit invalid `MOVE(...)` text (#48).
        return "NOP()"

    dst = _dangling_dst_operand(node)
    if dst is not None:
        # A DST<n> in a REQUIRED slot means the operator left that box blank in Do-More (DST is the
        # unassigned-slot sentinel, not real memory). There is no value to operate on, so degrade to
        # an importable NOP() + `LLT EMIT` comment rather than emit an undefined reference. Checked
        # BEFORE the byte-cast rule below: a byte cast on a DST sentinel (`DST18:UB3`) is still a
        # dangling reference to unassigned memory -- the cast only describes which bits of it would
        # have been read/written, so it must degrade here rather than let the byte-cast rule lower it
        # to a `BTD(DST18,...)` that references a tag that will never exist (issue #127).
        src_op = (node.get("source") or {}).get("op") or op
        diagnostics.append(Diagnostic(
            "REVIEW_REQUIRED", "warning",
            f"{src_op}: required operand {dst!r} is a Do-More unassigned-slot sentinel -- that box was "
            f"left blank in the source, so there is no value to operate on (DST is not real memory; it "
            f"never appears in MEM_CONFIG). Emitted as a NOP() placeholder ('LLT EMIT' comment) -- fill "
            f"in the intended element or remove this leg (and verify the fail-safe direction, since the "
            f"dropped condition defaulted open).", here))
        return "NOP()"

    bytecast = _bytecast_operand(node)
    if bytecast is not None:
        # A Do-More byte/word cast (D0:UB2, DLV1:B0, Y0:UB) reads or writes a sub-element of an
        # integer (byte n, or a 32-bit dword) -- Do-More's flat memory model. Checked FIRST (before
        # AOI/native rendering). It is expressible in AB as a byte-field extract/insert, so translate
        # it directly (BTD/CLR/MOVE) when the shape maps faithfully; only shapes that can't (a signed
        # byte *read*, a ranged copy, a multi-cast leaf) keep the flagged NOP() + `LLT EMIT` seam.
        src_op = (node.get("source") or {}).get("op") or op
        translated = _bytecast_translation(node)
        if translated is not None:
            text, severity, code, note = translated
            diagnostics.append(Diagnostic(code, severity, f"{src_op}: {note}", here))
            return text
        diagnostics.append(Diagnostic(
            "REVIEW_REQUIRED", "warning",
            f"{src_op}: operand {bytecast!r} uses a Do-More byte/word cast (:UB/:B/:D) in a shape with "
            f"no single faithful AB instruction (a signed-byte read, a ranged copy, or more than one "
            f"cast on the leaf). Emitted as a NOP() placeholder ('LLT EMIT' comment); implement the "
            f"byte access by hand (e.g. a SINT-overlay UDT or AND/shift logic).",
            here))
        return "NOP()"

    if node.get("_danglingCall") is not None:
        # A JSR/CALL whose target routine doesn't exist -- a stale reference to a deleted Do-More code
        # block (`<Virtual>` program), flagged at assembly. Degrade to an importable NOP() + LLT EMIT.
        src_op = (node.get("source") or {}).get("op") or op
        diagnostics.append(Diagnostic(
            "REVIEW_REQUIRED", "warning",
            f"{src_op}: call target {node['_danglingCall']!r} is not an emitted routine -- a stale "
            f"reference to a deleted Do-More code block (a <Virtual> program). Emitted as a NOP() "
            f"placeholder ('LLT EMIT' comment); remove the call or point it at the intended routine.",
            here))
        return "NOP()"

    # AOI-backed op (library-install): emit an AOI call + a per-site backing tag instead of a
    # native instruction. The AB-specific AOI choice is the emitter's (PLAN_MAIN §2).
    if aoi is not None and aoi_mod.is_aoi_op(op):
        operand = operands[0] if operands else None
        otype = tag_types.get(operand["ref"]) if (tag_types and operand and "ref" in operand) else None
        chosen = aoi_mod.select_aoi(op, otype)
        backing = aoi.use(chosen)
        # Differential-family (DLT) dispatches by operand type, so flag unknown/lossy types.
        if op == "DLT":
            if otype is None:
                diagnostics.append(Diagnostic(
                    "REVIEW_REQUIRED", "warning",
                    f"AOI {chosen.name} for op '{op}': operand type unknown, defaulted by kind -- verify.", here))
            elif chosen.name == "DIFF_REAL":
                # Faithful REAL differential (no DINT truncation), but the deadband threshold is a
                # judgement call -- route to the Verify tier so the engineer confirms EPS suits the
                # signal's units/scale rather than leaving it as a must-fix warning.
                diagnostics.append(Diagnostic(
                    "REVIEW_REQUIRED", "info",
                    f"AOI DIFF_REAL: '{otype}' change is detected past an EPS deadband (default "
                    f"{aoi_mod.DIFF_REAL_DEFAULT_EPS:g}) rather than DIFF_NUM's DINT cast (which would "
                    f"drop the fraction) or an exact compare (which would fire on float noise). Confirm "
                    f"the EPS threshold suits this signal -- it is editable on the box ({backing}.EPS).",
                    here, requires_human_review=True))
        if chosen.out_member is not None:
            # Contact-style AOI: one operand, then its OUT member tested as a contact in series.
            # EnableOut is NOT usable as the rung condition (only means "executed OK") -- see AoiDef.
            arg = operand_to_text(operand) if operand else "?"
            return f"{chosen.name}({backing},{arg})XIC({backing}.{chosen.out_member})"
        # Output-style AOI (e.g. SCALE): the AOI writes a destination operand; pass ALL operands in
        # call order (a destination among them), no trailing result contact.
        args = [operand_to_text(o) for o in operands]
        return f"{chosen.name}({backing}{',' if args else ''}{','.join(args)})"

    if op == opcodes.OPAQUE_OP:
        # Opaque-tail op: a source instruction with no IL-primitive form (PLAN_MAIN §2). The
        # original mnemonic lives in `source`; flag it by that name. It renders as an importable
        # NOP() placeholder (graceful degradation) so the component still imports into Studio --
        # the rung carries a `[LLT EMIT: UNSUPPORTED TRANSLATION <op>]` comment (added by the L5X
        # emitter, l5x._emit_rung) so the engineer can CTRL+F "LLT EMIT" and hand-implement it.
        src_op = (node.get("source") or {}).get("op", "?")
        guidance = _OPAQUE_GUIDANCE.get(src_op)
        detail = f" {guidance}" if guidance else " implement it by hand -- no neutral text emitted."
        if src_op in _STRING_COMPOSE_STRUCTURAL:
            # Printf-to-string formatting op -- finishable by hand (CONCAT + numeric-to-string), not a
            # failed translation, so never a hard error. The lower_string_compose pass normally owns
            # the diagnostic + the `[LLT EMIT: STRING COMPOSE ...]` rung comment (it sets
            # `_stringComposeLowered`); this is the fallback when a rung is rendered without that pass
            # -- still a non-error MANUAL_STRING_COMPOSE, never a silent drop.
            if not node.get("_stringComposeLowered"):
                fmt = _string_compose_format(node)
                diagnostics.append(Diagnostic(
                    "MANUAL_STRING_COMPOSE", "warning",
                    f"Source instruction '{src_op}' formats a printf-style string into a Do-More "
                    f"String; AB has no single-instruction equivalent. Emitted as a NOP() placeholder "
                    f"('LLT EMIT' rung comment); compose it by hand (CONCAT + numeric-to-string, or "
                    f"AWA for a port write). Original format: {fmt!r}.",
                    here))
            return "NOP()"
        if src_op in _ENGINEER_OWNED_STRUCTURAL:
            # Engineer-owned config, not a failed translation -- see _ENGINEER_OWNED_STRUCTURAL.
            diagnostics.append(
                Diagnostic(
                    "ENGINEER_OWNED_CONFIG",
                    "warning",
                    f"Source instruction '{src_op}' is engineer-owned comms configuration, not a "
                    f"failed translation; emitted as a NOP() placeholder ('LLT EMIT' rung comment);"
                    f"{detail}",
                    here,
                )
            )
            return "NOP()"
        diagnostics.append(
            Diagnostic(
                "UNSUPPORTED_INSTRUCTION",
                "error",
                f"Source instruction '{src_op}' has no clean Allen-Bradley lowering (carried as an "
                f"opaque IL op); emitted as a NOP() placeholder ('LLT EMIT' rung comment);{detail}",
                here,
            )
        )
        return "NOP()"

    spec = opcodes.lookup(op)
    if spec is None:
        diagnostics.append(
            Diagnostic(
                "UNSUPPORTED_INSTRUCTION",
                "error",
                f"Op '{op}' is not in the opcode registry (v{opcodes.REGISTRY_VERSION}); "
                f"emitted operands verbatim -- verify the neutral text by hand.",
                here,
            )
        )
        args = [operand_to_text(o) for o in operands]
        return f"{op}({','.join(args)})"

    render = spec["render"]
    if render in ("timer", "counter"):
        backing = operand_to_text(operands[0]) if operands else "?"
        # preset/accum are canonical params: a number (TMR T0 5000 -> 5000) or, for a register
        # preset (CNTDN CT0 D0 -> "D0"), the tag-name string. _num renders both.
        args = [backing, _num(params.get("preset", 0)), _num(params.get("accum", 0))]
    elif render == "expr_dest":
        dest = operand_to_text(operands[0]) if operands else "?"
        toreal_src = standalone_toreal_operand(node.get("expression", "") or "")
        if toreal_src is not None:
            # Whole-expression Do-More TOREAL(<operand>) (int->real of a bare element/literal). AB has
            # no explicit "to real", but a MOV into a REAL destination auto-converts -- so emit a native
            # MOV(<operand>, <dest>) rather than a CPT (escalation ladder: direct instruction first).
            # A non-blocking info note records the coercion; verify the destination tag is REAL.
            diagnostics.append(Diagnostic(
                "TRANSLATION_NOTE", "info",
                f"{op}: Do-More TOREAL({toreal_src}) rendered as a native MOV into {dest} -- AB "
                f"auto-converts int->REAL on a MOV to a REAL destination. Verify {dest} is a REAL tag.",
                here))
            return f"{opcodes.emit_token('MOV')}({toreal_src},{dest})"
        expr_text, incompatible = _render_expression(node.get("expression", ""), op, diagnostics, here)
        if incompatible:
            return "NOP()"  # CPT can't render it; degrade to importable placeholder + LLT EMIT comment
        args = [dest, expr_text]
    elif render == "expr_only":
        expr_text, incompatible = _render_expression(node.get("expression", ""), op, diagnostics, here)
        if incompatible:
            return "NOP()"
        args = [expr_text]
    elif render == "call":
        target = node.get("callTarget")
        if target is None:
            diagnostics.append(
                Diagnostic("EMIT_INCOMPLETE", "error", f"{op} call has no callTarget.", here)
            )
            target = "?"
        # An unchecked optional call parameter is written as a DST<n> sentinel; AB simply doesn't
        # pass that argument, so drop it.
        call_operands = _strip_dst_operands(operands)
        if op == "JSR" and call_operands and not any("ref" in o for o in call_operands):
            # All-literal leftovers are Do-More box metadata, not arguments. Every CALL in the LB
            # Standard export reads `CALL <blk> 0x1 DST511 "3" "3"` -- the SAME trailing literals for
            # 9 calls across 4 different code blocks, none of which ($LGCMOD) declares a parameter.
            # Real arguments would be element references and would vary per call site. Passing them
            # anyway emits JSR(Derating,3,1,3,3) into a routine with no SBR, which Logix rejects on
            # verify -- so emit the plain dispatch and flag the drop rather than guess.
            dropped = ", ".join(operand_to_text(o) for o in call_operands)
            diagnostics.append(Diagnostic(
                "REVIEW_REQUIRED", "warning",
                f"{(node.get('source') or {}).get('op') or op} {target}: emitted as a plain dispatch "
                f"JSR({target},0). The source call carried only literal box metadata ({dropped}) and "
                f"the target code block declares no parameters, so nothing was passed. If this call "
                f"was meant to pass arguments, add them as JSR Input parameters and give {target} a "
                f"matching SBR.", here))
            call_operands = []
        param_texts = [operand_to_text(o) for o in call_operands]
        if op == "JSR":
            # AB JSR syntax is JSR(Routine, NumInputParams, [inputs...], [returns...]) -- the
            # parameter COUNT is mandatory (confirmed against a real Studio dispatch export:
            # `JSR(A0_FIRST_SCAN,0)`). A dispatch JSR (RUN/CALL with no args) -> JSR(Routine,0);
            # any operands ride as input parameters, their count leading (the input/return split
            # is the CALL->JSR review caveat raised at parse time).
            args = [target, str(len(param_texts)), *param_texts]
        else:
            args = [target, *param_texts]
    else:  # "operands"
        args = [operand_to_text(o) for o in operands]

    # Most ops serialize under their own name; a few use a different v36 neutral-text token
    # (opcodes._EMIT_TOKEN, e.g. MOV -> MOVE, NEQ -> NE).
    return f"{opcodes.emit_token(op)}({','.join(args)})"


# A Do-More byte/word cast suffix on an operand ref: :UB / :UBn / :B / :Bn (un/signed byte) or :D
# (double). A numeric bit cast (D0:5) was already decomposed to the `bit` field at parse time, so it
# never reaches here; and this pattern deliberately does NOT match an AB system tag like `S:FS`.
_BYTECAST_RE = re.compile(r":(?:U?B\d*|D)$")

# A Do-More ``DST<n>`` pseudo-element (``DST50``, ``DST511``). ``DST`` is NOT a real memory type --
# it never appears in an export's MEM_CONFIG (verified against the LB Standard export, whose blocks
# are X/Y/WX/WY/C/V/N/D/R/T/CT/SS/SL/PL/DLX/DLY/DLC/DLV/MI/MC/MIR/MHR/RX/RY/ResStep/TC/Stage/
# IndStep/MSG -- no DST). It is the **unassigned-slot sentinel** for a numeric operand slot, the
# analog of ``ST1023`` for a bit slot (docs/format-scoping.md).
#
# It does NOT by itself mean "broken logic". What matters is WHICH slot it sits in:
#   * an OPTIONAL slot (a CALL's unset parameter, MRX's unset exception-code output) -- the slot is
#     simply unchecked. The faithful translation is to OMIT that argument, not to drop the
#     instruction. Treating these as broken silently deleted every JSR in a real program.
#   * a REQUIRED input (a compare contact's value, e.g. ``STRE DST50 2``) -- the operator left the
#     box blank, so the source really is incomplete and there is nothing to compare. That keeps the
#     flagged NOP().
# (Disabled *preset* slots are already neutralized at parse; this catches the rest.)
_DST_REF_RE = re.compile(r"^DST\d+$")

# Ops whose DST operands sit in optional slots. ``JSR`` (from Do-More ``CALL``) carries unset call
# parameters; the opaque op already degrades to NOP() on its own (unsupported), so re-flagging its
# DST would double-report the same rung.
_DST_OPTIONAL_SLOT_OPS = frozenset({"JSR", opcodes.OPAQUE_OP})


def _strip_dst_operands(operands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop unassigned-slot ``DST<n>`` sentinels from an operand list (see :data:`_DST_REF_RE`).

    An unchecked optional slot has no AB counterpart -- the argument is simply not passed -- so a
    Do-More ``CALL Derating 0x1 DST511 "3" "3"`` renders as ``JSR(Derating,0)``.
    """
    return [o for o in operands
            if not (isinstance(o.get("ref"), str) and _DST_REF_RE.match(o["ref"]))]


def _bytecast_operand(node: dict[str, Any]) -> str | None:
    """The first operand ref carrying a Do-More byte/word cast (``D0:UB2``, ``DLV1:B0``, ``Y0:UB``),
    else None. Such a ref reads/writes a sub-element (byte n or a 32-bit dword) of the parent
    integer; :func:`_bytecast_translation` lowers the faithful shapes to native AB."""
    for op in node.get("operands", []):
        ref = op.get("ref")
        if isinstance(ref, str) and _BYTECAST_RE.search(ref):
            return ref
    return None


class _ByteCast(NamedTuple):
    """A decoded Do-More byte/word cast suffix (the part after the ``:``)."""

    parent: str   # the base element, cast stripped (``D0:UB2`` -> ``D0``)
    kind: str     # "byte" (8-bit, ``:UB``/``:B``) or "dword" (32-bit, ``:D``)
    index: int    # byte index (0 for a dword, ``:UB``, ``:B``; n for ``:UBn``/``:Bn``)
    signed: bool  # signed byte (``:B``) vs unsigned (``:UB``); a dword is signed


def _parse_bytecast(ref: str) -> _ByteCast | None:
    """Decode a byte/word cast ref (``D0:UB2`` -> byte 2 unsigned of ``D0``), else None."""
    m = _BYTECAST_RE.search(ref)
    if m is None:
        return None
    parent = ref[: m.start()]
    tok = ref[m.start() + 1 :]  # the cast token, without the leading ':'
    if not parent:
        return None
    if tok == "D":
        return _ByteCast(parent, "dword", 0, True)
    signed = not tok.startswith("U")  # ``B`` = signed, ``UB`` = unsigned
    digits = tok[1:] if signed else tok[2:]  # the index digits after ``B`` / ``UB``
    return _ByteCast(parent, "byte", int(digits) if digits else 0, signed)


# Move-family ops whose operands are ``[source, dest]`` (+ an optional length): a byte/word cast on
# the source is a *read* (extract the sub-element), on the dest a *write* (deposit it). These are
# exactly what Do-More INIT/COPY decompose into, so lowering the cast here covers all of them.
_BYTECAST_MOVE_OPS = frozenset({"MOV", "COP", "CPS", "FLL"})


def _bytecast_translation(node: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Lower a single byte/word cast on a move-family leaf to native AB neutral text.

    Returns ``(text, severity, code, note)`` for a faithful mapping, else None (the caller keeps the
    flagged ``NOP()`` seam). The cast is a bit field of the parent integer:

    * **write** (cast on the dest) -> ``BTD(source, 0, parent, index*8, 8)`` deposits the low byte of
      the source into byte ``index`` of the parent, leaving the parent's other bytes untouched;
    * **read** (unsigned cast on the source) -> ``CLR(dest)BTD(parent, index*8, dest, 0, 8)`` extracts
      byte ``index`` into the (zero-extended) dest;
    * **dword** (``:D``, either side) -> a full 32-bit ``MOVE`` (verify the parent is a DINT).
    * **byte-pack** (a byte cast on BOTH source and dest, ``MOV(DLV0:B0, D100:UB3)``) -> one
      ``BTD(srcParent, i*8, dstParent, j*8, 8)`` moving byte ``i`` of the source into byte ``j`` of
      the dest. This is the LB Standard's byte-packing ``INIT`` form (each row a disabled-sentinel
      range that the parser reduces to a single-element ``MOV`` of two byte casts).

    A *signed*-byte read needs sign extension (no single faithful instruction) -> None (seam); a
    ``:D`` dword dual-cast or mismatched widths likewise stays a seam."""
    op = node.get("op")
    if op not in _BYTECAST_MOVE_OPS:
        return None
    operands = node.get("operands", [])
    if len(operands) < 2:
        return None
    cast_idxs = [
        i for i, o in enumerate(operands)
        if isinstance(o.get("ref"), str) and _BYTECAST_RE.search(o["ref"])
    ]
    # A ranged FLL/COP/CPS (a length operand present and != 1) would need a per-element byte loop,
    # not one instruction -- keep it a seam. A single-element (length 1) copy is a plain move.
    if len(operands) >= 3:
        length = operands[2]
        if not ("literal" in length and length["literal"] == 1):
            return None
    mov, btd, clr = opcodes.emit_token("MOV"), opcodes.emit_token("BTD"), opcodes.emit_token("CLR")

    if cast_idxs == [0, 1]:
        # Byte-pack: a cast on BOTH source and dest -> read byte i of the source parent and write it
        # into byte j of the dest parent, in one BTD. This is the Do-More byte-packing INIT form
        # (`MOV(DLV0:B0, D100:UB3)` -> `BTD(DLV0,0,D100,24,8)`): BTD copies 8 bits from source bit
        # i*8 into dest bits j*8..j*8+7, leaving the dest's other bytes untouched. Only the byte<->byte
        # case (both 8-bit); a :D dword dual-cast or mismatched widths keeps the flagged NOP() seam.
        src_cast = _parse_bytecast(operands[0]["ref"])
        dst_cast = _parse_bytecast(operands[1]["ref"])
        if src_cast is None or dst_cast is None:
            return None
        if src_cast.kind != "byte" or dst_cast.kind != "byte":
            return None
        src_bit, dst_bit = src_cast.index * 8, dst_cast.index * 8
        text = f"{btd}({src_cast.parent},{src_bit},{dst_cast.parent},{dst_bit},8)"
        note = (f"operands {operands[0]['ref']!r} -> {operands[1]['ref']!r} pack byte {src_cast.index} "
                f"of {src_cast.parent} into byte {dst_cast.index} of {dst_cast.parent}; rendered as "
                f"{btd}(...) copying bits {src_bit}..{src_bit + 7} into bits {dst_bit}..{dst_bit + 7} "
                f"(the dest's other bytes preserved).")
        return text, "info", "TRANSLATION_NOTE", note

    if len(cast_idxs) != 1 or cast_idxs[0] > 1:  # need exactly one cast, on source(0) or dest(1)
        return None
    ci = cast_idxs[0]
    cast = _parse_bytecast(operands[ci]["ref"])
    if cast is None:
        return None
    other = operand_to_text(operands[1 - ci])  # the non-cast operand (source for a write, dest for a read)
    is_write = ci == 1
    ref = operands[ci]["ref"]

    if cast.kind == "dword":
        # A 32-bit reinterpretation: a plain full-width MOVE. Faithful only if the parent maps to a
        # 32-bit DINT (a 16-bit element's dword spans two words) -- so flag it for a width check.
        text = f"{mov}({other},{cast.parent})" if is_write else f"{mov}({cast.parent},{other})"
        note = (f"operand {ref!r} is a Do-More :D (32-bit dword) cast, rendered as a full-width "
                f"{mov}; verify {cast.parent} maps to a 32-bit DINT tag (a 16-bit element's dword "
                f"spans two consecutive words).")
        return text, "warning", "REVIEW_REQUIRED", note

    bit = cast.index * 8
    if is_write:
        # Deposit the low byte of the source into byte `index` of the parent (BTD leaves the parent's
        # other bytes untouched -- exact masked write). Sign is irrelevant when writing 8 bits.
        text = f"{btd}({other},0,{cast.parent},{bit},8)"
        note = (f"operand {ref!r} writes byte {cast.index} of {cast.parent}; rendered as "
                f"{btd}(...,{bit},8) depositing the low byte into bits {bit}..{bit + 7} while "
                f"preserving {cast.parent}'s other bytes.")
        return text, "info", "TRANSLATION_NOTE", note

    # Read side. A signed byte needs sign extension (multi-instruction) -> keep the seam.
    if cast.signed:
        return None
    # Unsigned byte read: zero the dest, then distribute byte `index` into its low byte.
    text = f"{clr}({other}){btd}({cast.parent},{bit},{other},0,8)"
    note = (f"operand {ref!r} reads unsigned byte {cast.index} of {cast.parent}; rendered as "
            f"{clr}({other}) then {btd} extracting bits {bit}..{bit + 7} into the low byte of "
            f"{other} (zero-extended).")
    return text, "info", "TRANSLATION_NOTE", note


# The first double-quoted run in a STRPRINT line is its printf format ("Temp is %d").
_STRPRINT_FORMAT_RE = re.compile(r'"([^"]*)"')


def _string_compose_format(node: dict[str, Any]) -> str:
    """The printf format string of a STRPRINT leaf (from ``source.raw``), else the raw/op."""
    raw = (node.get("source") or {}).get("raw", "") or (node.get("source") or {}).get("op", "?")
    m = _STRPRINT_FORMAT_RE.search(raw)
    return m.group(1) if m else raw


def _dangling_dst_operand(node: dict[str, Any]) -> str | None:
    """The first ``DST<n>`` sentinel sitting in a REQUIRED operand slot, else None.

    Only these are untranslatable: the operator left a mandatory box blank (e.g. ``STRE DST50 2``),
    so there is no value to compare and the leaf degrades to a flagged NOP(). A sentinel in an
    optional slot is not reported here -- it is stripped by :func:`_strip_dst_operands` and the
    instruction renders normally (see :data:`_DST_OPTIONAL_SLOT_OPS`).

    A byte/word cast on the sentinel (``DST18:UB3``) is still a dangling reference to unassigned
    memory -- the cast just describes which bits of it would have been read/written, not a real
    tag. Strip the cast before checking so this catches ``DST18:UB3`` the same as bare ``DST18``
    (issue #127): checked *before* :func:`_bytecast_operand` in :func:`instruction_to_text` so a
    byte-cast DST sentinel degrades to this flagged NOP() rather than the byte-cast lowering
    emitting a dangling ``BTD(DST18,...)`` reference to a tag that will never exist.
    """
    if node.get("op") in _DST_OPTIONAL_SLOT_OPS:
        return None
    for op in node.get("operands", []):
        ref = op.get("ref")
        if not isinstance(ref, str):
            continue
        base = ref
        cast = _parse_bytecast(ref)
        if cast is not None:
            base = cast.parent
        if _DST_REF_RE.match(base):
            return ref
    return None


def degraded_marker_op(node: dict[str, Any]) -> str | None:
    """Source mnemonic for the ``LLT EMIT`` marker if this instruction leaf cannot emit importable
    neutral text -- an opaque (``SRCOP``) op, or an expression-bearing op (CPT/CMP) whose
    expression uses a construct AB ``CPT`` can't render. Such leaves render as ``NOP()`` (see
    :func:`instruction_to_text`); every other leaf returns ``None``. Single source of truth shared
    by the renderer and the L5X emitter so the NOP placeholders and the comments never diverge."""
    if node.get("kind") != "instruction":
        return None
    op = node.get("op")
    if op == opcodes.OPAQUE_OP:
        src_op = (node.get("source") or {}).get("op", "?")
        # A STRPRINT lowered by lower_string_compose already carries a richer `[LLT EMIT: STRING
        # COMPOSE ...]` rung comment (with the format), so it does NOT also want the generic
        # `UNSUPPORTED TRANSLATION` marker -- suppress the duplicate.
        if src_op in _STRING_COMPOSE_STRUCTURAL and node.get("_stringComposeLowered"):
            return None
        return src_op
    if _dangling_dst_operand(node) is not None:  # DST<n> (bare or byte-cast) dangling ref -> NOP
        # Checked BEFORE the byte-cast rule below: a byte-cast DST sentinel (`DST18:UB3`) would
        # otherwise look like a successfully-lowered cast to `_bytecast_translation` (it mechanically
        # lowers the cast without knowing the base is unassigned memory) and slip past this marker
        # with no `LLT EMIT` comment, even though `instruction_to_text` renders it as a NOP (#127).
        return (node.get("source") or {}).get("op") or op
    if _bytecast_operand(node) is not None and _bytecast_translation(node) is None:
        # byte/word cast in a shape with no faithful AB form -> NOP (a translatable cast lowers to
        # native BTD/CLR/MOVE and is NOT degraded, so it gets no `LLT EMIT` marker)
        return (node.get("source") or {}).get("op") or op
    if node.get("_danglingCall") is not None:  # JSR/CALL to a deleted routine -> NOP
        return (node.get("source") or {}).get("op") or op
    spec = opcodes.lookup(op)
    if spec is not None and spec["render"] in ("expr_dest", "expr_only"):
        _, issues = translate_cpt_expression(node.get("expression", "") or "")
        if issues:
            return (node.get("source") or {}).get("op") or op
    return None


def degraded_source_ops(node: dict[str, Any] | None) -> list[str]:
    """Marker ops for every leaf under ``node`` that degrades to ``NOP()`` (opaque or
    CPT-incompatible), in first-seen order, deduped -- one ``[LLT EMIT: ...]`` rung comment each."""
    seen: list[str] = []

    def walk(n: dict[str, Any]) -> None:
        marker = degraded_marker_op(n)
        if marker is not None and marker not in seen:
            seen.append(marker)
        kind = n.get("kind")
        if kind == "series":
            for c in n.get("children", []):
                walk(c)
        elif kind == "branch":
            for p in n.get("paths", []):
                walk(p)

    if node is not None:
        walk(node)
    return seen


def node_to_text(
    node: dict[str, Any],
    diagnostics: list[Diagnostic],
    loc: dict[str, Any],
    *,
    aoi: "aoi_mod.AoiUsage | None" = None,
    tag_types: dict[str, str] | None = None,
) -> str:
    """Render any node (series/branch/instruction) to neutral text."""
    kind = node["kind"]
    if kind == "instruction":
        return instruction_to_text(node, diagnostics, loc, aoi=aoi, tag_types=tag_types)
    if kind == "series":
        return "".join(node_to_text(c, diagnostics, loc, aoi=aoi, tag_types=tag_types)
                       for c in node.get("children", []))
    if kind == "branch":
        legs = [node_to_text(p, diagnostics, loc, aoi=aoi, tag_types=tag_types) for p in node["paths"]]
        return "[" + ",".join(legs) + "]"
    raise ValueError(f"unknown node kind: {kind!r}")


def rung_to_text(
    rung: dict[str, Any],
    diagnostics: list[Diagnostic] | None = None,
    *,
    loc: dict[str, Any] | None = None,
    aoi: "aoi_mod.AoiUsage | None" = None,
    tag_types: dict[str, str] | None = None,
) -> str:
    """Render a rung to neutral text, terminated by ``;``.

    A rung with no ``network`` (comment-only / empty) renders as ``NOP();`` — the
    canonical form Studio 5000 itself exports for an empty rung (confirmed in the
    reference exports), not a bare ``;``. ``diagnostics`` is appended to in place if
    provided. ``aoi``/``tag_types`` enable AOI-backed ops (see :func:`instruction_to_text`).
    """
    if diagnostics is None:
        diagnostics = []
    loc = dict(loc or {})
    network = rung.get("network")
    if network is None:
        return "NOP();"
    return node_to_text(network, diagnostics, loc, aoi=aoi, tag_types=tag_types) + ";"
