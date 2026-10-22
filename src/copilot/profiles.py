"""Turn raw Content Understanding output into a clean candidate profile dict."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from copilot.catalog import clean_certifications

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_month(text: Any, today: date) -> int | None:
    """'Mar 2023' / 'March 2023' / '03/2023' / 'Present' -> months since year 0, or None."""
    t = str(text or "").strip().lower()
    if t in ("present", "current", "now", "today"):
        return today.year * 12 + today.month - 1
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", t)
    if m and m.group(1) in _MONTHS:
        return int(m.group(2)) * 12 + _MONTHS[m.group(1)] - 1
    m = re.match(r"(\d{1,2})[/-](\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)) * 12 + int(m.group(1)) - 1
    m = re.match(r"(\d{4})$", t)
    if m:
        return int(m.group(1)) * 12
    return None


def years_from_history(work_history: list[dict], today: date | None = None) -> int | None:
    """
    Total experience computed in code from the extracted job dates (overlapping jobs counted once,
    gaps not counted). LLMs are unreliable at date arithmetic; Python is not.
    Returns None if any job's dates can't be parsed, so the caller can fall back.
    """
    today = today or date.today()
    spans = []
    for job in work_history or []:
        span = job_span(job, today)
        if span is None:
            return None
        spans.append(span)
    if not spans:
        return None
    return round(months_covered(spans) / 12)


def job_span(job: dict, today: date | None = None) -> tuple[int, int] | None:
    """(start, end) in months for one extracted job, or None if the dates can't be read."""
    today = today or date.today()
    start, end = _parse_month(job.get("StartDate"), today), _parse_month(job.get("EndDate"), today)
    if start is None or end is None or end < start:
        return None
    return start, end


def months_covered(spans: list[tuple[int, int]]) -> int:
    """Total months covered by possibly overlapping (start, end) spans; overlaps counted once."""
    if not spans:
        return 0
    spans = sorted(spans)
    total, (cur_s, cur_e) = 0, spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    return total + cur_e - cur_s

_VALUE_KEYS = {
    "string": "valueString",
    "number": "valueNumber",
    "integer": "valueInteger",
    "boolean": "valueBoolean",
    "date": "valueDate",
    "time": "valueTime",
    "json": "valueJson",
}


def unwrap(field: dict[str, Any] | None) -> Any:
    """Recursively convert a CU field ({type, valueX, confidence, ...}) into a plain Python value."""
    if not field:
        return None
    ftype = field.get("type")
    if ftype == "array":
        return [unwrap(item) for item in field.get("valueArray", []) or []]
    if ftype == "object":
        return {k: unwrap(v) for k, v in (field.get("valueObject") or {}).items()}
    if ftype in _VALUE_KEYS:
        return field.get(_VALUE_KEYS[ftype])
    # unknown type: fall back to the first value* key we find
    return next((v for k, v in field.items() if k.startswith("value")), None)


def confidences(fields: dict[str, Any]) -> dict[str, float]:
    """Top-level field confidences, useful for flagging low-confidence extractions for human review."""
    return {k: round(v["confidence"], 3) for k, v in fields.items() if isinstance(v, dict) and "confidence" in v}


# In many PDF fonts a capital I and a lowercase l look identical, so the text layer can turn
# "Azure AI Search" into "Azure Al Search" and "OpenAI" into "OpenAl" (see decision 010).
_AI_MISREADS = [
    (re.compile(r"\b(Azure|Gen|Generative|Responsible|Conversational)\s+Al\b"), r"\1 AI"),
    (re.compile(r"\bAl(?=\s+(Search|Foundry|Services|Studio|Engineer|Fundamentals|Agents?)\b)"), "AI"),
    (re.compile(r"\b(Open|Gen)Al\b"), r"\1AI"),
]


def fix_ai_misreads(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    for pattern, repl in _AI_MISREADS:
        text = pattern.sub(repl, text)
    return text


def _clean_jobs(jobs: list[dict] | None) -> list[dict]:
    out = []
    for j in jobs or []:
        j = dict(j)
        j["JobTitle"] = fix_ai_misreads(j.get("JobTitle"))
        if j.get("Highlights") is not None:
            j["Highlights"] = [fix_ai_misreads(h) for h in j["Highlights"] if isinstance(h, str) and h.strip()]
        out.append(j)
    return out


def to_profile(candidate_id: str, source_file: str, cu_result: dict[str, Any]) -> dict[str, Any]:
    contents = cu_result.get("contents") or [{}]
    fields = contents[0].get("fields", {})
    v = {name: unwrap(f) for name, f in fields.items()}

    def clean_list(items):
        return [s.strip() for s in (items or []) if isinstance(s, str) and s.strip()]

    return {
        "id": candidate_id,
        "source_file": source_file,
        "name": v.get("CandidateName"),
        "email": v.get("Email"),
        "phone": v.get("Phone"),
        "location": v.get("Location"),
        "headline": fix_ai_misreads(v.get("Headline")),
        "role_family": v.get("RoleFamily"),
        # Prefer the deterministic calculation; keep the model's estimate for comparison.
        "years_experience": years_from_history(v.get("WorkHistory") or []) or v.get("TotalYearsExperience"),
        "years_experience_model": v.get("TotalYearsExperience"),
        "skills": clean_list(v.get("Skills")),
        "certifications": clean_certifications(clean_list(v.get("Certifications")), v.get("Education") or []),
        "work_history": _clean_jobs(v.get("WorkHistory")),
        "education": v.get("Education") or [],
        # Facts a recruiter must not screen on. Kept separately so the screening step can drop them.
        "protected_flags": {
            "date_of_birth": bool(v.get("MentionsDateOfBirth")),
            "marital_status": bool(v.get("MentionsMaritalStatus")),
            "photo": bool(v.get("MentionsPhoto")),
        },
        "confidence": confidences(fields),
        "markdown": contents[0].get("markdown", ""),
    }
