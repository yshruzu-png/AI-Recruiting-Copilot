"""
Score the extracted profiles (data/extracted/) against data/synthetic/ground_truth.json
and write docs/eval/extraction_report.md.

Usage: python scripts/evaluate_extraction.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.evaluation import evaluate, to_markdown  # noqa: E402


def main() -> None:
    truth = json.loads((ROOT / "data" / "synthetic" / "ground_truth.json").read_text())["candidates"]
    profiles = {p.stem: json.loads(p.read_text()) for p in (ROOT / "data" / "extracted").glob("CAND-*.json")}
    if not profiles:
        sys.exit("No extracted profiles found. Run scripts/extract_resumes.py first.")

    report = evaluate(profiles, truth)
    out = ROOT / "docs" / "eval" / "extraction_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_markdown(report))
    (out.with_suffix(".json")).write_text(json.dumps(report, indent=2))

    acc, sk = report["accuracy"], report["skills"]
    print(f"Evaluated {report['evaluated']} resumes")
    print(f"  Name accuracy           {acc['name']:.1%}")
    print(f"  Years (within 1 year)   {acc['years_within_1']:.1%}  (model alone: {acc.get('years_model_within_1', 0):.1%})")
    print(f"  Role family             {acc['role_family']:.1%}")
    print(f"  Skills F1               {sk['f1']:.1%}  (P {sk['precision']:.1%} / R {sk['recall']:.1%})")
    print(f"  Certifications F1       {report['certifications']['f1']:.1%}")
    print(f"  Resumes with a mismatch {len(report['errors'])}")
    print(f"\nFull report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
