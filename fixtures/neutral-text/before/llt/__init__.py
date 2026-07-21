"""LLT — Ladder Logic Translator.

Translates PLC ladder logic from AutomationDirect Do-More into Rockwell
Allen-Bradley, routing through one vendor-neutral Intermediate Language (IL).

This package is pre-implementation scaffold (Phase 1). The load-bearing artifact
today is the IL JSON Schema; :mod:`llt.schema` loads and validates against it.
"""

__version__ = "0.1.0"
