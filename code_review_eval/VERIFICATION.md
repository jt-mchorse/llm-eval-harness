# Verification record — `code-review-v1`

Every row in `fixtures/code_review_v1.jsonl` was read as a diff before it entered
the dataset. This file records what was accepted, what was rejected, and why.

Single-labeler verification. That is a real limitation — see *Calibration* in the
case study — and it is disclosed rather than papered over.

## Method

- **Defect rows** — an upstream bug-fix commit from `psf/requests`, diff reversed.
  The result reintroduces a defect the project itself identified and fixed. Ground
  truth is the upstream commit message; anyone can check the cited SHA.
- **Clean rows** — documentation-only commits, applied forward. Nothing to flag.
  These carry the false-positive signal.

## Accepted — 12 defect rows

| id | upstream fix | what the reversal reintroduces |
|---|---|---|
| 01 | proxy_bypass_registry returning true | `filter(None, ...)` removed, so empty strings match everything |
| 02 | response with utf8 bom | `utf-8-sig` handling removed, BOM leaks into decoded text |
| 03 | prefix comparison in `get_adapter()` | `prefix.lower()` dropped, lookup becomes case-sensitive |
| 04 | parse_header_links on empty header | empty-header guard removed |
| 05 | OPENSSL_VERSION_NUMBER on py2.6 | `getattr` guard removed, AttributeError |
| 06 | Transfer-Encoding chunked | `if length is not None` → `if length`, zero mishandled |
| 07 | super_len for partially read files | early return reports wrong length |
| 08 | proxy-selecting logic | scheme+host selection collapsed to scheme only |
| 09 | HTTPDigestAuth non-file bodies | `self.pos = None` reset removed, stale position reused |
| 10 | session.cookies not a RequestsCookieJar | merge reverts to `copy()` + `set_cookie` |
| 11 | off-by-one on max_redirects | `>=` becomes `>` |
| 12 | chardet on Python 3 | `sys.path` hack reintroduced |

## Rejected

| candidate | upstream subject | why rejected |
|---|---|---|
| — | Fix typos discovered by codespell | comment typo in a test file. Reversed, it is a misspelled comment, not a defect. The filter said `\btypo\b`, which does not match "typos" |
| — | Fix an invalid escape sequence | changes only a docstring prefix (`r"""` → `"""`). Produces a warning, not incorrect runtime behavior |
| — | Fix bug in renegotiating a nonce | reversal swaps `self.x = v` for `setattr(self, 'x', v)` — functionally identical, so no defect is reintroduced |
| — | Fix broken link / intersphinx_mapping | `docs/conf.py`. A `.py` file, but not library code |
| — | fix: Remove '<4' from python_requires | `setup.py` packaging metadata, not runtime |
| — | fix flake8 indent error / fix spaces | lint and whitespace |
| — | `fix` / `fix models.py` / `fix adapters.py` | no description of what broke, so nothing can ground the label |
| — | Fix kennethreitz/requests#790, Fix for issue #1280 | issue reference only, no defect description |
| — | Fix failing test ... / Fix test bug | the label would be "a test failed", not a runtime defect |

## What this cost the design

Two independent mining passes both emitted mislabeled rows. The lesson is
recorded in the miner itself rather than only here:

1. **Message filters are necessary but not sufficient.** A commit can be honestly
   titled "fix X" and still touch only comments. `changes_executable_code()` now
   requires at least one changed line that is not blank, a comment, or a bare
   string literal.
2. **A subject must name the defect.** `subject_has_substance()` strips the verb,
   PR ref, and filename, then requires what remains to be at least three words.
3. **Mining produces candidates, not a golden set.** The accept list in
   `accepted.txt` is the actual dataset boundary, and it is a human artifact.
