"""Live provider adapters for the regulatory ingestion framework.

Each adapter implements the discover -> fetch -> normalize stages described in
``docs/regulatory_ingestion_framework_v0_1.md`` and mirrored (design-only) by
``research/regulatory/contracts.py``'s ``RegulatoryProviderAdapter`` protocol.
Adapters live under ``src/aguayluz`` rather than importing ``research.regulatory``
because that package is deliberately design-only — no network, no persistence (see
its module docstring and ``tests/test_regulatory_framework_v0_2.py``'s
``test_contract_module_stays_design_only``). Runtime implementation is intentionally
a separate, reviewed module per provider.
"""
