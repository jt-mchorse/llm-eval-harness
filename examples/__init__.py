"""Runnable examples for the eval-harness public API.

Each module in this package is a self-contained script demonstrating one layer
of the harness. All examples are hermetic — they use stub backends and a
deterministic `AnswerSource`, so they run end-to-end on a fresh `pip install -e .`
clone with no API key.

The smoke test in `tests/test_examples_smoke.py` imports each example module
and runs its `main()` so the examples never silently drift out of sync with
the public API.
"""
