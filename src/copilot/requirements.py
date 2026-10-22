"""Turn a Content Understanding result for a Request for Resumes into clean, scoreable criteria."""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from copilot.profiles import unwrap

ROOT = Path(__file__).resolve().parents[2]


def _num(v: Any) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        m = re.search(r"\d+(\.\d+)?", str(v))
        return float(m.group()) if m else 0.0


def _clean_num(v: Any) -> int | float:
    n = _num(v)
    return int(n) if n == int(n) else n


def normalize_skill(term: str, vocabulary: list[str], cutoff: float = 0.88) -> str:
    """
    Map a term from the requirement onto the talent pool's own skill names, so "Azure Datafactory"
    matches resumes that say "Azure Data Factory". Unknown terms are kept as written.
    """
    t = term.strip()
    by_lower = {v.lower(): v for v in vocabulary}
    if t.lower() in by_lower:
        return by_lower[t.lower()]
    close = difflib.get_close_matches(t.lower(), list(by_lower), n=1, cutoff=cutoff)
    if close:
        return by_lower[close[0]]
    # "Zero Trust policies" -> "Zero Trust": the longest pool skill contained as a whole term
    inside = [v for v in vocabulary if re.search(rf"(?<![\w]){re.escape(v.lower())}(?![\w])", t.lower())]
    return max(inside, key=len) if inside else t


def _criteria(items: list[dict] | None, prefix: str, vocabulary: list[str], rated: bool) -> list[dict]:
    out = []
    for i, c in enumerate(items or [], start=1):
        skills = [normalize_skill(s, vocabulary) for s in c.get("Skills") or [] if isinstance(s, str) and s.strip()]
        crit = {"id": (c.get("CriterionId") or f"{prefix}{i}").strip().rstrip("."),
                "text": (c.get("Text") or "").strip(),
                "skills": list(dict.fromkeys(skills))}
        if rated:
            crit["target_years"] = _clean_num(c.get("TargetYears"))
            crit["points"] = _clean_num(c.get("Points"))
        else:
            crit["min_years"] = _clean_num(c.get("MinimumYears"))
        out.append(crit)
    return out


def to_requirement(request_id: str, cu_result: dict[str, Any], vocabulary: list[str]) -> dict[str, Any]:
    contents = cu_result.get("contents") or [{}]
    v = {name: unwrap(f) for name, f in contents[0].get("fields", {}).items()}
    return {
        "id": (v.get("RequestId") or request_id).strip(),
        "title": v.get("Title"),
        "client": v.get("Client"),
        "term": v.get("Term"),
        "location": v.get("Location"),
        "positions": int(_num(v.get("Positions")) or 1),
        "mandatory": _criteria(v.get("MandatoryCriteria"), "M", vocabulary, rated=False),
        "rated": _criteria(v.get("RatedCriteria"), "R", vocabulary, rated=True),
    }


def skill_vocabulary(profiles: dict[str, dict] | list[dict]) -> list[str]:
    items = profiles.values() if isinstance(profiles, dict) else profiles
    return sorted({s for p in items for s in p.get("skills") or []})


def load_requirements(source: str = "extracted") -> dict[str, dict[str, Any]]:
    """'extracted' = Content Understanding output in data/extracted/requests/; 'truth' = the generator's."""
    if source == "truth":
        gt = json.loads((ROOT / "data" / "synthetic" / "ground_truth.json").read_text(encoding="utf-8"))
        return {r["id"]: {k: v for k, v in r.items() if k != "expected"} for r in gt.get("requests", [])}
    folder = ROOT / "data" / "extracted" / "requests"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("RFR-*.json"))}


def compare_requirement(extracted: dict, truth: dict) -> dict[str, Any]:
    """Field-by-field check of one extracted request against the generator's truth."""
    def norm(s):
        return {x.lower() for x in s}

    checks: dict[str, bool] = {"title": (extracted.get("title") or "").strip().lower() == (truth.get("title") or "").lower()}
    for kind, num_key in (("mandatory", "min_years"), ("rated", "target_years")):
        got = {c["id"]: c for c in extracted.get(kind) or []}
        for t in truth.get(kind) or []:
            g = got.get(t["id"])
            checks[f"{t['id']} found"] = g is not None
            if g is None:
                continue
            checks[f"{t['id']} skills"] = norm(g["skills"]) == norm(t["skills"])
            checks[f"{t['id']} {num_key}"] = _num(g.get(num_key)) == _num(t.get(num_key))
            if kind == "rated":
                checks[f"{t['id']} points"] = _num(g.get("points")) == _num(t.get("points"))
        checks[f"no extra {kind}"] = len(got) == len(truth.get(kind) or [])
    return {"id": truth["id"], "checks": checks, "accuracy": sum(checks.values()) / len(checks)}
