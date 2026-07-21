"""Canonical opcode registry (first real cut).

Maps each canonical Allen-Bradley mnemonic (LLT's neutral opcode vocabulary) to its
instruction ``category`` and a neutral-text **render strategy**. Transcribed from
``docs/L5X-docs/L5X_MAIN.md`` §5.1 (the Logix "Relay Ladder Instructions" neutral-text
table). This seeds the cross-cutting opcode-registry workstream (``planning/PLAN_MAIN.md``
§6); the in-force vocabulary is pinned by ``metadata.registryVersion``.

An op absent from this registry is **unsupported** — the emitter raises an
``UNSUPPORTED_INSTRUCTION`` diagnostic rather than silently guessing.

Render strategies (how the neutral-text argument list is built):

* ``operands``  — ``OP(a0,a1,...)`` from ``operands[]`` in order (the default).
* ``timer``     — ``OP(backing_tag, preset, accum)`` (TON/TOF/RTO); preset/accum come
  from ``params``, **not** the operand list.
* ``counter``   — ``OP(backing_tag, preset, accum)`` (CTU/CTD).
* ``expr_dest`` — ``OP(operands[0], expression)`` (CPT).
* ``expr_only`` — ``OP(expression)`` (CMP).
* ``call``      — ``OP(callTarget, a0, a1, ...)`` (JSR/SBR/JXR/FOR/SFP/SFR): the routine
  name rides on ``callTarget``, kept off ``op``.
"""

from __future__ import annotations

REGISTRY_VERSION = "0.1.0"

# The IL opcode axis is a Reduced Instruction Set (RIS): a bounded set of atomic primitives,
# each of which MUST be renderable on every target (PLAN_MAIN.md §2). Source instructions with
# no IL-primitive form are NOT minted as new atomics — they are carried by this single sentinel
# op, with the original mnemonic kept in the leaf's `source` provenance (off the `op` token axis,
# so the corpus vocabulary and the atomic count stay bounded regardless of how many vendors are
# added). It is deliberately NOT in `_OPS`, so any emitter flags it UNSUPPORTED_INSTRUCTION.
OPAQUE_OP = "SRCOP"

# op -> (category, render strategy). Categories use the schema's instruction.category
# enum: contact|coil|timer|counter|compare|math|move|jump|call|special.
_OPS: dict[str, tuple[str, str]] = {
    # --- contacts / coils ---
    "XIC": ("contact", "operands"),
    "XIO": ("contact", "operands"),
    "OTE": ("coil", "operands"),
    "OTL": ("coil", "operands"),
    "OTU": ("coil", "operands"),
    "ONS": ("special", "operands"),
    "OSR": ("special", "operands"),
    "OSF": ("special", "operands"),
    # --- timers / counters ---
    "TON": ("timer", "timer"),
    "TOF": ("timer", "timer"),
    "RTO": ("timer", "timer"),
    "CTU": ("counter", "counter"),
    "CTD": ("counter", "counter"),
    "RES": ("special", "operands"),
    # --- program control ---
    "JMP": ("jump", "operands"),
    "LBL": ("jump", "operands"),
    "JSR": ("call", "call"),
    "SBR": ("call", "call"),
    "RET": ("call", "operands"),
    "JXR": ("call", "call"),
    "FOR": ("call", "call"),
    "SFP": ("call", "call"),
    "SFR": ("call", "call"),
    "TND": ("special", "operands"),
    "MCR": ("special", "operands"),
    "AFI": ("special", "operands"),
    "NOP": ("special", "operands"),
    "UID": ("special", "operands"),
    "UIE": ("special", "operands"),
    "EVENT": ("special", "operands"),
    "IOT": ("special", "operands"),
    "EOT": ("special", "operands"),
    # MSG (Message): backs the Do-More DEVREAD/DEVWRITE -> MSG scaffold (emit/device_msg.py). Renders
    # MSG(<MESSAGE tag>); the message's config is engineer-owned (see the scaffold rung comment).
    "MSG": ("special", "operands"),
    # --- math ---
    "ADD": ("math", "operands"),
    "SUB": ("math", "operands"),
    "MUL": ("math", "operands"),
    "DIV": ("math", "operands"),
    "MOD": ("math", "operands"),
    "NEG": ("math", "operands"),
    "ABS": ("math", "operands"),
    "CLR": ("math", "operands"),
    "SQR": ("math", "operands"),
    "CPT": ("math", "expr_dest"),
    "XPY": ("math", "operands"),
    "AND": ("math", "operands"),
    "OR": ("math", "operands"),
    "XOR": ("math", "operands"),
    "NOT": ("math", "operands"),
    "SWPB": ("math", "operands"),
    # BCD <-> integer/real conversion. v36 caveat: these may export as `BCD_TO`/`TO_BCD` on
    # Studio 5000 v36 -- confirm the token spelling against a real export (parser flags this).
    "FRD": ("math", "operands"),
    "TOD": ("math", "operands"),
    # --- move ---
    "MOV": ("move", "operands"),
    "MVM": ("move", "operands"),
    "BTD": ("move", "operands"),
    "COP": ("move", "operands"),
    "CPS": ("move", "operands"),
    "FLL": ("move", "operands"),
    # --- compare ---
    "CMP": ("compare", "expr_only"),
    "EQU": ("compare", "operands"),
    "NEQ": ("compare", "operands"),
    "LES": ("compare", "operands"),
    "LEQ": ("compare", "operands"),
    "GRT": ("compare", "operands"),
    "GEQ": ("compare", "operands"),
    "LIM": ("compare", "operands"),
    "MEQ": ("compare", "operands"),
    # --- FIFO/LIFO queue (operand order from the v36.00 SANDBOX export). The emitter's §6.2
    # lowering (emit/queues.py) produces these from Do-More FIFOLOAD/LIFOLOAD/... with the operand
    # reorder + a CONTROL control tag + a Length from the block's .dmd dimensions. ---
    "FFL": ("special", "operands"),  # FFL(source, array[0], control, length, position)
    "FFU": ("special", "operands"),  # FFU(array[0], dest, control, length, position)
    "LFL": ("special", "operands"),  # LFL(source, array[0], control, length, position)
    "LFU": ("special", "operands"),  # LFU(array[0], dest, control, length, position)
    # NOTE: shift/sequencer targets (BSL/BSR/SQO/SQI) land with their lowering (SR/DRUM), so the
    # parser's direct-op guarantee stays honest until the Do-More sources are reclassified.
}

# Emit-token overrides: several instructions serialize in Studio 5000 v36 L5X neutral text under a
# token that differs from the canonical ladder mnemonic. All confirmed against the real v36.00
# SANDBOX export (`src-examples/l5x/SANDBOX_main_program_RLL.L5X`, rungs 2 + 19): move -> `MOVE`,
# and the whole compare family shortens (EQU->EQ, NEQ->NE, LES->LT, LEQ->LE, GRT->GT, GEQ->GE),
# while limit-test lengthens (LIM->LIMIT). The IL keeps the canonical op (so the corpus token axis
# and the parser stay undisturbed); only the emitted neutral text uses the v36 token.
# NOTE: `MEQ` (masked equal) was NOT in the sample -- its v36 token is unconfirmed and left as-is.
_EMIT_TOKEN: dict[str, str] = {
    "MOV": "MOVE",
    "EQU": "EQ",
    "NEQ": "NE",
    "LES": "LT",
    "LEQ": "LE",
    "GRT": "GT",
    "GEQ": "GE",
    "LIM": "LIMIT",
}


def emit_token(op: str) -> str:
    """The token an op serializes as in AB L5X neutral text (usually the op itself)."""
    return _EMIT_TOKEN.get(op, op)


def lookup(op: str) -> dict[str, str] | None:
    """Return ``{'category', 'render'}`` for ``op``, or ``None`` if unsupported."""
    entry = _OPS.get(op)
    if entry is None:
        return None
    return {"category": entry[0], "render": entry[1]}


def is_supported(op: str) -> bool:
    return op in _OPS
