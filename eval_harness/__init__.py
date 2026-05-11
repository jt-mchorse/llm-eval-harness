"""Reusable LLM eval framework.

Public surface (so far): the dataset layer — load and dump versioned golden
JSONL datasets, with line-number error reporting. Subsequent issues add the
judge wrapper (#2), regression runner (#3), drift detection (#4), pytest
plugin (#5), GitHub Action (#6), and CLI (#7).
"""

from eval_harness.dataset import (
    Dataset,
    DatasetLoadError,
    Example,
    ExpectedOutput,
    load_jsonl,
)

__all__ = [
    "Dataset",
    "DatasetLoadError",
    "Example",
    "ExpectedOutput",
    "load_jsonl",
]

__version__ = "0.0.1"
