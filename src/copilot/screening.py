"""
Screen candidates against a public-sector style Request for Resumes (RFR).

How these evaluations usually work, and what this module reproduces:
- Mandatory criteria are pass/fail. Fail one and the candidate is not compliant, however strong
  they are elsewhere.
- Rated criteria earn points, usually in proportion to demonstrated years of experience.
- "Demonstrated" means shown in a dated role on the resume (see evidence.py). A skill that is only
  listed earns nothing until a recruiter confirms it, so it is flagged "verify".

Everything here is deterministic: the same resume and requirement always give the same result.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from copilot.evidence import evidence_for

MET, NOT_MET, VERIFY = "met", "not_met", "verify"


def _listed(profile: dict, skills: list[str]) -> list[str]:
    have = {s.strip().lower() for s in profile.get("skills") or []}
    return [s for s in skills if s.strip().lower() in have]


def evaluate_criterion(criterion: dict, kind: str, profile: dict, today: date | None = None) -> dict[str, Any]:
    """kind is 'mandatory' or 'rated'."""
    ev = evidence_for(profile.get("work_history") or [], criterion.get("skills") or [], today)
    listed = _listed(profile, criterion.get("skills") or [])
    months = ev["months"]
    out = {
        "id": criterion["id"],
        "kind": kind,
        "text": criterion.get("text"),
        "skills": criterion.get("skills") or [],
        "evidence_months": months,
        "evidence_years": round(months / 12, 1),
        "evidence": ev["jobs"],
        "listed_in_skills": listed,
    }
    if kind == "mandatory":
        need = (criterion.get("min_years") or 0) * 12
        if ev["jobs"] and months >= need:
            out["status"] = MET
        elif listed and not ev["jobs"]:
            out["status"] = VERIFY      # claimed but not shown in any role
        else:
            out["status"] = NOT_MET
        out["required_years"] = criterion.get("min_years") or 0
    else:
        target = criterion.get("target_years") or 0
        maxp = criterion.get("points") or 0
        if ev["jobs"]:
            ratio = min(1.0, months / (target * 12)) if target else 1.0
            out["status"] = MET if ratio >= 1 else "partial"
        else:
            ratio = 0.0
            out["status"] = VERIFY if listed else NOT_MET
        out["points_awarded"] = round(maxp * ratio, 1)
        out["points_max"] = maxp
        out["target_years"] = target
    return out


def evaluate_candidate(requirement: dict, profile: dict, today: date | None = None) -> dict[str, Any]:
    mand = [evaluate_criterion(c, "mandatory", profile, today) for c in requirement.get("mandatory") or []]
    rated = [evaluate_criterion(c, "rated", profile, today) for c in requirement.get("rated") or []]
    statuses = {m["status"] for m in mand}
    compliance = (NOT_MET if NOT_MET in statuses else VERIFY if VERIFY in statuses else MET)
    return {
        "candidate_id": profile.get("id"),
        "requirement_id": requirement.get("id"),
        "compliance": compliance,          # met | verify | not_met
        "mandatory": mand,
        "rated": rated,
        "points": round(sum(r["points_awarded"] for r in rated), 1),
        "points_max": sum(r["points_max"] for r in rated),
    }


def screen(requirement: dict, profiles: list[dict], today: date | None = None) -> list[dict[str, Any]]:
    """Evaluate every profile. Compliant first, then 'verify', then the rest; by points within each."""
    order = {MET: 0, VERIFY: 1, NOT_MET: 2}
    results = [evaluate_candidate(requirement, p, today) for p in profiles]
    results.sort(key=lambda r: (order[r["compliance"]], -r["points"], r["candidate_id"] or ""))
    return results
