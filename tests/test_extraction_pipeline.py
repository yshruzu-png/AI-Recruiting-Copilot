"""
Offline tests: build fake Content Understanding responses from the ground truth and check that
profile normalization + evaluation behave correctly. No Azure calls.

Run: pytest -q
"""
import copy
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.catalog import clean_certifications  # noqa: E402
from copilot.evaluation import evaluate, to_markdown  # noqa: E402
from copilot.profiles import to_profile, unwrap, years_from_history  # noqa: E402

GT_PATH = ROOT / "data" / "synthetic" / "ground_truth.json"


def s(v):
    return {"type": "string", "valueString": v, "confidence": 0.95}


def arr(items):
    return {"type": "array", "valueArray": items}


def obj(d):
    return {"type": "object", "valueObject": d}


def fake_cu_result(gt: dict) -> dict:
    """What Content Understanding would return if it extracted this candidate perfectly."""
    p = gt["protected_info"]
    fields = {
        "CandidateName": s(gt["name"]),
        "Email": s(gt["email"]),
        "Phone": s(gt["phone"]),
        "Location": s(gt["city"]),
        "Headline": s(gt["headline"]),
        "Skills": arr([s(x) for x in gt["skills"]]),
        "Certifications": arr([s(x) for x in gt["certifications"]]),
        "WorkHistory": arr([obj({"JobTitle": s("t"), "Company": s("c")}) for _ in range(gt["num_roles"])]),
        "TotalYearsExperience": {"type": "integer", "valueInteger": gt["years_experience"], "confidence": 0.8},
        "Education": arr([obj({"Degree": s(e["degree"]), "Institution": s(e["school"]),
                               "GraduationYear": {"type": "integer", "valueInteger": e["year"]}})
                          for e in gt["education"]]),
        "RoleFamily": s(gt["family"]),
        "MentionsDateOfBirth": {"type": "boolean", "valueBoolean": "date_of_birth" in p},
        "MentionsMaritalStatus": {"type": "boolean", "valueBoolean": "marital_status" in p},
        "MentionsPhoto": {"type": "boolean", "valueBoolean": "photo_note" in p},
    }
    return {"contents": [{"kind": "document", "markdown": "# resume", "fields": fields}]}


@pytest.fixture(scope="module")
def truth():
    if not GT_PATH.exists():
        pytest.skip("Run scripts/generate_synthetic_data.py first")
    return json.loads(GT_PATH.read_text())["candidates"]


def test_unwrap_nested():
    field = arr([obj({"Degree": s("BSc"), "GraduationYear": {"type": "integer", "valueInteger": 2020}})])
    assert unwrap(field) == [{"Degree": "BSc", "GraduationYear": 2020}]
    assert unwrap(None) is None
    assert unwrap({"type": "array"}) == []


def test_profile_shape(truth):
    gt = truth[0]
    prof = to_profile(gt["id"], gt["file"], fake_cu_result(gt))
    assert prof["name"] == gt["name"]
    assert prof["skills"] == gt["skills"]
    assert prof["years_experience"] == gt["years_experience"]
    assert set(prof["protected_flags"]) == {"date_of_birth", "marital_status", "photo"}
    assert prof["confidence"]["CandidateName"] == 0.95


def test_perfect_extraction_scores_100(truth):
    profiles = {gt["id"]: to_profile(gt["id"], gt["file"], fake_cu_result(gt)) for gt in truth}
    report = evaluate(profiles, truth)
    assert all(v == 1.0 for v in report["accuracy"].values()), report["accuracy"]
    assert report["skills"]["f1"] == 1.0
    assert report["errors"] == []
    assert "Resume extraction evaluation" in to_markdown(report)


def test_mistakes_are_detected(truth):
    profiles = {gt["id"]: to_profile(gt["id"], gt["file"], fake_cu_result(gt)) for gt in truth}
    first = truth[0]["id"]
    bad = copy.deepcopy(profiles[first])
    bad["skills"] = bad["skills"][1:] + ["Made Up Skill"]  # one missing, one extra
    bad["years_experience"] += 3
    profiles[first] = bad
    del profiles[truth[1]["id"]]  # one resume failed to extract

    report = evaluate(profiles, truth)
    assert report["missing_profiles"] == [truth[1]["id"]]
    assert report["skills"]["precision"] < 1 and report["skills"]["recall"] < 1
    assert report["accuracy"]["years_within_1"] < 1
    assert report["errors"][0]["id"] == first


def test_years_computed_from_dates():
    today = date(2026, 10, 1)
    jobs = [{"StartDate": "Mar 2024", "EndDate": "Present"},     # 31 months
            {"StartDate": "Apr 2022", "EndDate": "Sep 2023"}]    # 17 months
    assert years_from_history(jobs, today) == 4                  # 48 months, gap ignored
    overlap = [{"StartDate": "Jan 2020", "EndDate": "Dec 2022"}, {"StartDate": "June 2021", "EndDate": "Dec 2023"}]
    assert years_from_history(overlap, today) == 4               # overlap counted once (47 months)
    assert years_from_history([{"StartDate": "sometime", "EndDate": "Present"}], today) is None
    assert years_from_history([], today) is None


def test_certification_cleanup():
    edu = [{"Degree": "Full-Stack / Data Bootcamp Certificate"}]
    certs = ["Microsoft Certified: Azure Al Engineer Associate",   # 'Al' misread from 'AI'
             "Full-Stack / Data Bootcamp Certificate",              # actually education
             "CISSP", "Some Unknown Cert"]
    assert clean_certifications(certs, edu) == [
        "Microsoft Certified: Azure AI Engineer Associate", "CISSP", "Some Unknown Cert"]
