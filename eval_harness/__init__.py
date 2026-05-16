"""Reusable LLM eval framework.

Public surface:
- Dataset layer (#1, shipped): versioned JSONL goldens with line-number errors.
- Judge wrapper (#2, shipped): LLM-as-judge with calibration against human labels.
- Regression runner (#3, shipped): SQLite-backed run history + per-run diffs.
- Drift detection (#4, shipped): three-axis drift (length / embedding / judge)
  scored via Jensen-Shannon divergence with an HTML report.
- pytest plugin (#5, shipped), GitHub Action (#6, shipped), CLI surface (#7, shipped).
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
from eval_harness.drift import (
    DEFAULT_EMBEDDING_THRESHOLD,
    DEFAULT_JUDGE_THRESHOLD,
    DEFAULT_LENGTH_THRESHOLD,
    AxisReport,
    ClusterStats,
    DriftReport,
    JudgeStats,
    LengthStats,
    RepresentativeExample,
    compute_drift,
    hash_embed,
    jensen_shannon,
)
from eval_harness.drift import (
    render_html as render_drift_html,
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
from eval_harness.runner import (
    DEFAULT_THRESHOLD_DROP,
    AnswerSource,
    DatasetEchoSource,
    DeltaReport,
    RowDelta,
    RowScore,
    RunResult,
    RunSpec,
    diff_runs,
    load_baseline,
    render_delta_ascii,
    render_run_json,
    run_suite,
)
from eval_harness.runs import (
    StoredRun,
    connect,
    init_db,
    init_db_on,
    latest_run_id_for_suite,
    new_run_id,
    read_run,
    utc_now_iso,
    write_run,
)

__all__ = [
    # Dataset
    "Dataset",
    "DatasetLoadError",
    "Example",
    "ExpectedOutput",
    "load_jsonl",
    # Drift
    "AxisReport",
    "ClusterStats",
    "DEFAULT_EMBEDDING_THRESHOLD",
    "DEFAULT_JUDGE_THRESHOLD",
    "DEFAULT_LENGTH_THRESHOLD",
    "DriftReport",
    "JudgeStats",
    "LengthStats",
    "RepresentativeExample",
    "compute_drift",
    "hash_embed",
    "jensen_shannon",
    "render_drift_html",
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
    # Regression runner
    "AnswerSource",
    "DatasetEchoSource",
    "DEFAULT_THRESHOLD_DROP",
    "DeltaReport",
    "RowDelta",
    "RowScore",
    "RunResult",
    "RunSpec",
    "diff_runs",
    "load_baseline",
    "render_delta_ascii",
    "render_run_json",
    "run_suite",
    # Runs persistence
    "StoredRun",
    "connect",
    "init_db",
    "init_db_on",
    "latest_run_id_for_suite",
    "new_run_id",
    "read_run",
    "utc_now_iso",
    "write_run",
]

__version__ = "0.0.3"
