"""
How well does the submission workflow agree with the ground truth?

The ground truth applies the same screening rules to the true resume content, so any disagreement
comes from extraction: a missed job bullet, a misread date, a criterion read wrongly from the PDF.
The two error types are not equal for an agency:
- false pass: we'd submit someone who fails a mandatory (wasted submission, hurts credibility)
- false fail: we'd screen out someone who qualifies (lost placement)
"""
from __future__ import annotations

from typing import Any

TOP_N = 3


def _shortlist(rows: list[dict], key_id: str) -> list[str]:
    compliant = [r for r in rows if r["compliance"] == "met"]
    compliant.sort(key=lambda r: (-r["points"], r[key_id]))
    return [r[key_id] for r in compliant[:TOP_N]]


def compare_screening(results: list[dict], expected: list[dict]) -> dict[str, Any]:
    exp = {e["id"]: e for e in expected}
    got = {r["candidate_id"]: r for r in results}
    ids = sorted(set(exp) & set(got))
    false_pass = [i for i in ids if got[i]["compliance"] == "met" and exp[i]["compliance"] != "met"]
    false_fail = [i for i in ids if exp[i]["compliance"] == "met" and got[i]["compliance"] != "met"]
    errors = [abs(got[i]["points"] - exp[i]["points"]) for i in ids]
    top_got, top_exp = _shortlist(results, "candidate_id"), _shortlist(expected, "id")
    return {
        "compliance_accuracy": sum(got[i]["compliance"] == exp[i]["compliance"] for i in ids) / len(ids),
        "points_mae": sum(errors) / len(errors),
        "points_within_5": sum(e <= 5 for e in errors) / len(errors),
        "false_pass": false_pass,
        "false_fail": false_fail,
        "shortlist": top_got,
        "expected_shortlist": top_exp,
        "shortlist_overlap": (len(set(top_got) & set(top_exp)) / len(top_exp)) if top_exp else 1.0,
        "missing_candidates": sorted(set(exp) - set(got)),
    }


def to_markdown(runs: dict[str, dict[str, dict]], extraction: dict[str, float] | None) -> str:
    lines = ["# Submission workflow evaluation", "",
             "Ground truth = the same screening rules applied to the true resume content, so every "
             "difference below comes from extraction.", ""]
    if extraction:
        avg = sum(extraction.values()) / len(extraction)
        lines += [f"**Requirement extraction (criteria read from the RFR PDFs): {avg:.0%} of fields correct**", ""]
    for label, per_req in runs.items():
        if not per_req:
            continue
        n = len(per_req)
        lines += [f"## {label}", "",
                  "| Request | Compliance agreement | Points within ±5 | False passes | False fails | Shortlist overlap (top 3) |",
                  "|---|---|---|---|---|---|"]
        for rid, m in per_req.items():
            lines.append(f"| {rid} | {m['compliance_accuracy']:.0%} | {m['points_within_5']:.0%} | "
                         f"{', '.join(m['false_pass']) or 'none'} | {', '.join(m['false_fail']) or 'none'} | "
                         f"{m['shortlist_overlap']:.0%} |")
        avg = lambda k: sum(m[k] for m in per_req.values()) / n  # noqa: E731
        lines += [f"| **All** | **{avg('compliance_accuracy'):.0%}** | **{avg('points_within_5'):.0%}** | "
                  f"**{sum(len(m['false_pass']) for m in per_req.values())}** | "
                  f"**{sum(len(m['false_fail']) for m in per_req.values())}** | **{avg('shortlist_overlap'):.0%}** |", ""]
    return "\n".join(lines)
