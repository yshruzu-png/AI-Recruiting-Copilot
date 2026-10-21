"""
Chat with the recruiting copilot in the terminal.

Prereqs: Week 2 done (data/extracted/ profiles + the 'candidates' search index), `az login`.
Usage:
    python scripts/chat.py                                   # interactive
    python scripts/chat.py "Top 5 for the Senior Data Engineer role, and why?"   # one question
    python scripts/chat.py --show-tools "Compare CAND-012 to JD-001"            # print tool calls
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.agent import build_agent  # noqa: E402
from copilot.agent_tools import RecruitingTools, azure_search_backend, load_jobs, load_profiles  # noqa: E402


async def ask(agent, tools, session, question: str, show_tools: bool) -> None:
    start = len(tools.calls)
    reply = await agent.run(question, session=session)
    if show_tools:
        for c in tools.calls[start:]:
            args = ", ".join(f"{k}={v!r}" for k, v in c["args"].items() if v is not None)
            print(f"  [tool] {c['tool']}({args})")
    print(f"\n{reply.text}\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--show-tools", action="store_true", help="print each tool call")
    args = ap.parse_args()

    profiles = load_profiles()
    if not profiles:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    tools = RecruitingTools(profiles, load_jobs(), azure_search_backend())
    agent = build_agent(tools)
    session = agent.create_session()  # keeps the conversation, so follow-ups work

    if args.question:
        await ask(agent, tools, session, args.question, args.show_tools)
        return
    print("Recruiting Copilot. Ask about candidates or jobs (JD-001..JD-005). Empty line to quit.\n")
    while (q := input("you> ").strip()):
        await ask(agent, tools, session, q, args.show_tools)


if __name__ == "__main__":
    asyncio.run(main())
