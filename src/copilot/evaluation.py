"""Compare extracted candidate profiles with the synthetic ground truth."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().strip(".").lower()


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3)}


class _SetScore:
    """Micro-averaged precision/recall over sets (e.g. skills across all resumes)."""

    def __init__(self):
        self.tp = self.fp = self.fn = 0

    def add(self, predicted, expected) -> tuple[set, set]:
        p, e = {norm(x) for x in predicted or []}, {norm(x) for x in expected or []}
        self.tp += len(p & e)
        self.fp += len(p - e)
        self.fn += len(e - p)
        return p - e, e - p  # extra, missing

    def result(self):
        return prf(self.tp, self.fp, self.fn)


def evaluate(profiles: dict[str, dict], truth: list[dict]) -> dict[str, Any]:
    exact = defaultdict(lambda: [0, 0])  # metric -> [correct, total]
    skills, certs = _SetScore(), _SetScore()
    skills_by_format: dict[str, _SetScore] = defaultdict(_SetScore)
    flags = {k: [0, 0, 0] for k in ("date_of_birth", "marital_status", "photo")}  # tp, fp, fn
    errors: list[dict] = []
    missing_profiles = []

    def check(metric: str, ok: bool):
        exact[metric][0] += int(ok)
        exact[metric][1] += 1

    for gt in truth:
        prof = profiles.get(gt["id"])
        if prof is None:
            missing_profiles.append(gt["id"])
            continue
        issues = []

        name_ok = norm(prof.get("name")) == norm(gt["name"])
        check("name", name_ok)
        check("email", norm(prof.get("email")) == norm(gt["email"]))
        role_ok = prof.get("role_family") == gt["family"]
        check("role_family", role_ok)
        if not role_ok:
            issues.append(f"role_family: got {prof.get('role_family')!r}, expected {gt['family']!r}")
        check("job_count", len(prof.get("work_history") or []) == gt["num_roles"])

        yrs = prof.get("years_experience")
        check("years_exact", yrs == gt["years_experience"])
        within = isinstance(yrs, (int, float)) and abs(yrs - gt["years_experience"]) <= 1
        check("years_within_1", within)
        if not within:
            issues.append(f"years: got {yrs}, expected {gt['years_experience']}")
        model_yrs = prof.get("years_experience_model")
        if model_yrs is not None:  # how good is the LLM's own estimate, for comparison?
            check("years_model_within_1", isinstance(model_yrs, (int, float))
                  and abs(model_yrs - gt["years_experience"]) <= 1)

        edu_pred = norm((prof.get("education") or [{}])[0].get("Degree"))
        check("degree", edu_pred == norm(gt["education"][0]["degree"]))

        extra, missing = skills.add(prof.get("skills"), gt["skills"])
        skills_by_format[gt["format"]].add(prof.get("skills"), gt["skills"])
        if extra or missing:
            issues.append(f"skills extra={sorted(extra)} missing={sorted(missing)}")
        c_extra, c_missing = certs.add(prof.get("certifications"), gt["certifications"])
        if c_extra or c_missing:
            issues.append(f"certs extra={sorted(c_extra)} missing={sorted(c_missing)}")

        for flag, counts in flags.items():
            expected = flag in gt["protected_info"] or (flag == "photo" and "photo_note" in gt["protected_info"])
            got = bool((prof.get("protected_flags") or {}).get(flag))
            counts[0] += int(got and expected)
            counts[1] += int(got and not expected)
            counts[2] += int(expected and not got)
            if got != expected:
                issues.append(f"{flag}: got {got}, expected {expected}")

        if not name_ok:
            issues.append(f"name: got {prof.get('name')!r}, expected {gt['name']!r}")
        if issues:
            errors.append({"id": gt["id"], "format": gt["format"], "issues": issues})

    return {
        "evaluated": len(truth) - len(missing_profiles),
        "missing_profiles": missing_profiles,
        "accuracy": {k: round(c / t, 3) for k, (c, t) in exact.items()},
        "skills": skills.result(),
        "skills_by_format": {f: s.result() for f, s in sorted(skills_by_format.items())},
        "certifications": certs.result(),
        "protected_flags": {k: prf(*v) for k, v in flags.items()},
        "errors": errors,
    }


def to_markdown(report: dict[str, Any]) -> str:
    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    lines = [
        "# Resume extraction evaluation",
        "",
        f"Resumes evaluated: **{report['evaluated']}**"
        + (f" (missing: {', '.join(report['missing_profiles'])})" if report["missing_profiles"] else ""),
        "",
        "## Field accuracy",
        "",
        "| Field | Accuracy |",
        "|---|---|",
    ]
    labels = {"name": "Candidate name", "email": "Email", "role_family": "Role family (classify)",
              "job_count": "Number of jobs", "years_exact": "Years of experience (exact)",
              "years_within_1": "Years of experience (within 1 year), calculated in code",
              "years_model_within_1": "Years of experience (within 1 year), model's own estimate",
              "degree": "Degree"}
    for key, label in labels.items():
        if key in report["accuracy"]:
            lines.append(f"| {label} | {pct(report['accuracy'][key])} |")

    lines += ["", "## List fields (micro-averaged)", "", "| Field | Precision | Recall | F1 |", "|---|---|---|---|"]
    for label, key in (("Skills", "skills"), ("Certifications", "certifications")):
        m = report[key]
        lines.append(f"| {label} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} |")

    lines += ["", "## Skills F1 by file format", "", "| Format | F1 |", "|---|---|"]
    lines += [f"| {f} | {pct(m['f1'])} |" for f, m in report["skills_by_format"].items()]

    lines += ["", "## Protected-information detection (for blind screening)", "",
              "| Flag | Precision | Recall |", "|---|---|---|"]
    for flag, m in report["protected_flags"].items():
        lines.append(f"| {flag.replace('_', ' ')} | {pct(m['precision'])} | {pct(m['recall'])} |")

    lines += ["", f"## Resumes with at least one mismatch ({len(report['errors'])})", ""]
    for e in report["errors"]:
        lines.append(f"- **{e['id']}** ({e['format']}): " + "; ".join(e["issues"]))
    return "\n".join(lines) + "\n"


def search_metrics(results: dict[str, list[str]], jobs: list[dict], truth: list[dict], k: int = 5) -> dict[str, Any]:
    """
    results: job id -> ranked candidate ids returned by search.
    - family_precision@k: share of the top k whose real career track matches the job (objective)
    - baseline_overlap@10: share of the transparent skill-overlap baseline's top 10 that search also
      returned in its top 10 (agreement, not ground truth)
    """
    family = {c["id"]: c["family"] for c in truth}
    per_job, fam_scores, overlaps = [], [], []
    for job in jobs:
        ranked = results.get(job["id"], [])
        top_k = ranked[:k]
        fam = sum(family.get(c) == job["family"] for c in top_k) / k
        base = {b["id"] for b in job["baseline_top10"]}
        overlap = len(base & set(ranked[:10])) / len(base) if base else 0.0
        fam_scores.append(fam)
        overlaps.append(overlap)
        per_job.append({"id": job["id"], "title": job["title"], f"family_precision@{k}": round(fam, 3),
                        "baseline_overlap@10": round(overlap, 3), "top": top_k})
    n = len(jobs) or 1
    return {f"family_precision@{k}": round(sum(fam_scores) / n, 3),
            "baseline_overlap@10": round(sum(overlaps) / n, 3), "jobs": per_job, "k": k}


def search_to_markdown(m: dict[str, Any]) -> str:
    k = m["k"]
    lines = ["# Candidate search evaluation", "",
             "Each job description is used as the search query (hybrid: keyword + vector).", "",
             f"- **Family precision@{k}:** {m[f'family_precision@{k}']:.0%} of the top {k} candidates are in the job's career track",
             f"- **Baseline overlap@10:** {m['baseline_overlap@10']:.0%} agreement with a transparent skill-overlap baseline", "",
             f"| Job | Family precision@{k} | Baseline overlap@10 | Top {k} |", "|---|---|---|---|"]
    for j in m["jobs"]:
        lines.append(f"| {j['id']} {j['title']} | {j[f'family_precision@{k}']:.0%} | "
                     f"{j['baseline_overlap@10']:.0%} | {', '.join(j['top'])} |")
    return "\n".join(lines) + "\n"
