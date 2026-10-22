"""
Read each Request for Resumes (PDF) with the Content Understanding requirement analyzer and save
clean criteria to data/extracted/requests/RFR-xxx.json. Then compare them with the generator's truth.

Prereqs: scripts/setup_content_understanding.py (creates 'requirementAnalyzer').
Usage:
    python scripts/extract_requirements.py
    python scripts/extract_requirements.py --from-raw     # rebuild from saved results, no Azure calls
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent_tools import load_profiles  # noqa: E402
from copilot.requirements import compare_requirement, load_requirements, skill_vocabulary, to_requirement  # noqa: E402

ANALYZER_ID = "requirementAnalyzer"
SRC = ROOT / "data" / "synthetic" / "requests"
OUT = ROOT / "data" / "extracted" / "requests"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-raw", action="store_true", help="rebuild from saved raw results (free)")
    args = ap.parse_args()

    profiles = load_profiles()
    if not profiles:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    vocab = skill_vocabulary(profiles)  # map requirement wording onto the pool's skill names
    (OUT / "raw").mkdir(parents=True, exist_ok=True)

    files = sorted(SRC.glob("RFR-*.pdf"))
    if not files:
        sys.exit("No requests found. Run scripts/generate_synthetic_data.py first.")
    if not args.from_raw:
        from copilot.config import settings
        from copilot.content_understanding import ContentUnderstandingClient

        cu = ContentUnderstandingClient(settings.ai_endpoint)
        for f in files:
            print(f"  Analyzing {f.name}...")
            raw = cu.analyze_bytes(ANALYZER_ID, f.read_bytes(), "application/pdf", f.name)
            (OUT / "raw" / f"{f.stem}.json").write_text(json.dumps(raw, indent=2))

    truth = load_requirements("truth")
    scores = []
    for f in files:
        raw = json.loads((OUT / "raw" / f"{f.stem}.json").read_text())
        req = to_requirement(f.stem, raw, vocab)
        (OUT / f"{f.stem}.json").write_text(json.dumps(req, indent=2))
        result = compare_requirement(req, truth[f.stem])
        scores.append(result["accuracy"])
        wrong = [k for k, ok in result["checks"].items() if not ok]
        print(f"  {f.stem}: {len(req['mandatory'])} mandatory, {len(req['rated'])} rated, "
              f"{result['accuracy']:.0%} correct" + (f"  (check: {', '.join(wrong)})" if wrong else ""))
    print(f"\nRequirement extraction accuracy: {sum(scores) / len(scores):.0%} -> {OUT}")


if __name__ == "__main__":
    main()
