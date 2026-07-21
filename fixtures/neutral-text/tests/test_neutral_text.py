"""Unit tests for the IL -> Allen-Bradley neutral-text serializer."""

from __future__ import annotations

from llt.emit.neutral_text import (
    Diagnostic,
    instruction_to_text,
    node_to_text,
    operand_to_text,
    rung_to_text,
)


def test_operand_ref_plain():
    assert operand_to_text({"ref": "Motor_Run"}) == "Motor_Run"


def test_operand_bit_access():
    assert operand_to_text({"ref": "ACCUMULATOR", "bit": 0}) == "ACCUMULATOR.0"


def test_operand_path_member_and_index():
    op = {"ref": "MyUDT", "path": [{"member": "Bank"}, {"index": 2}, {"member": "Cmd"}]}
    assert operand_to_text(op) == "MyUDT.Bank[2].Cmd"


def test_operand_variable_index():
    assert operand_to_text({"ref": "Arr", "path": [{"index": {"ref": "i"}}]}) == "Arr[i]"


def test_operand_member_then_bit():
    op = {"ref": "Run_Timer", "path": [{"member": "DN"}], "bit": 0}
    assert operand_to_text(op) == "Run_Timer.DN.0"


def test_operand_literals():
    assert operand_to_text({"literal": 1}) == "1"
    assert operand_to_text({"literal": True}) == "1"
    assert operand_to_text({"literal": False}) == "0"


def test_instruction_simple():
    diags: list[Diagnostic] = []
    node = {"kind": "instruction", "op": "XIC", "operands": [{"ref": "ALWAYS_ON"}]}
    assert instruction_to_text(node, diags, {}) == "XIC(ALWAYS_ON)"
    assert diags == []


def test_instruction_timer_pulls_preset_accum_from_params():
    diags: list[Diagnostic] = []
    node = {
        "kind": "instruction", "op": "TON",
        "operands": [{"ref": "Run_Timer"}],
        "params": {"preset": 5000, "timebase": 1},
    }
    # accum defaults to 0; preset comes from params, NOT the operand list.
    assert instruction_to_text(node, diags, {}) == "TON(Run_Timer,5000,0)"


def test_instruction_counter_register_preset_string_param():
    # A register-valued preset (Do-More `CNTDN CT0 D0`) is carried as a string on params.preset;
    # the serializer renders the tag name as the preset argument, not a fallback 0.
    diags: list[Diagnostic] = []
    node = {
        "kind": "instruction", "op": "CTD",
        "operands": [{"ref": "CT0"}],
        "params": {"preset": "D0"},
    }
    assert instruction_to_text(node, diags, {}) == "CTD(CT0,D0,0)"


def test_instruction_unsupported_op_flags_diagnostic():
    diags: list[Diagnostic] = []
    node = {"kind": "instruction", "op": "FAKEOP", "operands": [{"ref": "X"}]}
    text = instruction_to_text(node, diags, {})
    assert text == "FAKEOP(X)"  # best-effort
    assert len(diags) == 1 and diags[0].code == "UNSUPPORTED_INSTRUCTION"
    assert diags[0].severity == "error"


def test_branch_compact():
    diags: list[Diagnostic] = []
    node = {
        "kind": "branch",
        "paths": [
            {"kind": "instruction", "op": "XIC", "operands": [{"ref": "A"}]},
            {"kind": "instruction", "op": "XIC", "operands": [{"ref": "B"}]},
        ],
    }
    assert node_to_text(node, diags, {}) == "[XIC(A),XIC(B)]"


def test_branch_empty_bypass_leg():
    """An empty series leg renders as the leading-comma bypass form [,leg]."""
    diags: list[Diagnostic] = []
    node = {
        "kind": "branch",
        "paths": [
            {"kind": "series", "children": []},  # empty bypass leg
            {"kind": "instruction", "op": "XIC", "operands": [{"ref": "B"}]},
        ],
    }
    assert node_to_text(node, diags, {}) == "[,XIC(B)]"


def test_rung_seal_in():
    diags: list[Diagnostic] = []
    rung = {
        "number": 0,
        "network": {
            "kind": "series",
            "children": [
                {"kind": "branch", "paths": [
                    {"kind": "instruction", "op": "XIC", "operands": [{"ref": "Start_PB"}]},
                    {"kind": "instruction", "op": "XIC", "operands": [{"ref": "Motor_Run"}]},
                ]},
                {"kind": "instruction", "op": "XIO", "operands": [{"ref": "Stop_PB"}]},
                {"kind": "instruction", "op": "OTE", "operands": [{"ref": "Motor_Run"}]},
            ],
        },
    }
    assert rung_to_text(rung, diags) == "[XIC(Start_PB),XIC(Motor_Run)]XIO(Stop_PB)OTE(Motor_Run);"


def test_rung_empty_when_no_network():
    # Studio 5000 exports an empty rung as NOP();, not a bare ;
    assert rung_to_text({"number": 3}) == "NOP();"


# --- CPT expression rendering (Do-More MATH -> AB CPT operator spelling) ---

def _cpt_node(expr: str) -> dict:
    return {"kind": "instruction", "op": "CPT", "operands": [{"ref": "D0"}],
            "expression": expr, "source": {"op": "MATH", "raw": "MATH D0"}}


def test_cpt_modulo_translated_no_diag():
    diags = []
    text = instruction_to_text(_cpt_node("(D1 % 3) + D0"), diags, {})
    assert text == "CPT(D0,(D1 MOD 3) + D0)"
    assert not diags  # CPT-clean expression -> no review diagnostic


def test_cpt_round_respelled_emits_real_cpt_with_info_note():
    # ROUND is re-spelled (not degraded): the leaf emits a real CPT with (TRN(x + 0.5)), and a
    # non-blocking info note records the positive-domain assumption. No NOP, no LLT EMIT marker.
    from llt.emit.neutral_text import degraded_marker_op
    diags = []
    text = instruction_to_text(_cpt_node("ROUND(D1)"), diags, {})
    assert text == "CPT(D0,(TRN(D1 + 0.5)))"
    assert degraded_marker_op(_cpt_node("ROUND(D1)")) is None  # not a degraded seam
    note = next(d for d in diags if d.code == "TRANSLATION_NOTE")
    assert note.severity == "info" and "TRN(x + 0.5)" in note.message


def test_cpt_standalone_toreal_emits_native_mov_with_info_note():
    # A whole-expression Do-More TOREAL(<operand>) maps to a native MOV (int->real is implicit on an
    # AB MOV to a REAL dest) -- NOT flagged, NOT a CPT, NOT a NOP. A non-blocking info note records it.
    from llt.emit.neutral_text import degraded_marker_op
    diags = []
    text = instruction_to_text(_cpt_node("TOREAL(D1)"), diags, {})
    assert text == "MOVE(D1,D0)"  # MOV serializes under its v36 MOVE token; dest is the CPT dest (D0)
    assert degraded_marker_op(_cpt_node("TOREAL(D1)")) is None  # not a degraded seam
    assert not any(d.code == "REVIEW_REQUIRED" for d in diags)  # mapped, not flagged
    note = next(d for d in diags if d.code == "TRANSLATION_NOTE")
    assert note.severity == "info" and "MOV" in note.message


def test_cpt_nested_toreal_emits_real_cpt_with_info_note():
    # TOREAL inside a larger expression rides AB's dest-type REAL promotion: the wrapper is unwrapped
    # and a real CPT is emitted (not a MOV, not a NOP), with a non-blocking info note.
    from llt.emit.neutral_text import degraded_marker_op
    diags = []
    text = instruction_to_text(_cpt_node("TOREAL(D1) + 1.0"), diags, {})
    assert text == "CPT(D0,(D1) + 1.0)"
    assert degraded_marker_op(_cpt_node("TOREAL(D1) + 1.0")) is None
    assert not any(d.code == "REVIEW_REQUIRED" for d in diags)
    note = next(d for d in diags if d.code == "TRANSLATION_NOTE")
    assert note.severity == "info" and "REAL" in note.message


def test_cpt_incompatible_expression_degrades_to_nop():
    # AB CPT can't express IF/==, so the leaf degrades to an importable NOP() placeholder (the
    # verbatim CPT(dest,IF(...)) would NOT import); the original expression rides on the diagnostic.
    diags = []
    text = instruction_to_text(_cpt_node("IF((D1 % 3) == 0, D0 + 1, D0)"), diags, {})
    assert text == "NOP()"
    d = next(d for d in diags if d.code == "REVIEW_REQUIRED")
    assert "CPT" in d.message and "IF((D1 % 3) == 0, D0 + 1, D0)" in d.message  # carries the original
    # And the shared predicate marks it for the LLT EMIT rung comment, keyed by its source op.
    from llt.emit.neutral_text import degraded_marker_op
    assert degraded_marker_op(_cpt_node("IF((D1 % 3) == 0, D0 + 1, D0)")) == "MATH"


# --- v36 emit-token overrides (MOV -> MOVE, NEQ -> NE), decoded from the SANDBOX export ---

def test_mov_serializes_as_v36_move_token():
    node = {"kind": "instruction", "op": "MOV", "operands": [{"ref": "A"}, {"ref": "B"}]}
    assert instruction_to_text(node, [], {}) == "MOVE(A,B)"


def test_compare_family_uses_v36_tokens():
    # v36 shortens the compare family (SANDBOX rung 19); LIM lengthens to LIMIT.
    from llt import opcodes
    assert {op: opcodes.emit_token(op) for op in ("EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM")} == {
        "EQU": "EQ", "NEQ": "NE", "LES": "LT", "LEQ": "LE", "GRT": "GT", "GEQ": "GE", "LIM": "LIMIT"}
    node = {"kind": "instruction", "op": "LES", "operands": [{"ref": "A"}, {"ref": "B"}]}
    assert instruction_to_text(node, [], {}) == "LT(A,B)"


def test_ops_without_override_serialize_under_their_own_name():
    from llt import opcodes
    assert opcodes.emit_token("XIC") == "XIC"
    assert opcodes.emit_token("MEQ") == "MEQ"  # masked-equal token unconfirmed -> left as-is
    node = {"kind": "instruction", "op": "ADD",
            "operands": [{"ref": "A"}, {"literal": 1}, {"ref": "A"}]}
    assert instruction_to_text(node, [], {}) == "ADD(A,1,A)"


# --- opaque ops carry AB-specific guidance for the known-lossy families ---

def test_opaque_lossy_op_carries_actionable_guidance():
    from llt.opcodes import OPAQUE_OP
    diags = []
    instruction_to_text({"kind": "instruction", "op": OPAQUE_OP, "operands": [{"ref": "A"}],
                         "source": {"op": "SR"}}, diags, {})
    assert diags[0].code == "UNSUPPORTED_INSTRUCTION"
    assert "BSL/BSR" in diags[0].message  # SR-specific direction, not a generic message


def test_byte_cast_write_lowers_to_btd_deposit():
    from llt.emit.neutral_text import degraded_marker_op
    # MOV(192, D100:UB2): write byte 2 of D100. Byte 2 = bits 16..23, so the deposit BTD bit is 16,
    # length 8, and the parent's other bytes are preserved (BTD, not MOVE). No LLT EMIT marker.
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"literal": 192}, {"ref": "D100:UB2"}], "source": {"op": "MOVE"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "BTD(192,0,D100,16,8)"
    assert degraded_marker_op(node) is None  # translated -> not degraded, no LLT EMIT comment
    d = next(d for d in diags if d.code == "TRANSLATION_NOTE")
    assert d.severity == "info" and "D100:UB2" in d.message


def test_byte_cast_write_bit_offset_tracks_the_byte_index():
    # byte 0 deposits at bit 0; byte 3 deposits at bit 24 -- the BTD dest bit must follow index*8.
    for index, bit in ((0, 0), (3, 24)):
        node = {"kind": "instruction", "op": "MOV",
                "operands": [{"ref": "V7"}, {"ref": f"D5:UB{index}"}], "source": {"op": "MOVE"}}
        diags: list[Diagnostic] = []
        assert instruction_to_text(node, diags, {}) == f"BTD(V7,0,D5,{bit},8)"


def test_byte_cast_read_lowers_to_clr_plus_btd_extract():
    from llt.emit.neutral_text import degraded_marker_op
    # MOV(D0:UB2, D9): read unsigned byte 2 of D0 into D9. The dest is cleared (zero-extend) then
    # byte 2 (bits 16..23) is distributed into its low byte -- source bit 16, dest bit 0, length 8.
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "D0:UB2"}, {"ref": "D9"}], "source": {"op": "MOVE"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "CLR(D9)BTD(D0,16,D9,0,8)"
    assert degraded_marker_op(node) is None
    assert any(d.code == "TRANSLATION_NOTE" for d in diags)


def test_byte_cast_read_source_bit_tracks_the_byte_index():
    # a different byte index must change the BTD *source* bit (byte 1 -> bit 8, byte 3 -> bit 24).
    for index, bit in ((1, 8), (3, 24)):
        node = {"kind": "instruction", "op": "MOV",
                "operands": [{"ref": f"D0:UB{index}"}, {"ref": "D9"}]}
        diags: list[Diagnostic] = []
        assert instruction_to_text(node, diags, {}) == f"CLR(D9)BTD(D0,{bit},D9,0,8)"


def test_signed_byte_read_stays_a_flagged_seam():
    from llt.emit.neutral_text import degraded_marker_op
    # a signed-byte *read* (D0:B1 as a source) needs sign extension -> no single faithful AB form,
    # so it stays a NOP() seam with the LLT EMIT marker; a signed-byte *write* still lowers (below).
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "D0:B1"}, {"ref": "D9"}], "source": {"op": "MOVE"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "NOP()"
    assert degraded_marker_op(node) == "MOVE"
    assert any(d.code == "REVIEW_REQUIRED" for d in diags)


def test_signed_byte_write_lowers_to_btd():
    # writing a signed byte (D0:B1 as a dest) deposits 8 bits -- sign is irrelevant on a write.
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "V3"}, {"ref": "D0:B1"}]}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "BTD(V3,0,D0,8,8)"


def test_dword_cast_lowers_to_full_move_not_a_byte_extract():
    from llt.emit.neutral_text import degraded_marker_op
    # a :D (32-bit dword) cast is a full-width reinterpretation -> a plain MOVE, NOT a BTD byte
    # field. This is the byte-vs-word distinction: :UBn -> BTD, :D -> MOVE.
    write = {"kind": "instruction", "op": "MOV",
             "operands": [{"ref": "V1"}, {"ref": "D0:D"}], "source": {"op": "MOVE"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(write, diags, {}) == "MOVE(V1,D0)"
    assert "BTD" not in instruction_to_text(write, [], {})
    assert degraded_marker_op(write) is None
    read = {"kind": "instruction", "op": "MOV", "operands": [{"ref": "D0:D"}, {"ref": "V1"}]}
    assert instruction_to_text(read, [], {}) == "MOVE(D0,V1)"


def test_ranged_copy_with_a_byte_cast_stays_a_seam():
    # a byte cast on a multi-element COP (length > 1) would need a per-element byte loop, not one
    # instruction -> it stays a flagged NOP() seam rather than a wrong single BTD.
    node = {"kind": "instruction", "op": "COP",
            "operands": [{"ref": "D0"}, {"ref": "D8:UB1"}, {"literal": 4}], "source": {"op": "COPY"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "NOP()"
    assert any(d.code == "REVIEW_REQUIRED" for d in diags)


def test_single_element_copy_with_a_byte_cast_lowers():
    # a length-1 COP is a single move, so a byte cast on it lowers like a MOV (write -> BTD).
    node = {"kind": "instruction", "op": "COP",
            "operands": [{"ref": "D0"}, {"ref": "D8:UB1"}, {"literal": 1}]}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "BTD(D0,0,D8,8,8)"


def test_dual_byte_cast_packs_to_a_single_btd():
    from llt.emit.neutral_text import degraded_marker_op
    # A byte cast on BOTH source and dest (MOV(DLV0:B0, D100:UB3)) packs byte 0 of DLV0 into byte 3
    # of D100 -> one BTD, source bit 0, dest bit 24, length 8. This is the byte-packing INIT form
    # (#88); it used to be punted to a NOP seam by #58. No LLT EMIT marker.
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "DLV0:B0"}, {"ref": "D100:UB3"}], "source": {"op": "INIT"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "BTD(DLV0,0,D100,24,8)"
    assert degraded_marker_op(node) is None  # translated -> not degraded, no LLT EMIT comment
    d = next(d for d in diags if d.code == "TRANSLATION_NOTE")
    assert d.severity == "info" and "DLV0:B0" in d.message


def test_dual_byte_cast_bits_track_both_byte_indices_independently():
    # The BTD *source* bit follows the SOURCE byte index and the *dest* bit follows the DEST byte
    # index, independently: A:Bi -> B:UBj becomes BTD(A, i*8, B, j*8, 8).
    for (si, di), want in {
        (0, 2): "BTD(A,0,B,16,8)",
        (2, 0): "BTD(A,16,B,0,8)",
        (3, 1): "BTD(A,24,B,8,8)",
    }.items():
        node = {"kind": "instruction", "op": "MOV",
                "operands": [{"ref": f"A:B{si}"}, {"ref": f"B:UB{di}"}]}
        assert instruction_to_text(node, [], {}) == want


def test_dual_byte_cast_dword_side_stays_a_seam():
    from llt.emit.neutral_text import degraded_marker_op
    # A :D dword on either side of a dual cast is a full-word reinterpretation, not an 8-bit pack ->
    # no single faithful BTD, so it stays the flagged NOP() seam (only byte<->byte lowers).
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "D0:D"}, {"ref": "D100:UB1"}], "source": {"op": "INIT"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "NOP()"
    assert degraded_marker_op(node) == "INIT"
    assert any(d.code == "REVIEW_REQUIRED" for d in diags)


def test_system_tag_colon_is_not_mistaken_for_a_byte_cast():
    # S:FS (first-scan status) has a colon but is NOT a byte cast -> renders normally, no degrade.
    diags: list[Diagnostic] = []
    assert instruction_to_text({"kind": "instruction", "op": "XIC",
                                "operands": [{"ref": "S:FS"}]}, diags, {}) == "XIC(S:FS)"
    assert diags == []


def test_dst_sentinel_in_a_required_slot_degrades_to_importable_nop():
    from llt.emit.neutral_text import degraded_marker_op
    # A compare contact has no optional slots, so a DST sentinel here means the operator left the box
    # blank -- nothing to compare -> NOP() + a REVIEW naming it.
    node = {"kind": "instruction", "op": "EQU",
            "operands": [{"ref": "DST50"}, {"literal": 2}], "source": {"op": "STRE"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "NOP()"
    d = next(d for d in diags if d.code == "REVIEW_REQUIRED")
    assert "DST50" in d.message and "left blank" in d.message
    assert degraded_marker_op(node) == "STRE"


def test_dst_degrade_matches_only_DST_number_not_similar_tag_names():
    # a real tag that merely starts with "DST" (DSTATE) is NOT a DST<n> pseudo-element -> renders.
    diags: list[Diagnostic] = []
    assert instruction_to_text({"kind": "instruction", "op": "XIC",
                                "operands": [{"ref": "DSTATE"}]}, diags, {}) == "XIC(DSTATE)"
    assert diags == []


def test_byte_cast_dst_sentinel_degrades_to_nop_not_a_dangling_btd():
    # Issue #127: the LB Standard bundle's Z1_ENET_Config byte-packing INIT rows leave some slots
    # unassigned, so the parser hands a byte-cast leaf whose BASE ref is a DST<n> sentinel (not a
    # real tag) -- e.g. `INIT "... DLV20:B0 ST1023 DST18:UB3 ..."` -> MOV(DLV20:B0, DST18:UB3).
    # _bytecast_operand/_bytecast_translation would happily lower this mechanically to
    # BTD(DST18,24,DLV20,0,8) -- a reference Studio rejects on verify ("Referenced tag is
    # undefined") since DST18 is never emitted as a tag. The DST check must run BEFORE the
    # byte-cast lowering so this degrades to the same flagged NOP() as any other required-slot DST.
    from llt.emit.neutral_text import degraded_marker_op
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "DLV20:B0"}, {"ref": "DST18:UB3"}], "source": {"op": "INIT"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "NOP()"
    assert not any("BTD" in d.message for d in diags)
    d = next(d for d in diags if d.code == "REVIEW_REQUIRED")
    assert "DST18" in d.message and "left blank" in d.message
    assert degraded_marker_op(node) == "INIT"


def test_byte_cast_dst_sentinel_as_source_also_degrades_to_nop():
    # The DST sentinel can carry the cast on either side of the move; a single-sided byte-cast read
    # from a DST base (`MOV(DST18:UB2, D100)`) is just as dangling as the byte-pack shape above.
    node = {"kind": "instruction", "op": "MOV",
            "operands": [{"ref": "DST18:UB2"}, {"ref": "D100"}], "source": {"op": "INIT"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "NOP()"
    assert not any(d.code != "REVIEW_REQUIRED" for d in diags)
    assert any("DST18" in d.message for d in diags)


def test_opaque_op_renders_as_importable_nop():
    # An opaque leaf degrades to NOP() (a valid AB instruction) so the component still imports;
    # the original mnemonic survives in the diagnostic + the rung's `LLT EMIT` comment, not here.
    from llt.opcodes import OPAQUE_OP
    diags = []
    text = instruction_to_text({"kind": "instruction", "op": OPAQUE_OP,
                                "operands": [{"ref": "A"}, {"ref": "B"}],
                                "source": {"op": "DEVWRITE"}}, diags, {})
    assert text == "NOP()"
    assert "NOP()" in diags[0].message  # diagnostic names the placeholder


# The device/comms/control-flow/file ops that make up TankStruct's opaque tail each carry a
# concrete reason (an AB form + why it isn't faithfully emittable, or "no AB primitive"), not the
# generic "implement it by hand". A distinctive substring per op pins that the right entry fires.
def test_device_and_control_flow_ops_carry_specific_guidance():
    from llt.opcodes import OPAQUE_OP
    cases = {
        "DEVREAD": "MSG read",
        "DEVWRITE": "MSG write",
        "SETUPIP": "TCP/IP",
        "SETTIME": "WALLCLOCKTIME",
        "PUBLISH": "MQTT",
        "HALT": "no halt instruction",
        "FILEOPEN": "no component-scoped file I/O",
        "FILEREAD": "no component-scoped file I/O",
        "FILEWRITE": "no component-scoped file I/O",
        "FILECLOSE": "no component-scoped file I/O",
    }
    for src_op, needle in cases.items():
        diags = []
        instruction_to_text({"kind": "instruction", "op": OPAQUE_OP, "operands": [{"ref": "A"}],
                             "source": {"op": src_op}}, diags, {})
        assert diags[0].code == "UNSUPPORTED_INSTRUCTION"
        assert "implement it by hand" not in diags[0].message, f"{src_op} fell back to generic"
        assert needle in diags[0].message, f"{src_op} guidance missing {needle!r}"


def test_opaque_op_without_guidance_falls_back_to_generic():
    from llt.opcodes import OPAQUE_OP
    diags = []
    instruction_to_text({"kind": "instruction", "op": OPAQUE_OP, "operands": [],
                         "source": {"op": "FILTER"}}, diags, {})
    assert "implement it by hand" in diags[0].message


def test_dst_sentinel_in_an_optional_call_slot_is_omitted_not_dropped():
    # Do-More writes DST<n> for an UNCHECKED optional slot. A CALL's unset parameter is one, so the
    # faithful AB form simply doesn't pass that argument -- JSR(Derating,0). Treating it as broken
    # silently deleted every subroutine call in a real program (all 9 JSRs), so this is load-bearing:
    # the instruction must survive, with no seam raised.
    node = {"kind": "instruction", "op": "JSR", "callTarget": "Derating",
            "operands": [{"ref": "DST511"}], "source": {"op": "CALL"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "JSR(Derating,0)"
    assert diags == []


def test_real_call_parameters_still_ride_on_the_jsr():
    # Stripping sentinels must not strip genuine arguments.
    node = {"kind": "instruction", "op": "JSR", "callTarget": "Derating",
            "operands": [{"ref": "V10"}, {"ref": "DST511"}], "source": {"op": "CALL"}}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "JSR(Derating,1,V10)"


def test_call_box_metadata_does_not_become_jsr_parameters():
    # Do-More writes `CALL <blk> 0x1 DST511 "3" "3"` -- the trailing literals are box metadata, not
    # arguments (identical across every call site; the target declares no parameters). Passing them
    # would emit JSR(X,3,1,3,3) into a routine with no SBR, which Logix rejects on verify.
    node = {"kind": "instruction", "op": "JSR", "callTarget": "Derating", "source": {"op": "CALL"},
            "operands": [{"literal": 1}, {"ref": "DST511"}, {"literal": "3"}, {"literal": "3"}]}
    diags: list[Diagnostic] = []
    assert instruction_to_text(node, diags, {}) == "JSR(Derating,0)"
    d = next(d for d in diags if d.code == "REVIEW_REQUIRED")
    assert "plain dispatch" in d.message
