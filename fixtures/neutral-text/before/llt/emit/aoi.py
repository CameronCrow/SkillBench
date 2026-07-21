"""Allen-Bradley AOI library + emit-side mapping (library-install model).

Some IL ops have **no native Allen-Bradley instruction** but map to an **Add-On
Instruction** shipped in the AOI library (``src/llt/emit/aoi_library/``) and installed
**once per Studio 5000 project**. At emit time the emitter *references* the AOI
(``Use="Context"`` → Use Existing on import) and emits a per-call-site **backing tag**;
the engineer installs the library once (``llt aoi-export``). Single-file bundling was
tested and rejected — Studio will not auto-create a bundled ``Use="Context"`` AOI
(1756-PM019). Design + library: ``docs/L5X-docs/AB-AOIs/README.md``.

This is the emit-side counterpart to ``llt.opcodes``: ``opcodes`` covers ops with a native
AB instruction; this covers ops delivered as an AOI. An op in neither is unsupported and the
emitter flags it (``phase: emit``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

LIBRARY_DIR = Path(__file__).parent / "aoi_library"

# IL atomic types that select the *bit* differential AOI; anything else is numeric.
_BOOL_TYPES = {"BOOL"}
# Numeric IL types whose delta loses precision through DIFF_NUM's DINT cast -> use DIFF_REAL instead.
_REAL_TYPES = {"REAL", "LREAL"}

# DIFF_REAL's default deadband. MUST match the EPS parameter's DefaultData in DIFF_REAL.L5X -- this
# copy exists only so the emit-time diagnostic can name the value. ponytail: absolute deadband; a
# signal far off unity scale (say |x| > 1e4, where float32 ULP nears 1e-3) should tune EPS per box.
DIFF_REAL_DEFAULT_EPS = 1e-4


@dataclass(frozen=True)
class AoiDef:
    """One library AOI. ``name`` is both the AOI name and its backing tag's DataType.

    ``out_member`` distinguishes the two AOI call shapes:

    * **contact-style** (``out_member`` set, e.g. ``"OUT"``): a single-operand AOI whose BOOL
      result member is read as a contact *after* the call (``backing.OUT``) and carries into the
      rung. We do NOT condition the rung on ``EnableOut`` (it only signals the AOI executed
      without error, not the result -- confirmed in Studio, 2026-06-17). Used by ``DLT``.
    * **output-style** (``out_member`` is ``None``): the AOI writes its result to a destination
      operand; the call takes ALL operands and has no trailing result contact. Used by ``SCALE``.
    """

    name: str
    revision: str
    library_file: str  # filename under aoi_library/
    summary: str
    out_member: str | None = "OUT"
    # UDT (or other) .L5X files this AOI depends on, under aoi_library/. They ship + export with the
    # AOI and must be imported BEFORE it (a UDT the AOI's parameters reference). Import order is the
    # tuple order (dependencies first, then the AOI).
    dependencies: tuple[str, ...] = ()


AOI_LIBRARY: dict[str, AoiDef] = {
    "DIFF_BIT": AoiDef("DIFF_BIT", "1.0", "DIFF_BIT.L5X", "bit changed since last scan"),
    "DIFF_NUM": AoiDef("DIFF_NUM", "1.0", "DIFF_NUM.L5X", "numeric value changed since last scan"),
    # REAL differential: a DINT cast (DIFF_NUM) would drop the fraction, and an exact NE on a REAL
    # would fire on float noise every scan -- so this variant compares against an EPS deadband. EPS
    # is a per-instance Input (default 1e-4, editable on the box). See DIFF_REAL_DEFAULT_EPS.
    "DIFF_REAL": AoiDef("DIFF_REAL", "1.0", "DIFF_REAL.L5X",
                        "REAL changed past an EPS deadband since last scan"),
    # LLT AOIs are DM_-prefixed (Do-More) so their name can't collide with a project's own UDTs
    # or instructions -- AB shares one namespace across data types + AOIs (a bare "SCALE" collided
    # with a project UDT and aborted the import). The IL op stays the neutral "SCALE".
    "DM_SCALE": AoiDef("DM_SCALE", "1.0", "DM_SCALE.L5X", "linear scale raw range -> EU range",
                       out_member=None),
    "DM_DECO": AoiDef("DM_DECO", "1.0", "DM_DECO.L5X", "decode integer -> 1-of-N bit",
                      out_member=None),
    "DM_FILTER": AoiDef("DM_FILTER", "1.0", "DM_FILTER.L5X", "first-order exponential filter",
                        out_member=None),
    "DM_ALDEV": AoiDef("DM_ALDEV", "1.0", "DM_ALDEV.L5X", "deviation alarm", out_member=None),
    "DM_ALRATE": AoiDef("DM_ALRATE", "1.0", "DM_ALRATE.L5X", "rate-of-change alarm", out_member=None),
    "DM_ALHILO": AoiDef("DM_ALHILO", "1.0", "DM_ALHILO.L5X", "4-level high/low alarm", out_member=None),
    # STRPRINT (Print to String) compose: the one printf-shape LLT lowers to a real AOI is a single
    # decimal integer field (FmtInt(x,dec)) -> DTOS. Its body is native DTOS(In,Dest); any richer
    # format (literals, FmtTMR/FmtReal, non-dec radix, multiple fields) stays a MANUAL_STRING_COMPOSE
    # seam -- never a plausible-but-wrong compose (issue #49).
    "DM_ITOS": AoiDef("DM_ITOS", "1.0", "DM_ITOS.L5X", "format a signed integer as a decimal string",
                      out_member=None),
    # STRPRINT FmtTMR(x,sec): a timer/accumulator (milliseconds) -> an "Hh Mm Ss" duration string.
    # Body is DIV/MOD arithmetic + DTOS/CONCAT; the exact field format (always Hh Mm Ss) is a fixed
    # rendering flagged for verification -- Do-More's default omits leading-zero hours/minutes.
    "DM_FMTTMR": AoiDef("DM_FMTTMR", "1.0", "DM_FMTTMR.L5X",
                        "format a millisecond accumulator as an Hh Mm Ss duration string",
                        out_member=None),
    # RAMPSOAK is emitted by a dedicated lowering (emit/rampsoak.py), not the generic AOI render, so
    # it is NOT in _OP_TO_AOI. It carries two UDT dependencies (import them first).
    "DM_RAMPSOAK": AoiDef("DM_RAMPSOAK", "1.1", "DM_RAMPSOAK.L5X", "ramp/soak setpoint profiler",
                          out_member=None,
                          dependencies=("DM_RAMPSOAK_STEP.L5X", "DM_RAMPSOAK_PROF.L5X")),
}

# IL op -> library AOI name, for ops that map 1:1 to an AOI. (DLT is not here: it dispatches by
# operand datatype in select_aoi. Adding an output-style AOI op is a one-line entry here.)
_OP_TO_AOI = {
    "SCALE": "DM_SCALE",
    "DECO": "DM_DECO",
    "FILTER": "DM_FILTER",
    "ALDEV": "DM_ALDEV",
    "ALRATE": "DM_ALRATE",
    "ALHILO": "DM_ALHILO",
    # ITOS is a synthetic op minted by emit/string_compose.py when it recognizes a single-integer
    # STRPRINT format; it never comes from the parser (STRPRINT stays opaque there). Output-style:
    # DM_ITOS(backing, In, Dest).
    "ITOS": "DM_ITOS",
    # FMTTMR is likewise synthetic (minted by emit/string_compose.py for a FmtTMR(x,sec) template);
    # output-style: DM_FMTTMR(backing, In, Dest).
    "FMTTMR": "DM_FMTTMR",
    # RAMPSOAK's operands are assembled by a dedicated pre-pass (emit/rampsoak.py) that also mints
    # the profile + status tags and the leg/init rungs; by the time the AOI render sees it, it is a
    # plain output-style call, so it rides the generic path here (backing tag + REQUIRES_AOI + the
    # two UDT dependencies all handled by AoiUsage).
    "RAMPSOAK": "DM_RAMPSOAK",
}

# IL ops rendered via an AOI rather than a native AB instruction.
_AOI_OPS = {"DLT", *_OP_TO_AOI}


def is_aoi_op(il_op: str) -> bool:
    """Is this IL op delivered via an AOI (rather than a native AB instruction)?"""
    return il_op in _AOI_OPS


@lru_cache(maxsize=1)
def dependency_type_names() -> frozenset[str]:
    """UDT type names shipped as AOI dependencies (e.g. ``DM_RAMPSOAK_PROF``).

    A tag of one of these types resolves once its owning AOI is installed (the ``.L5X`` ships the
    UDT), so the emitter emits it as a plain reference -- not an unresolved-type import blocker.
    """
    return frozenset(dep[:-4] if dep.endswith(".L5X") else dep
                     for adef in AOI_LIBRARY.values() for dep in adef.dependencies)


def select_aoi(il_op: str, operand_type: str | None) -> AoiDef | None:
    """Pick the library AOI for an AOI-backed op, dispatched by the operand's IL datatype.

    ``DLT`` (Do-More differential/"delta" contact): a BOOL operand → ``DIFF_BIT``; a REAL/LREAL
    operand → ``DIFF_REAL`` (deadband compare, no DINT truncation); any other numeric → ``DIFF_NUM``.
    Unknown type defaults to ``DIFF_BIT`` (contacts are usually bits; the emitter flags the ambiguity).
    """
    if il_op == "DLT":  # differential contact: dispatch by operand datatype
        if operand_type is None or operand_type in _BOOL_TYPES:
            return AOI_LIBRARY["DIFF_BIT"]
        if operand_type in _REAL_TYPES:
            return AOI_LIBRARY["DIFF_REAL"]
        return AOI_LIBRARY["DIFF_NUM"]
    name = _OP_TO_AOI.get(il_op)  # the output-style AOIs map 1:1
    return AOI_LIBRARY[name] if name else None


def is_lossy_numeric(operand_type: str | None) -> bool:
    """True if a numeric operand would lose precision through DIFF_NUM's DINT cast."""
    return operand_type in _REAL_TYPES


def library_path(name: str) -> Path:
    return LIBRARY_DIR / AOI_LIBRARY[name].library_file


def dependency_paths(name: str) -> list[Path]:
    """The AOI's dependency ``.L5X`` files (UDTs, ...), in import order -- these go in BEFORE the AOI."""
    return [LIBRARY_DIR / dep for dep in AOI_LIBRARY[name].dependencies]


@lru_cache(maxsize=None)
def read_definition(name: str) -> str:
    """The AOI's ``.L5X`` library file text (for ``llt aoi-export`` / one-time install)."""
    return library_path(name).read_text(encoding="utf-8")


# --- bundle staleness: does a bundle's AOI content match the installed library? ---------------
#
# A bundle copies the installed ``aoi_library/*.L5X`` at assemble time. If those library files
# change later (e.g. the #74 ExternalAccess fix rewrote DM_FMTTMR.L5X), a bundle assembled BEFORE
# the change carries the *old* AOI content -- importing it re-imports the stale, blocker-carrying
# definitions, which fail every import and (via undismissed popups) can crash Studio. We catch this
# by stamping a content fingerprint of the bundled AOI files into ``manifest.json`` at assemble time
# (:func:`library_fingerprint`), then recomputing the installed library's fingerprint at import time
# and warning on any mismatch (:func:`detect_aoi_drift`). The comparison is a pure function so it is
# unit-testable with no Studio and no filesystem.

# manifest.json key holding the staleness stamp. Presence of this key marks a bundle assembled by
# a build that has this feature; its ABSENCE marks a pre-feature bundle (itself a staleness signal).
STALENESS_KEY = "staleness"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def library_fingerprint(filenames: Iterable[str] | None = None) -> dict[str, str]:
    """Content fingerprint of the installed AOI library: ``{filename: sha256-hex}``.

    ``filenames`` restricts the fingerprint to that subset (a file that isn't in the installed
    library is omitted, so its absence shows up as drift at compare time); ``None`` fingerprints
    every ``*.L5X`` in ``aoi_library/``. Deterministic: keys follow the given order (deduped) or
    sorted for the whole-directory case.
    """
    if filenames is None:
        names: list[str] = sorted(p.name for p in LIBRARY_DIR.glob("*.L5X"))
    else:
        names = list(dict.fromkeys(filenames))  # dedupe, preserve first-seen order
    out: dict[str, str] = {}
    for name in names:
        p = LIBRARY_DIR / name
        if p.is_file():
            out[name] = _file_sha256(p)
    return out


@dataclass(frozen=True)
class AoiDrift:
    """The result of comparing a bundle's stamped AOI fingerprint to the installed library.

    ``stale`` names bundled AOI files whose installed copy has since changed (or vanished);
    ``missing_stamp`` marks a bundle that predates the staleness feature entirely. Either is a
    non-blocking staleness signal -- :meth:`message` renders the human-readable warning (``None``
    when there's no drift).
    """

    stale: tuple[str, ...] = ()
    missing_stamp: bool = False

    @property
    def has_drift(self) -> bool:
        return self.missing_stamp or bool(self.stale)

    def message(self) -> str | None:
        """A non-blocking warning naming the drift and recommending the fix, or ``None`` if clean."""
        if self.missing_stamp:
            return ("This bundle predates LLT's staleness stamp, so it may have been assembled "
                    "before AOI-library or emitter fixes now installed. Re-assemble it from the "
                    "project before importing.")
        if self.stale:
            files = ", ".join(self.stale)
            return (f"Bundled AOI definition(s) differ from the installed AOI library: {files}. "
                    f"This bundle was assembled before those AOIs changed; importing it may fail "
                    f"in Studio. Re-assemble it from the project before importing.")
        return None


def detect_aoi_drift(manifest: dict, installed_fingerprint: dict[str, str]) -> AoiDrift:
    """Pure comparison: is ``manifest``'s stamped AOI fingerprint stale vs ``installed_fingerprint``?

    ``installed_fingerprint`` is the currently-installed library's ``{filename: sha256}`` (see
    :func:`library_fingerprint`). Rules:

    * manifest has no :data:`STALENESS_KEY` -> ``missing_stamp`` (a pre-feature bundle).
    * a stamped file whose hash differs from (or is absent from) the installed one -> ``stale``.
    * an empty stamp (a fresh bundle that referenced no AOIs) -> no drift.
    """
    if STALENESS_KEY not in manifest:
        return AoiDrift(missing_stamp=True)
    stamp = (manifest.get(STALENESS_KEY) or {}).get("aoiFingerprint") or {}
    stale = tuple(sorted(f for f, h in stamp.items() if installed_fingerprint.get(f) != h))
    return AoiDrift(stale=stale)


def check_bundle_staleness(manifest: dict) -> AoiDrift:
    """:func:`detect_aoi_drift` against the *currently-installed* AOI library (reads the files).

    The import-side entry point: recomputes the installed fingerprint for exactly the files the
    bundle stamped, so an unchanged library reports no drift and a changed one names the files.
    """
    if STALENESS_KEY not in manifest:
        return AoiDrift(missing_stamp=True)
    stamp = (manifest.get(STALENESS_KEY) or {}).get("aoiFingerprint") or {}
    return detect_aoi_drift(manifest, library_fingerprint(stamp.keys()))


@dataclass
class AoiUsage:
    """Accumulates AOI usage across one emit: required definitions + generated backing tags.

    ``use()`` is called once per AOI call site; it allocates a fresh backing tag (each
    differential contact needs its own previous-scan state) and records the required AOI.
    """

    required: dict[str, AoiDef] = field(default_factory=dict)
    backing_tags: list[dict] = field(default_factory=list)
    _counters: dict[str, int] = field(default_factory=dict)

    def use(self, aoi: AoiDef) -> str:
        """Record a use of ``aoi``; return a fresh backing-tag name for this call site."""
        self.required[aoi.name] = aoi
        n = self._counters.get(aoi.name, 0) + 1
        self._counters[aoi.name] = n
        tag_name = f"{aoi.name}_{n}"
        self.backing_tags.append(
            {"name": tag_name, "dataType": aoi.name, "scope": "program", "usage": "memory"}
        )
        return tag_name
