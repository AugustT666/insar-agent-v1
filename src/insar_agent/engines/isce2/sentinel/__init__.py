"""Sentinel-1 / ISCE2 data preparation package.

Split from the former single-module ``sentinel_prep`` into focused submodules:

- ``_common``       — shared filesystem / XML primitives and conda env helpers
- ``metadata``      — SceneRecord, manifest/XML parsing, geolocation checks
- ``annotation``    — per-burst annotation XML synthesis
- ``burst_assembly``— TIFF concatenation, annotation/measurement synthesis,
                      burst-source discovery and manifest extraction
- ``geolocation``   — SAFE annotation geolocation validation and preview overlay
- ``orbit``         — precise orbit download, retry/backoff, ISCE2 script paths
- ``prepare``       — top-level ``prepare_sentinel_data`` orchestration and
                      ISCE2 import validation

The legacy module path ``insar_agent.engines.isce2.sentinel_prep`` remains a
compatibility shim that re-exports the public and test-facing symbols.
"""
