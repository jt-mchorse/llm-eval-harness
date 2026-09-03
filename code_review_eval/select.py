"""Filter mined candidates down to the human-verified golden set.

The miner produces candidates. It cannot produce a golden set on its own -
two independent passes over psf/requests both emitted rows whose label was
wrong (a comment typo reversed into "a defect"; a setattr rewrite whose
reversal is functionally identical). Every accepted row below was read as a
diff by a human before it entered the dataset, and every rejection is
recorded in VERIFICATION.md with its reason.

Single-labeler verification. That is a real limitation and it is disclosed
rather than hidden - see the calibration note in the case study.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--accept", required=True, type=Path,
                    help="one candidate id per line; '#' comments allowed")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    accept: list[str] = []
    for ln in a.accept.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            accept.append(ln)

    by_id = {}
    for ln in a.candidates.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            by_id[r["id"]] = r

    missing = [i for i in accept if i not in by_id]
    if missing:
        print(f"ERROR: accepted ids not found in candidates: {missing}", file=sys.stderr)
        return 2

    rows, n_def, n_clean = [], 0, 0
    for cid in accept:
        r = dict(by_id[cid])
        if "defect" in r["tags"]:
            n_def += 1
            r["id"] = f"cr_defect_{n_def:02d}"
        else:
            n_clean += 1
            r["id"] = f"cr_clean_{n_clean:02d}"
        r["provenance"] = dict(r["provenance"])
        r["provenance"]["verified"] = "human read the diff and confirmed the label"
        rows.append(r)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(f"accepted defects={n_def} clean={n_clean} total={len(rows)} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
