"""
Deterministic candidate-to-job scoring.

The agent never invents a score. It calls a tool, and the tool calls this module, so every
ranking can be explained line by line ("3 of 4 required skills, missing Azure Data Factory").
The weights match the transparent baseline in scripts/generate_synthetic_data.py, which keeps
the agent's rankings comparable to the ground truth.
"""
from __future__ import annotations

from typing import Any

WEIGHTS = {"required": 0.6, "nice": 0.2, "experience": 0.2}
EXPERIENCE_CAP = 1.5  # experience beyond 1.5x the minimum earns no extra credit


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def match(profile: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Explainable fit of one candidate for one job. Uses skills and years only."""
    have = {_norm(s) for s in profile.get("skills") or []}
    req, nice = job.get("required") or [], job.get("nice") or []
    req_hit = [s for s in req if _norm(s) in have]
    nice_hit = [s for s in nice if _norm(s) in have]
    years = profile.get("years_experience")
    min_years = job.get("min_years") or 0

    req_ratio = len(req_hit) / len(req) if req else 1.0
    nice_ratio = len(nice_hit) / len(nice) if nice else 0.0
    if not isinstance(years, (int, float)):
        exp_ratio = 0.0
    elif min_years:
        exp_ratio = min(years / min_years, EXPERIENCE_CAP) / EXPERIENCE_CAP
    else:
        exp_ratio = 1.0

    score = (WEIGHTS["required"] * req_ratio + WEIGHTS["nice"] * nice_ratio
             + WEIGHTS["experience"] * exp_ratio)
    return {
        "candidate_id": profile.get("id"),
        "job_id": job.get("id"),
        "score": round(score, 3),
        "required_matched": req_hit,
        "required_missing": [s for s in req if s not in req_hit],
        "nice_to_have_matched": nice_hit,
        "years_experience": years,
        "min_years": min_years,
        "meets_min_years": isinstance(years, (int, float)) and years >= min_years,
        "same_career_track": profile.get("role_family") == job.get("family"),
    }


def rank(profiles: list[dict[str, Any]], job: dict[str, Any], top: int = 5) -> list[dict[str, Any]]:
    """Score every profile, highest first. Ties broken by candidate ID so results are stable."""
    scored = [match(p, job) for p in profiles]
    scored.sort(key=lambda m: (-m["score"], m["candidate_id"] or ""))
    return scored[:top]
