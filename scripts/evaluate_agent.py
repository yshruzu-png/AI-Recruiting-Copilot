"""
Ask the agent a fixed set of recruiter questions and score the answers.
Writes docs/eval/agent_report.md (and .json).

Checks: ranking questions use the ranking tool, cite only real IDs and agree with the baseline;
fairness probes (age, marital status) are declined; an impossible role gets an honest "no match";
no candidate names appear in any answer.

Usage: python scripts/evaluate_agent.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent import build_agent  # noqa: E402
from copilot.agent_eval import CASES, ID_RE, score_case, summarize, to_markdown  # noqa: E402
from copilot.agent_tools import RecruitingTools, azure_search_backend, load_jobs, load_profiles  # noqa: E402
from copilot.requirements import load_requirements  # noqa: E402
from copilot.config import settings  # noqa: E402


async def main() -> None:
    gt = json.loads((ROOT / "data" / "synthetic" / "ground_truth.json").read_text())
    baseline = {j["id"]: [b["id"] for b in j["baseline_top10"][:5]] for j in gt["jobs"]}
    profiles = load_profiles()
    if not profiles:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    names = [p.get("name") for p in profiles.values()]

    tools = RecruitingTools(profiles, load_jobs(), azure_search_backend(),
                            load_requirements("extracted") or load_requirements("truth"))
    agent = build_agent(tools)

    results = []
    for case in CASES:
        tools.calls.clear()
        reply = await agent.run(case["question"], session=agent.create_session())  # independent questions
        tool_ids = set(ID_RE.findall(json.dumps([c.get("result") for c in tools.calls])))
        r = score_case(case, reply.text, list(tools.calls), tool_ids, baseline.get(case.get("job_id")), names)
        results.append(r)
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {case['kind']:<9} {case['question'][:70]}")

    summary = summarize(results)
    out = ROOT / "docs" / "eval" / "agent_report.md"
    out.write_text(to_markdown(summary, results, settings.chat_deployment), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str))
    for k, v in summary["pass_rate"].items():
        print(f"{k:<10} {v:.0%} passed")
    print(f"Baseline overlap@5  {summary['baseline_overlap@5'] or 0:.0%}")
    print(f"Report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
