"""
Project evidence: which jobs on a resume demonstrate a skill, and for how long.

Public-sector evaluators score "demonstrated experience": a skill counts when the resume shows it
being used in a role, with dates. A skill that only appears in the Skills section is not evidence;
it is flagged for the recruiter to verify instead.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Any

from copilot.profiles import job_span, months_covered


@lru_cache(maxsize=512)
def _pattern(skill: str) -> re.Pattern:
    # whole-term match that also works for terms like "C#", ".NET" and "CI/CD"
    return re.compile(rf"(?<![\w]){re.escape(skill.strip())}(?![\w])", re.I)


def mentions(text: str, skill: str) -> bool:
    return bool(skill.strip()) and bool(_pattern(skill).search(text or ""))


def evidence_for(work_history: list[dict[str, Any]], skills: list[str],
                 today: date | None = None) -> dict[str, Any]:
    """
    Jobs whose highlights mention any of the given skills, and the months they cover
    (overlapping jobs counted once). Jobs with unreadable dates are listed but add no months.
    """
    today = today or date.today()
    jobs, spans = [], []
    for job in work_history or []:
        hits = [h for h in job.get("Highlights") or [] if any(mentions(h, s) for s in skills)]
        if not hits:
            continue
        span = job_span(job, today)
        months = (span[1] - span[0]) if span else 0
        if span:
            spans.append(span)
        jobs.append({
            "title": job.get("JobTitle"),
            "company": job.get("Company"),
            "start": job.get("StartDate"),
            "end": job.get("EndDate"),
            "months": months,
            "highlights": hits,
        })
    return {"jobs": jobs, "months": months_covered(spans)}
