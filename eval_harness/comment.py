"""Render eval deltas as GitHub-flavored markdown + upsert the sticky PR comment.

Two pieces:

- `render_delta_markdown(report)` — produces a GFM table with a hidden HTML
  sticky-comment marker. Same data as `render_delta_ascii(report)` (in
  `runner.py`), different audience: this output lands as a comment on a
  GitHub PR; the ascii version is for terminals.
- `upsert_sticky_comment(repo, pr, body)` — finds the prior eval-harness
  comment on the PR by HTML marker and edits it; otherwise creates a new
  comment. Marker-based identity (D-009) is reliable across bot renames
  and across consumers calling the same action from different repos.

The HTTP plumbing is `urllib.request` so the module has zero pip-installable
deps; CI passes `GITHUB_TOKEN` (the workflow's automatic token) via env.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from eval_harness.runner import DeltaReport, RowDelta

STICKY_MARKER = "<!-- eval-harness:sticky-comment -->"
"""Hidden HTML marker the bot uses to find its prior comment.

Lives inside the rendered comment body. The find-step does a substring
scan over each comment's body and picks the first one that contains the
marker. Renaming the bot or rotating tokens doesn't break identity.
"""


def render_delta_markdown(report: DeltaReport) -> str:
    """Markdown for the sticky PR comment. Includes the marker.

    The shape:
      `# Eval delta · <suite>`
      summary line (mean Δ + flagged + improved/regressed counts)
      table (status, example_id, baseline, current, delta, flag)
      either "no rows" callout or the per-row table
    """
    summary = report.summary
    # `.get` defaults only on a MISSING key; a present-but-null mean_delta
    # (an undefined mean Δ — e.g. an all-new suite — serialized as JSON null)
    # would reach the `:+.3f` format below and raise TypeError, crashing the
    # whole comment render. Coerce null → 0.0 explicitly; `is not None` (not
    # `or`) so a legitimate falsy 0.0 mean Δ is preserved.
    raw_mean_delta = summary.get("mean_delta", 0.0)
    mean_delta = float(raw_mean_delta) if raw_mean_delta is not None else 0.0
    n_flag = int(summary.get("n_flagged", 0))
    n_reg = int(summary.get("n_regressed", 0))
    n_imp = int(summary.get("n_improved", 0))
    n_new = int(summary.get("n_new", 0))
    n_rem = int(summary.get("n_removed", 0))
    n_same = int(summary.get("n_unchanged", 0))

    lines: list[str] = [STICKY_MARKER, ""]
    lines.append(f"# Eval delta · `{report.suite}`")
    headline_status = "[X]" if n_flag > 0 else "[!]" if n_reg > 0 else "[+]" if n_imp > 0 else "[=]"
    lines.append(
        f"{headline_status} mean Δ **{mean_delta:+.3f}** · "
        f"flagged **{n_flag}** · regressed {n_reg} · improved {n_imp} · "
        f"unchanged {n_same} · new {n_new} · removed {n_rem}"
    )
    lines.append("")
    lines.append(
        f"_current_ `{report.current_run_id[:8]}` vs _baseline_ `{report.baseline_run_id[:8]}` "
        f"· threshold drop: `{report.threshold_drop:.3f}`"
    )
    lines.append("")

    if not report.rows:
        lines.append("_(no rows in either run)_")
        return "\n".join(lines) + "\n"

    lines.append("| status | example_id | baseline | current | Δ | flag |")
    lines.append("| ------ | ---------- | -------: | ------: | -: | :--: |")
    for row in report.rows:
        lines.append(_row_to_md(row))

    lines.append("")
    lines.append(
        "<sub>posted by "
        "[eval-harness](https://github.com/jt-mchorse/llm-eval-harness) · "
        "this comment is updated in-place on every push</sub>"
    )
    return "\n".join(lines) + "\n"


def _row_to_md(r: RowDelta) -> str:
    def fmt(v: float | None) -> str:
        return "—" if v is None else f"{v:.3f}"

    delta_str = "—" if r.delta is None else f"{r.delta:+.3f}"
    flag = ":warning:" if r.flagged else ""
    # Wrap example_id in `code` so multi-word IDs don't break the column.
    return f"| {r.status} | `{r.example_id}` | {fmt(r.baseline_score)} | {fmt(r.current_score)} | {delta_str} | {flag} |"


# ---------------------------------------------------------------------------
# GitHub API plumbing — stdlib-only, GITHUB_TOKEN-driven
# ---------------------------------------------------------------------------

# `repo` is `owner/name`; `pr_number` is the PR number (issue API treats
# PRs as issues for comments).

_GITHUB_API = "https://api.github.com"


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "eval-harness-sticky-comment/1",
    }


def _do_request(
    method: str, url: str, token: str, body: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    data: bytes | None = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, method=method, headers=_auth_headers(token))
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        raise RuntimeError(f"GitHub API {method} {url} -> {e.code}: {err_body}") from e


def find_sticky_comment(
    repo: str,
    pr_number: int,
    *,
    token: str | None = None,
    marker: str = STICKY_MARKER,
    api_base: str = _GITHUB_API,
) -> int | None:
    """Return the id of the prior sticky comment on this PR, or None.

    Paginates through `/issues/<n>/comments` (100 per page) and matches
    bodies against `marker`. First match wins. Pagination caps at 1000
    comments so a runaway query doesn't burn rate limit; if a real PR
    has 1000+ comments this query would need refinement, but that's not
    a portfolio-scale concern today.
    """
    token = _resolve_token(token)
    for page in range(1, 11):
        url = f"{api_base}/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}"
        result = _do_request("GET", url, token)
        items = result if isinstance(result, list) else []
        if not items:
            return None
        for item in items:
            body = item.get("body") or ""
            if marker in body:
                return int(item["id"])
        if len(items) < 100:
            return None
    return None


def upsert_sticky_comment(
    repo: str,
    pr_number: int,
    body: str,
    *,
    token: str | None = None,
    marker: str = STICKY_MARKER,
    api_base: str = _GITHUB_API,
) -> int:
    """Edit the existing sticky comment in place, or create a new one.

    Returns the comment id.
    """
    token = _resolve_token(token)
    # Sanity: refuse to upsert a body that's missing the marker — the next
    # upsert wouldn't find this one and the comment would double.
    if marker not in body:
        raise ValueError("body is missing the sticky marker; refusing to upsert")
    existing_id = find_sticky_comment(
        repo, pr_number, token=token, marker=marker, api_base=api_base
    )
    if existing_id is not None:
        url = f"{api_base}/repos/{repo}/issues/comments/{existing_id}"
        result = _do_request("PATCH", url, token, body={"body": body})
        return int((result if isinstance(result, dict) else {}).get("id", existing_id))
    url = f"{api_base}/repos/{repo}/issues/{pr_number}/comments"
    result = _do_request("POST", url, token, body={"body": body})
    return int((result if isinstance(result, dict) else {}).get("id", 0))


def _resolve_token(token: str | None) -> str:
    if token is not None:
        return token
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not env:
        raise RuntimeError(
            "GitHub token missing: pass `token=` or set GITHUB_TOKEN / GH_TOKEN. "
            "In Actions, `permissions: pull-requests: write` makes this automatic."
        )
    return env
