"""
Chat with the recruiting copilot in the terminal.

Prereqs: Week 2 done (data/extracted/ profiles + the 'candidates' search index), `az login`.
Usage:
    python scripts/chat.py                                   # interactive
    python scripts/chat.py "Top 5 for the Senior Data Engineer role, and why?"   # one question
    python scripts/chat.py --show-tools "Compare CAND-012 to JD-001"            # print tool calls
    python scripts/chat.py --no-shield ...                   # skip the Prompt Shields call (local rules only)

Every turn runs through copilot.guardrails.guarded_run: input check (local rules + Prompt Shields),
the agent, then an output check (no names / emails / phones, only candidate IDs a tool returned).
Each turn is logged to logs/audit.jsonl.
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent import build_agent  # noqa: E402
from copilot.agent_tools import RecruitingTools, azure_search_backend, load_jobs, load_profiles  # noqa: E402
from copilot.guardrails import PromptShield, guarded_run  # noqa: E402
from copilot.requirements import load_requirements  # noqa: E402


async def ask(agent, tools, session, question: str, show_tools: bool, shield, names) -> None:
    start = len(tools.calls)
    reply = await guarded_run(agent, tools, question, session=session, shield=shield, names=names)
    if show_tools:
        for c in tools.calls[start:]:
            args = ", ".join(f"{k}={v!r}" for k, v in c["args"].items() if v is not None)
            print(f"  [tool] {c['tool']}({args})")
        for p in reply.input_problems + reply.output_problems:
            print(f"  [guardrail] {p['check']}: {p['detail']}")
    print(f"\n{reply.text}\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--show-tools", action="store_true", help="print each tool call and guardrail finding")
    ap.add_argument("--no-shield", action="store_true", help="skip Azure Prompt Shields (local rules only)")
    args = ap.parse_args()

    profiles = load_profiles()
    if not profiles:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    tools = RecruitingTools(profiles, load_jobs(), azure_search_backend(),
                            load_requirements("extracted") or load_requirements("truth"))
    if tools.held:
        print(f"Held for recruiter review: {', '.join(tools.held)}\n")
    agent = build_agent(tools)
    from copilot.config import settings
    shield = None if args.no_shield else PromptShield(settings.ai_endpoint)
    names = [p.get("name") for p in profiles.values() if p.get("name")]
    session = agent.create_session()  # keeps the conversation, so follow-ups work

    if args.question:
        await ask(agent, tools, session, args.question, args.show_tools, shield, names)
        return
    print("Recruiting Copilot. Ask about jobs (JD-001..JD-005) or requests for resumes (RFR-001..RFR-004). "
          "Empty line to quit.\n")
    while (q := input("you> ").strip()):
        await ask(agent, tools, session, q, args.show_tools, shield, names)


if __name__ == "__main__":
    asyncio.run(main())
