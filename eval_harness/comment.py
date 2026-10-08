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

from eval_harness.comparison import render_configured, render_signed_classified
from eval_harness.io_utils import loads_json
from eval_harness.markdown import md_code_cell, md_code_span, md_table_cell
from eval_harness.runner import DeltaReport, RowDelta

STICKY_MARKER = "<!-- eval-harness:sticky-comment -->"

# GitHub refuses an issue comment longer than 65,536 characters with a 422
# ("Body is too long"), on POST and on the PATCH that updates the sticky
# comment in place (#312). The budget is measured in UTF-8 *bytes*, which is
# never less than the character count however GitHub counts, with headroom
# for the footer and the omission line.
COMMENT_BODY_BUDGET = 65_000

# Which rows a capped comment keeps first. The flagged rows are the verdict;
# unchanged rows are the ones a reader loses least by not seeing.
_KEEP_ORDER: dict[str, int] = {
    "regressed": 1,
    "new": 2,
    "removed": 3,
    "improved": 4,
    "unchanged": 5,
}
"""Hidden HTML marker the bot uses to find its prior comment.

Lives inside the rendered comment body. The find-step does a substring
scan over each comment's body and picks the first one that contains the
marker. Renaming the bot or rotating tokens doesn't break identity.
"""


def render_delta_markdown(report: DeltaReport, *, max_bytes: int | None = None) -> str:
    """Markdown for the sticky PR comment. Includes the marker.

    The shape:
      `# Eval delta · <suite>`
      summary line (mean Δ + flagged + improved/regressed counts)
      table (status, example_id, baseline, current, delta, flag)
      either "no rows" callout or the per-row table

    ``max_bytes`` caps the UTF-8 size of the result (``comment`` passes
    :data:`COMMENT_BODY_BUDGET`; the ``diff-json`` markdown output is
    uncapped). Under the cap the output is unchanged. Over it, rows are kept
    flagged first, then regressed / new / removed / improved, then unchanged,
    still rendered in their original order, and a line after the table says
    how many rows of each status were left out (#312). Without it a suite of
    roughly 1,100 rows could never post its comment, and a PR whose earlier,
    smaller run had posted one kept that stale verdict.
    """
    summary = report.summary
    # `.get` defaults only on a MISSING key; a present-but-null mean_delta
    # (an undefined mean Δ — e.g. an all-new suite — serialized as JSON null)
    # would reach the `:+.3f` format below and raise TypeError, crashing the
    # whole comment render. Coerce null → 0.0 explicitly; `is not None` (not
    # `or`) so a legitimate falsy 0.0 mean Δ is preserved.
    raw_mean_delta = summary.get("mean_delta", 0.0)
    mean_delta = float(raw_mean_delta) if raw_mean_delta is not None else 0.0

    # The sibling count fields were left with bare `int(...)`, so a present-but-null
    # count (an undefined count serialized as JSON null, the same shape as the
    # null mean_delta handled above) reached `int(None)` and raised a TypeError —
    # crashing the whole comment render and escaping `_run_comment` as exit 1 (it
    # catches ValueError/KeyError, not TypeError). Coerce null → 0 like mean_delta.
    def _count(key: str) -> int:
        v = summary.get(key)
        return int(v) if v is not None else 0

    n_flag = _count("n_flagged")
    n_reg = _count("n_regressed")
    n_imp = _count("n_improved")
    n_new = _count("n_new")
    n_rem = _count("n_removed")
    n_same = _count("n_unchanged")

    lines: list[str] = [STICKY_MARKER, ""]
    # `suite` is a free-form operator-chosen name; a backtick in it closes this
    # heading's code span early (#180 fixed the same class in the table cells but
    # not this non-table span). `md_code_span` neutralizes the backtick without
    # pipe-escaping (a `\|` would render literal outside a table).
    lines.append(f"# Eval delta · {md_code_span(report.suite)}")
    headline_status = "[X]" if n_flag > 0 else "[!]" if n_reg > 0 else "[+]" if n_imp > 0 else "[=]"
    lines.append(
        f"{headline_status} mean Δ **{mean_delta:+.3f}** · "
        f"flagged **{n_flag}** · regressed {n_reg} · improved {n_imp} · "
        f"unchanged {n_same} · new {n_new} · removed {n_rem}"
    )
    lines.append("")
    # The run ids load from the delta JSON (hand-editable); a backtick in the
    # first 8 chars breaks these code spans just like the suite heading above.
    # `threshold_drop` is a formatted float — no backtick possible — so it stays raw.
    # It is also the operator's configured `--threshold-drop`, and a fixed `.3f`
    # republished `0.0125` as `0.013` here while the ASCII header said `0.01`
    # (#257). `render_configured` widens from three places only as far as the
    # round trip requires, so the shipped default still publishes `0.100`.
    lines.append(
        f"_current_ {md_code_span(report.current_run_id[:8])} "
        f"vs _baseline_ {md_code_span(report.baseline_run_id[:8])} "
        f"· threshold drop: `{render_configured(report.threshold_drop)}`"
    )
    lines.append("")

    if not report.rows:
        lines.append("_(no rows in either run)_")
        return "\n".join(lines) + "\n"

    lines.append("| status | example_id | baseline | current | Δ | flag |")
    lines.append("| ------ | ---------- | -------: | ------: | -: | :--: |")
    footer = [
        "",
        "<sub>posted by "
        "[eval-harness](https://github.com/jt-mchorse/llm-eval-harness) · "
        "this comment is updated in-place on every push</sub>",
    ]
    rendered = [_row_to_md(row, report.threshold_drop) for row in report.rows]
    full = "\n".join([*lines, *rendered, *footer]) + "\n"
    if max_bytes is None or len(full.encode("utf-8")) <= max_bytes:
        return full
    kept = _rows_within_budget(report.rows, rendered, lines, footer, max_bytes)
    omitted: dict[str, int] = {}
    for i, row in enumerate(report.rows):
        if i not in kept:
            omitted[row.status] = omitted.get(row.status, 0) + 1
    lines.extend(rendered[i] for i in sorted(kept))
    lines.append("")
    lines.append(_omission_line(omitted, len(report.rows)))
    return "\n".join([*lines, *footer]) + "\n"


def _omission_line(omitted: dict[str, int], n_rows: int) -> str:
    parts = ", ".join(
        f"{n} {status}"
        for status, n in sorted(omitted.items(), key=lambda kv: _KEEP_ORDER.get(kv[0], 9))
    )
    total = sum(omitted.values())
    return (
        f"_{total} of {n_rows} rows not shown ({parts}): GitHub caps a comment at "
        "65,536 characters. `eval-harness diff-json --format markdown` prints the "
        "full table._"
    )


def _rows_within_budget(
    rows: list[RowDelta] | tuple[RowDelta, ...],
    rendered: list[str],
    head: list[str],
    footer: list[str],
    max_bytes: int,
) -> set[int]:
    """Indices of the rows to keep, highest priority first, within ``max_bytes``.

    The omission line is reserved at its longest possible size first, so adding
    it after the choice cannot push the body back over the cap.
    """
    worst_line = _omission_line({status: len(rows) for status in _KEEP_ORDER}, len(rows))
    used = len(("\n".join([*head, "", worst_line, *footer]) + "\n").encode("utf-8"))
    order = sorted(
        range(len(rows)),
        key=lambda i: (0 if rows[i].flagged else _KEEP_ORDER.get(rows[i].status, 9), i),
    )
    kept: set[int] = set()
    for i in order:
        cost = len(rendered[i].encode("utf-8")) + 1  # its newline
        if used + cost > max_bytes:
            break
        kept.add(i)
        used += cost
    return kept


def _row_to_md(r: RowDelta, threshold_drop: float) -> str:
    def fmt(v: float | None) -> str:
        return "—" if v is None else f"{v:.3f}"

    # Beside its `:warning:` and its status, so it may not read as the other
    # verdict: two rows both showing `-0.100`, one flagged (#291).
    delta_str = (
        "—" if r.delta is None else render_signed_classified(r.delta, (0.0, -threshold_drop))
    )
    flag = ":warning:" if r.flagged else ""
    # Wrap example_id in `code` so multi-word IDs stay legible — but backticks
    # protect neither GFM table delimiter: a literal `|` injects an extra column
    # (#130) and a literal newline splits the row across two physical lines
    # (#142), both before inline-code spans are parsed. AND a backtick in the id
    # closes the wrapping code span early, splitting it and leaking the middle out
    # as prose (#180). `md_code_cell` escapes the pipe, collapses any CR/LF run,
    # neutralizes interior backticks, and wraps the result in a single span.
    # `status` is free-form too (it round-trips through externally-produced delta
    # JSON, e.g. a hand-edited or CI-generated DeltaReport), so it defends the
    # same two GFM delimiters as `example_id`: an unescaped `|` injects an extra
    # column and a literal newline splits the row across two physical lines. It is
    # NOT wrapped in a code span, so `md_table_cell` (no backtick pass) suffices.
    example_id = md_code_cell(r.example_id)
    status = md_table_cell(r.status)
    return f"| {status} | {example_id} | {fmt(r.baseline_score)} | {fmt(r.current_score)} | {delta_str} | {flag} |"


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
            return loads_json(raw) if raw else {}
    except error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        raise RuntimeError(f"GitHub API {method} {url} -> {e.code}: {err_body}") from e
    # The rest of what talking to GitHub can raise, onto the same RuntimeError
    # the CLI translates to exit 2 (#303). Only HTTPError was caught, so a
    # refused connection, a timeout or a proxy's HTML page under a 200 escaped
    # as a traceback at exit 1 -- the code that means "a regression was
    # flagged". After the HTTPError arm: HTTPError is a URLError, which is an
    # OSError, as are TimeoutError and ConnectionResetError.
    except OSError as e:
        reason = e.reason if isinstance(e, error.URLError) else e
        raise RuntimeError(f"GitHub API {method} {url} failed: {reason}") from e
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"GitHub API {method} {url} returned a body that is not JSON: {e}"
        ) from e


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
