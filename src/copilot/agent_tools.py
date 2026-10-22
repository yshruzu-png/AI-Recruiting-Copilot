"""
Tools the recruiting agent can call.

Every tool returns a *blind* view of candidates: skills, titles, dates, certifications and degrees.
Names, contact details, location, graduation years, the raw resume text and the protected-info
flags never reach the model, so it cannot rank on them even if asked to.

The search backend is injected, so the same tools run against Azure AI Search (live) or a simple
keyword search (offline tests).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Callable

from pydantic import Field

from copilot import matching, screening

ROOT = Path(__file__).resolve().parents[2]

# search(query, top, role_family=None, min_years=None, skill=None) -> list of dicts with an "id"
SearchFn = Callable[..., list[dict[str, Any]]]

ROLE_FAMILIES = ["data_engineer", "ml_engineer", "cloud_devops", "backend", "frontend", "security"]
RETRIEVE_FOR_RANKING = 20  # shortlist size pulled from search before deterministic scoring


# ---------------------------------------------------------------------------
# Blind views
# ---------------------------------------------------------------------------
def blind_profile(p: dict[str, Any]) -> dict[str, Any]:
    """What the agent is allowed to see about a candidate."""
    return {
        "candidate_id": p["id"],
        "current_title": p.get("headline"),
        "career_track": p.get("role_family"),
        "years_experience": p.get("years_experience"),
        "skills": p.get("skills") or [],
        "certifications": p.get("certifications") or [],
        "work_history": [
            {k: j.get(k) for k in ("JobTitle", "Company", "StartDate", "EndDate")}
            for j in p.get("work_history") or []
        ],
        # degree names only: graduation year is a proxy for age, school can be a proxy for origin
        "education": [e.get("Degree") for e in p.get("education") or [] if e.get("Degree")],
    }


def blind_summary(p: dict[str, Any]) -> dict[str, Any]:
    """Short version for search results."""
    b = blind_profile(p)
    return {k: b[k] for k in ("candidate_id", "current_title", "career_track", "years_experience",
                              "skills", "certifications")}


def public_job(j: dict[str, Any]) -> dict[str, Any]:
    """Job fields the agent may see (never the evaluation baseline)."""
    return {"job_id": j["id"], "title": j["title"], "career_track": j.get("family"),
            "min_years": j.get("min_years"), "required_skills": j.get("required") or [],
            "nice_to_have_skills": j.get("nice") or []}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_profiles(folder: Path | None = None) -> dict[str, dict[str, Any]]:
    folder = folder or ROOT / "data" / "extracted"
    profiles = {}
    for path in sorted(folder.glob("CAND-*.json")):
        p = json.loads(path.read_text(encoding="utf-8"))
        profiles[p["id"]] = p
    return profiles


def stale_profiles(profiles: dict[str, dict]) -> list[str]:
    """Profiles extracted before Week 4 (no job highlights): they can't show demonstrated experience."""
    return sorted(cid for cid, p in profiles.items()
                  if p.get("work_history") and not any(j.get("Highlights") for j in p["work_history"]))


def load_jobs(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Job requirements. In production these would come from a JD analyzer; here, the synthetic set."""
    path = path or ROOT / "data" / "synthetic" / "ground_truth.json"
    jobs = json.loads(path.read_text(encoding="utf-8"))["jobs"]
    return {j["id"]: {k: v for k, v in j.items() if k != "baseline_top10"} for j in jobs}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class RecruitingTools:
    def __init__(self, profiles: dict[str, dict], jobs: dict[str, dict], search: SearchFn,
                 requests: dict[str, dict] | None = None):
        self.profiles, self.jobs, self._search = profiles, jobs, search
        self.requests = requests or {}  # public-sector Requests for Resumes (Week 4)
        self.calls: list[dict[str, Any]] = []  # audit log: tool, arguments and result of every call

    def _log(self, name: str, **args) -> None:
        self.calls.append({"tool": name, "args": args})

    def _ret(self, result):
        self.calls[-1]["result"] = result
        return result

    def _job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id.strip().upper())

    # -- jobs ---------------------------------------------------------------
    def list_jobs(self) -> list[dict[str, Any]]:
        """List the open job requisitions (ID, title, career track, minimum years)."""
        self._log("list_jobs")
        return self._ret([{"job_id": j["id"], "title": j["title"], "career_track": j.get("family"),
                           "min_years": j.get("min_years")} for j in self.jobs.values()])

    def get_job(self, job_id: Annotated[str, Field(description="Job ID, e.g. JD-001")]) -> dict[str, Any]:
        """Get a job's requirements: required skills, nice-to-have skills and minimum years."""
        self._log("get_job", job_id=job_id)
        job = self._job(job_id)
        return self._ret(public_job(job) if job else {"error": f"No job with ID {job_id}. Call list_jobs."})

    # -- candidates ---------------------------------------------------------
    def search_candidates(
        self,
        query: Annotated[str, Field(description="Plain-language description of the skills or experience wanted")],
        career_track: Annotated[str | None, Field(description=f"Optional filter, one of: {', '.join(ROLE_FAMILIES)}")] = None,
        min_years: Annotated[int | None, Field(description="Optional minimum years of experience", ge=0)] = None,
        required_skill: Annotated[str | None, Field(description="Optional exact skill the candidate must list")] = None,
        top: Annotated[int, Field(description="How many results", ge=1, le=10)] = 5,
    ) -> list[dict[str, Any]]:
        """Search the candidate pool (hybrid keyword + semantic). Returns blind summaries, best match first."""
        self._log("search_candidates", query=query, career_track=career_track, min_years=min_years,
                  required_skill=required_skill, top=top)
        if career_track and career_track not in ROLE_FAMILIES:
            return self._ret([{"error": f"Unknown career track '{career_track}'. Use one of {ROLE_FAMILIES}."}])
        hits = self._search(query, top=top, role_family=career_track, min_years=min_years, skill=required_skill)
        return self._ret([blind_summary(self.profiles[h["id"]]) for h in hits if h["id"] in self.profiles])

    def get_candidate(self, candidate_id: Annotated[str, Field(description="Candidate ID, e.g. CAND-012")]) -> dict[str, Any]:
        """Get one candidate's blind profile: skills, certifications, work history and degrees."""
        self._log("get_candidate", candidate_id=candidate_id)
        p = self.profiles.get(candidate_id.strip().upper())
        return self._ret(blind_profile(p) if p else {"error": f"No candidate with ID {candidate_id}."})

    def compare_candidate_to_job(
        self,
        candidate_id: Annotated[str, Field(description="Candidate ID, e.g. CAND-012")],
        job_id: Annotated[str, Field(description="Job ID, e.g. JD-001")],
    ) -> dict[str, Any]:
        """Score one candidate against one job: required skills matched and missing, nice-to-haves, years."""
        self._log("compare_candidate_to_job", candidate_id=candidate_id, job_id=job_id)
        p, job = self.profiles.get(candidate_id.strip().upper()), self._job(job_id)
        if not p or not job:
            return self._ret({"error": "Unknown candidate or job ID."})
        return self._ret(matching.match(p, job))

    def rank_candidates_for_job(
        self,
        job_id: Annotated[str, Field(description="Job ID, e.g. JD-001")],
        top: Annotated[int, Field(description="How many candidates to return", ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Shortlist the best candidates for a job: retrieves likely matches with search, then scores
        each one with the same transparent formula (60% required skills, 20% nice-to-have, 20% experience)."""
        self._log("rank_candidates_for_job", job_id=job_id, top=top)
        job = self._job(job_id)
        if not job:
            return self._ret({"error": f"No job with ID {job_id}. Call list_jobs."})
        query = f"{job['title']}. Required: {', '.join(job['required'])}. Nice to have: {', '.join(job['nice'])}"
        hits = self._search(query, top=RETRIEVE_FOR_RANKING)
        pool = [self.profiles[h["id"]] for h in hits if h["id"] in self.profiles]
        ranked = matching.rank(pool, job, top=top)
        for r in ranked:
            r["current_title"] = self.profiles[r["candidate_id"]].get("headline")
        return self._ret({"job": public_job(job), "scoring": matching.WEIGHTS,
                          "candidates_considered": len(pool), "shortlist": ranked})

    # -- Requests for Resumes (public sector) -------------------------------
    def list_requests(self) -> list[dict[str, Any]]:
        """List open public-sector Requests for Resumes (RFRs) with their number of mandatory and rated criteria."""
        self._log("list_requests")
        return self._ret([{"request_id": r["id"], "title": r.get("title"), "mandatory_criteria": len(r.get("mandatory") or []),
                           "rated_criteria": len(r.get("rated") or [])} for r in self.requests.values()])

    def screen_request(
        self,
        request_id: Annotated[str, Field(description="Request ID, e.g. RFR-002")],
        top: Annotated[int, Field(description="How many candidates to return", ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Screen the whole pool against a Request for Resumes. Mandatory criteria are pass/fail and need
        project evidence with dates; rated criteria earn points. Returns compliant candidates first."""
        self._log("screen_request", request_id=request_id, top=top)
        req = self.requests.get(request_id.strip().upper())
        if not req:
            return self._ret({"error": f"No request with ID {request_id}. Call list_requests."})
        results = screening.screen(req, list(self.profiles.values()))
        rows = [{"candidate_id": r["candidate_id"], "compliance": r["compliance"],
                 "points": r["points"], "points_max": r["points_max"],
                 "mandatory": {m["id"]: f"{m['status']} ({m['evidence_years']} yrs shown)" for m in r["mandatory"]},
                 "rated": {x["id"]: x["points_awarded"] for x in r["rated"]}} for r in results[:top]]
        counts = {k: sum(r["compliance"] == k for r in results) for k in ("met", "verify", "not_met")}
        return self._ret({"request": {"id": req["id"], "title": req.get("title"),
                                      "mandatory": [{"id": c["id"], "text": c["text"]} for c in req.get("mandatory") or []],
                                      "rated": [{"id": c["id"], "text": c["text"], "points": c.get("points")}
                                                for c in req.get("rated") or []]},
                          "counts": counts, "candidates": rows,
                          "note": "verify = skill listed but not shown in a dated role; recruiter must confirm."})

    def as_agent_tools(self) -> list:
        """Wrap the methods as Microsoft Agent Framework function tools."""
        from agent_framework import tool

        return [tool(fn) for fn in (self.list_jobs, self.get_job, self.search_candidates, self.get_candidate,
                                    self.compare_candidate_to_job, self.rank_candidates_for_job,
                                    self.list_requests, self.screen_request)]


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------
def azure_search_backend(credential=None) -> SearchFn:
    """Live backend: the Week 2 hybrid search over the Azure AI Search 'candidates' index."""
    from azure.identity import DefaultAzureCredential
    from azure.search.documents import SearchClient

    from copilot.config import settings
    from copilot.search_index import INDEX_NAME, Embedder, hybrid_search

    cred = credential or DefaultAzureCredential()
    client = SearchClient(settings.search_endpoint, INDEX_NAME, cred)
    embedder = Embedder(settings.ai_endpoint, settings.embedding_deployment, cred)

    def search(query: str, top: int = 5, **filters) -> list[dict]:
        return hybrid_search(client, embedder, query, top=top, **filters)

    return search


def keyword_search_backend(profiles: dict[str, dict]) -> SearchFn:
    """Offline backend for tests: counts query words found in each profile's skills and title."""
    def search(query: str, top: int = 5, role_family=None, min_years=None, skill=None) -> list[dict]:
        words = {w.strip(".,:;()").lower() for w in query.split() if len(w) > 2}
        scored = []
        for p in profiles.values():
            if role_family and p.get("role_family") != role_family:
                continue
            if min_years is not None and (p.get("years_experience") or 0) < min_years:
                continue
            if skill and skill.lower() not in {s.lower() for s in p.get("skills") or []}:
                continue
            text = " ".join((p.get("skills") or []) + [p.get("headline") or ""]).lower()
            scored.append((sum(w in text for w in words), p["id"]))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [{"id": cid} for _, cid in scored[:top]]

    return search
