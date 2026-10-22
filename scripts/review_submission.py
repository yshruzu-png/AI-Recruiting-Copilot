"""
Recruiter review: approve or reject a draft. Approving exports the client-ready Word document,
with the candidate's name added back for the first time.

Usage:
    python scripts/review_submission.py RFR-002 CAND-031 --approve --reviewer "Yusuf"
    python scripts/review_submission.py RFR-002 CAND-028 --reject --reviewer "Yusuf" --note "Docker not confirmed"
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent_tools import load_profiles  # noqa: E402
from copilot.submission import draft_path, export_docx, review  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    ap.add_argument("candidate_id")
    decision = ap.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    ap.add_argument("--reviewer", required=True, help="your name, recorded on the submission")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    path = draft_path(args.request_id.upper(), args.candidate_id.upper())
    if not path.exists():
        sys.exit(f"No draft at {path.relative_to(ROOT)}. Run scripts/screen_requirement.py first.")
    before = json.loads(path.read_text())
    if before["warnings"] and args.approve:
        print("Warnings on this draft:")
        for w in before["warnings"]:
            print(f"  - {w}")
        if input("Approve anyway? [y/N] ").strip().lower() != "y":
            sys.exit("Not approved.")

    draft = review(path, args.reviewer, "approved" if args.approve else "rejected", args.note)
    print(f"{draft['candidate_id']} for {draft['requirement_id']}: {draft['status']} by {draft['reviewer']}")
    if args.approve:
        profile = load_profiles()[draft["candidate_id"]]
        out = export_docx(draft, profile, path.with_suffix(".docx"))
        print(f"Exported: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
