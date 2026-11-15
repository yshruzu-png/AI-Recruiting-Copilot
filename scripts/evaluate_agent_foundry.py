"""
Score the recruiting agent with Microsoft Foundry's model-graded evaluators.
Writes docs/eval/foundry_agent_report.md (and .json); the run also appears in the Foundry portal.

The Week 3 evaluation (scripts/evaluate_agent.py) checks facts with code: the right tool, real IDs,
agreement with the baseline, no names. Those checks can't judge whether an answer is *good*. Here an
LLM judge in Foundry scores the same 10 questions on:
- relevance          does the answer address the question?
- coherence          is it clear and well organised?
- task_adherence     did the agent do what was asked within its instructions? (a polite refusal of an
                     age filter should pass: the instructions say to decline it)
- tool_call_accuracy were the right tools called with sensible arguments?

Usage: python scripts/evaluate_agent_foundry.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent import build_agent, default_chat_client  # noqa: E402
from copilot.agent_eval import CASES  # noqa: E402
from copilot.agent_tools import RecruitingTools, azure_search_backend, load_jobs, load_profiles  # noqa: E402
from copilot.config import settings  # noqa: E402
from copilot.requirements import load_requirements  # noqa: E402

EVALUATORS = ["relevance", "coherence", "task_adherence", "tool_call_accuracy"]
OUT = ROOT / "docs" / "eval" / "foundry_agent_report.md"


def to_markdown(r, cases: list[dict]) -> str:
    L = ["# Agent evaluation with Foundry evaluators", "",
         f"Model under test: **{settings.chat_deployment}** · judge: **{settings.chat_deployment}** · "
         f"run status: **{r.status}**", ""]
    if r.report_url:
        L += [f"Foundry portal: {r.report_url}", ""]
    L += ["| Evaluator | Passed | Failed |", "|---|---|---|"]
    for name, counts in sorted(r.per_evaluator.items()):
        L.append(f"| {name} | {counts.get('passed', 0)} | {counts.get('failed', 0)} |")
    L += ["", f"Overall: **{r.passed}/{r.total}** items passed every evaluator.", "",
          "| # | Kind | Question | Status | Scores |", "|---|---|---|---|---|"]
    for i, item in enumerate(r.items):
        kind = cases[i]["kind"] if i < len(cases) else ""
        q = (item.input_text or (cases[i]["question"] if i < len(cases) else ""))[:80].replace("|", "/").replace("\n", " ")
        scores = ", ".join(f"{s.name} {s.score:g}{'' if s.passed in (None, True) else ' ✗'}" for s in item.scores)
        L.append(f"| {i + 1} | {kind} | {q} | {item.status} | {scores or item.error_message or ''} |")
    if r.error:
        L += ["", f"Error: {r.error}"]
    L += ["", "Scores are 1-5 from an LLM judge; a ✗ marks a score below the evaluator's pass threshold. "
          "Read failures next to the answers in docs/eval/agent_report.md before trusting them: a judge can "
          "mark a correct refusal as 'not relevant'."]
    return "\n".join(L) + "\n"


async def main() -> None:
    from agent_framework import evaluate_agent
    from agent_framework.foundry import FoundryEvals

    profiles = load_profiles()
    if not profiles:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    tools = RecruitingTools(profiles, load_jobs(), azure_search_backend(),
                            load_requirements("extracted") or load_requirements("truth"))
    client = default_chat_client()
    agent = build_agent(tools, client)
    evals = FoundryEvals(client=client, evaluators=EVALUATORS, timeout=600)

    print(f"Running {len(CASES)} questions through the agent, then {', '.join(EVALUATORS)} in Foundry...")
    results = await evaluate_agent(agent=agent, queries=[c["question"] for c in CASES], evaluators=evals,
                                   eval_name="recruiting-copilot-agent")
    r = results[0]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(to_markdown(r, CASES), encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps({
        "status": r.status, "report_url": r.report_url, "per_evaluator": r.per_evaluator,
        "passed": r.passed, "total": r.total, "error": r.error,
        "items": [{"status": i.status, "input": i.input_text, "output": i.output_text,
                   "scores": [{"name": s.name, "score": s.score, "passed": s.passed} for s in i.scores]}
                  for i in r.items]}, indent=2, default=str), encoding="utf-8")
    for name, counts in sorted(r.per_evaluator.items()):
        print(f"  {name:<20} {counts.get('passed', 0)} passed, {counts.get('failed', 0)} failed")
    if r.report_url:
        print(f"Foundry portal: {r.report_url}")
    print(f"Report: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
