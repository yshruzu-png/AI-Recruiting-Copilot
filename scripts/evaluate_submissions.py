"""
Score the submission workflow against the ground truth. No model calls; screening is deterministic.
Writes docs/eval/submission_report.md.

Two runs, so a mistake can be traced to its stage:
  1. True criteria + extracted resumes        -> measures resume extraction only
  2. Extracted criteria + extracted resumes   -> end to end (needs scripts/extract_requirements.py)

Usage: python scripts/evaluate_submissions.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent_tools import load_profiles, stale_profiles  # noqa: E402
from copilot.requirements import compare_requirement, load_requirements  # noqa: E402
from copilot.screening import screen  # noqa: E402
from copilot.submission_eval import compare_screening, to_markdown  # noqa: E402


def main() -> None:
    gt = json.loads((ROOT / "data" / "synthetic" / "ground_truth.json").read_text())
    expected = {r["id"]: r["expected"] for r in gt.get("requests", [])}
    if not expected:
        sys.exit("ground_truth.json has no requests. Re-run scripts/generate_synthetic_data.py.")
    loaded = load_profiles()
    if not loaded:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    stale = stale_profiles(loaded)
    if stale:
        print(f"WARNING: stale profiles without job highlights: {', '.join(stale)}. "
              f"Re-run: python scripts/extract_resumes.py --only {' '.join(stale)}\n")
    profiles = list(loaded.values())

    truth, extracted = load_requirements("truth"), load_requirements("extracted")
    runs = {"1. True criteria, extracted resumes (resume extraction only)": {},
            "2. Extracted criteria, extracted resumes (end to end)": {}}
    labels = list(runs)
    for rid, req in truth.items():
        runs[labels[0]][rid] = compare_screening(screen(req, profiles), expected[rid])
        if rid in extracted:
            runs[labels[1]][rid] = compare_screening(screen(extracted[rid], profiles), expected[rid])
    extraction = {rid: compare_requirement(extracted[rid], truth[rid])["accuracy"] for rid in extracted if rid in truth}

    for label, per_req in runs.items():
        if not per_req:
            print(f"{label}: skipped (run scripts/extract_requirements.py)")
            continue
        n = len(per_req)
        print(label)
        for rid, m in per_req.items():
            print(f"  {rid}  compliance {m['compliance_accuracy']:.0%}  points±5 {m['points_within_5']:.0%}  "
                  f"false pass {len(m['false_pass'])}  false fail {len(m['false_fail'])}  "
                  f"shortlist {m['shortlist_overlap']:.0%}")
        print(f"  ALL     compliance {sum(m['compliance_accuracy'] for m in per_req.values()) / n:.0%}\n")
    out = ROOT / "docs" / "eval" / "submission_report.md"
    out.write_text(to_markdown(runs, extraction), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
