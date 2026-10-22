"""
Screen the whole candidate pool against one Request for Resumes and draft submissions for the best.

Usage:
    python scripts/screen_requirement.py RFR-002                 # top 3 drafts, model-written summaries
    python scripts/screen_requirement.py RFR-002 --top 5 --no-model
    python scripts/screen_requirement.py RFR-002 --source truth  # use the generator's criteria

Drafts land in data/submissions/RFR-002/CAND-xxx.md (+ .json) for a recruiter to review with
scripts/review_submission.py. Nothing is exported until a recruiter approves it.
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent_tools import load_profiles, stale_profiles  # noqa: E402
from copilot.requirements import load_requirements, skill_vocabulary  # noqa: E402
from copilot.screening import NOT_MET, screen  # noqa: E402
from copilot.submission import build_draft, save_draft, write_summary  # noqa: E402

MARK = {"met": "PASS  ", "verify": "VERIFY", "not_met": "FAIL  "}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    ap.add_argument("--top", type=int, default=3, help="how many drafts to create")
    ap.add_argument("--source", choices=["extracted", "truth"], default="extracted",
                    help="criteria from Content Understanding (default) or from the generator")
    ap.add_argument("--no-model", action="store_true", help="template summaries only, no model calls")
    args = ap.parse_args()

    profiles = load_profiles()
    if not profiles:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    reqs = load_requirements(args.source)
    req = reqs.get(args.request_id.upper())
    if not req:
        hint = "Run scripts/extract_requirements.py first." if args.source == "extracted" and not reqs else ""
        sys.exit(f"Unknown request {args.request_id}. Available: {', '.join(reqs) or 'none'}. {hint}")
    if not any(j.get("Highlights") for p in profiles.values() for j in p.get("work_history") or []):
        sys.exit("Profiles have no job highlights. Re-run setup_content_understanding.py and extract_resumes.py "
                 "(Week 4 added a Highlights field to the resume analyzer).")

    stale = stale_profiles(profiles)
    if stale:
        print(f"WARNING: {', '.join(stale)} have no job highlights and will look like they have no experience. "
              f"Re-run: python scripts/extract_resumes.py --only {' '.join(stale)}\n")
    results = screen(req, list(profiles.values()))
    print(f"{req['id']} {req['title']}: {len(results)} candidates screened\n")
    print(f"{'':6}  {'Candidate':<9}  {'Points':>9}  Mandatory")
    for r in results[:12]:
        mand = "  ".join(f"{m['id']}:{m['status']}" for m in r["mandatory"])
        print(f"{MARK[r['compliance']]}  {r['candidate_id']:<9}  {r['points']:>5g}/{r['points_max']:<3g}  {mand}")
    counts = {k: sum(r["compliance"] == k for r in results) for k in MARK}
    print(f"\n{counts['met']} compliant, {counts['verify']} need verification, {counts['not_met']} screened out")

    chosen = [r for r in results if r["compliance"] != NOT_MET][: args.top]
    if not chosen:
        print("Nobody meets the mandatory requirements. No drafts created.")
        return
    client = None
    if not args.no_model:
        from copilot.agent import default_chat_client
        client = default_chat_client()
    vocab = skill_vocabulary(profiles)
    print(f"\nDrafting {len(chosen)} submission(s):")
    for r in chosen:
        draft = build_draft(req, r, profiles[r["candidate_id"]])
        if client:
            draft = await write_summary(draft, client, vocab)
        path = save_draft(draft)
        note = "" if draft["summary_source"] == "model" or not client else \
            f"  (model summary rejected: {'; '.join(draft['summary_rejected']['problems'])})"
        print(f"  {r['candidate_id']}: {path.with_suffix('.md').relative_to(ROOT)}  [{draft['summary_source']} summary]{note}")
    print("\nNext: read the drafts, then  python scripts/review_submission.py "
          f"{req['id']} {chosen[0]['candidate_id']} --approve --reviewer \"Your Name\"")


if __name__ == "__main__":
    asyncio.run(main())
