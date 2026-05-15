"""Reusable LLM eval framework.

Public surface:
- Dataset layer (#1, shipped): versioned JSONL goldens with line-number errors.
- Judge wrapper (#2, shipped): LLM-as-judge with calibration against human labels.
- Regression runner (#3), drift detection (#4), pytest plugin (#5), GitHub
  Action (#6), CLI extensions (#7) — separate issues.
"""

from eval_harness.calibration import (
    CalibrationLoadError,
    CalibrationResult,
    CalibrationRow,
    binarize,
    calibrate,
    cohens_kappa,
    load_calibration,
    pearson_r,
    render_report,
)
from eval_harness.dataset import (
    Dataset,
    DatasetLoadError,
    Example,
    ExpectedOutput,
    load_jsonl,
)
from eval_harness.judge import (
    FAITHFULNESS_RUBRIC,
    AnthropicBackend,
    Backend,
    Judge,
    JudgeParseError,
    JudgeScore,
    parse_judge_output,
)

__all__ = [
    # Dataset
    "Dataset",
    "DatasetLoadError",
    "Example",
    "ExpectedOutput",
    "load_jsonl",
    # Judge
    "AnthropicBackend",
    "Backend",
    "FAITHFULNESS_RUBRIC",
    "Judge",
    "JudgeParseError",
    "JudgeScore",
    "parse_judge_output",
    # Calibration
    "CalibrationLoadError",
    "CalibrationResult",
    "CalibrationRow",
    "binarize",
    "calibrate",
    "cohens_kappa",
    "load_calibration",
    "pearson_r",
    "render_report",
]

__version__ = "0.0.2"
