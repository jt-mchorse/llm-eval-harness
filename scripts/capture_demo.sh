#!/usr/bin/env bash
# Deterministic driver for the 60-second README demo (issue #20).
#
# Runs the three highest-leverage surfaces in sequence on a fresh clone
# with no API key:
#
#   1. regression runner + ASCII delta table (examples/regression_run_and_diff.py)
#   2. three-axis drift report (examples/drift_report.py)
#   3. PR sticky-comment flow (eval-harness diff-json --format markdown twice,
#      once on the committed fixtures and once on a synthesized "push 2" current,
#      to show the <!-- eval-harness:sticky-comment --> marker is stable so the
#      bot edits in place on every push)
#
# The output is the recording — when JT records the GIF/video, this script's
# stdout is what gets captured. Hermetic: no API key, no network, no SQLite
# writes outside a tempdir.
#
# Variables:
#   CAPTURE_PACE_SECONDS  pause between sections (default 2 for recording;
#                         test_capture_demo_smoke.py sets this to 0).
#   CAPTURE_OPEN_HTML     if "1", open the drift HTML report with the OS
#                         default opener after step 2 (default: just print
#                         the path). Off in CI.
#
# Exit: 0 on full success; non-zero on any sub-step failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACE="${CAPTURE_PACE_SECONDS:-2}"
OPEN_HTML="${CAPTURE_OPEN_HTML:-0}"

banner() {
  printf '\n'
  printf '═══ %s\n' "$1"
  printf '\n'
}

pace() {
  if [ "$PACE" != "0" ]; then
    sleep "$PACE"
  fi
}

cd "$REPO_ROOT"

banner "llm-eval-harness · 60-second demo"
printf 'three surfaces · stub backends · no API key required\n'
pace

banner "1/3 · regression runner + delta table"
printf 'examples/regression_run_and_diff.py\n'
printf '  baseline + regressed run against the same dataset,\n'
printf '  diff_runs + render_delta_ascii surfaces the dropped row.\n\n'
python -u examples/regression_run_and_diff.py
pace

banner "2/3 · three-axis drift report"
printf 'examples/drift_report.py\n'
printf '  length · embedding-cluster · judge   (JSD per axis)\n'
printf '  single-file HTML written to a tempfile.\n\n'
DRIFT_OUTPUT="$(python -u examples/drift_report.py)"
printf '%s\n' "$DRIFT_OUTPUT"

if [ "$OPEN_HTML" = "1" ]; then
  HTML_PATH="$(printf '%s\n' "$DRIFT_OUTPUT" | sed -n 's/^\[example\] HTML report written to: //p' | tail -n1)"
  if [ -n "$HTML_PATH" ] && [ -f "$HTML_PATH" ]; then
    if command -v open >/dev/null 2>&1; then
      open "$HTML_PATH"
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$HTML_PATH"
    else
      printf '\n(no OS opener found; skipping browser launch)\n'
    fi
  fi
fi
pace

banner "3/3 · PR sticky-comment flow"
printf 'eval-harness diff-json --format markdown   ← what GitHub Actions posts\n'
printf '  committed fixtures: demo_baseline.json → demo_current.json\n'
printf '  the <!-- eval-harness:sticky-comment --> marker is how upsert_sticky_comment\n'
printf '  finds and edits the prior comment in place on every push.\n\n'
printf '─── push #1: initial regression ─────────────────────────────────────\n\n'
# `|| true`: diff-json exits non-zero when any row is flagged; that is the
# regression signal the workflow forwards via its own exit status. Here we
# want the rendered markdown to print regardless of flag status.
eval-harness diff-json \
  --current  fixtures/demo_current.json \
  --baseline fixtures/demo_baseline.json \
  --format   markdown \
  || true
pace

printf '\n─── push #2: same PR, one row recovered ─────────────────────────────\n\n'
# Synthesize an "improved" current by bumping the worst-scoring row's score
# above the threshold; then re-render. The marker line is identical in both
# renderings — that is the entire point of D-009 (marker-based identity, not
# comment-id-based) — so the action edits the same comment instead of stacking
# duplicates across pushes.
TMP_CURRENT="$(mktemp -t eval-harness-capture-push2-XXXXXX.json)"
python -u - "$TMP_CURRENT" <<'PY'
import json
import sys
from pathlib import Path

src = json.loads(Path("fixtures/demo_current.json").read_text())
# Bump the lowest-scoring row above the regression threshold so push #2
# shows a clean comment: the row that was flagged on push #1 is now green.
worst = min(src["rows"], key=lambda r: r["score"])
old_score = worst["score"]
worst["score"] = min(1.0, round(old_score + 0.6, 3))
worst["reasoning"] = "Author addressed reviewer feedback on push #2."
src["run_id"] = src["run_id"] + "_push2"
src["mean_score"] = round(sum(r["score"] for r in src["rows"]) / len(src["rows"]), 3)
Path(sys.argv[1]).write_text(json.dumps(src, indent=2))
print(f"[capture] synthesized push-2 current: bumped {worst['example_id']!r} "
      f"from {old_score:.3f} → {worst['score']:.3f}")
PY
printf '\n'
eval-harness diff-json \
  --current  "$TMP_CURRENT" \
  --baseline fixtures/demo_baseline.json \
  --format   markdown \
  || true
rm -f "$TMP_CURRENT"
pace

banner "demo complete"
printf 'all three surfaces ran end-to-end with zero API calls.\n'
printf 'recapture: scripts/capture_demo.sh (env: CAPTURE_PACE_SECONDS, CAPTURE_OPEN_HTML).\n'
