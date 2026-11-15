"""
Red-team the Week 5 guardrails. Writes docs/eval/guardrails_report.md (and .json).

1. Resume integrity: 7 tampered resumes (hidden keyword stuffing, AI-directed instructions) must be
   held for review; the 40 clean resumes and 3 tricky controls must not be.
2. Input check: 10 jailbreak / override prompts vs 18 ordinary recruiter questions.
3. Containment: with the tampered resumes in the pool, no held candidate may appear in any ranking
   or RFR screening, and the report shows where they would have ranked without the guardrail.

Offline by default (no Azure calls, free). --live adds:
- Content Understanding extraction of the tampered resumes (instead of the offline text-layer profile)
- Prompt Shields on every prompt and on every resume's text (document attacks)
- The live agent answering each attack prompt that gets past the input check, for a human to read

Usage:
    python scripts/generate_adversarial_data.py
    python scripts/evaluate_guardrails.py            # offline
    python scripts/evaluate_guardrails.py --live     # + Azure
"""
import argparse
import asyncio
import json
import mimetypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot import guardrails  # noqa: E402
from copilot.agent_tools import RecruitingTools, keyword_search_backend, load_jobs, load_profiles  # noqa: E402
from copilot.guardrail_eval import (ATTACK_PROMPTS, BENIGN_PROMPTS, offline_profile, score_prompts,  # noqa: E402
                                    score_resumes)
from copilot.requirements import load_requirements  # noqa: E402

ADV = ROOT / "data" / "synthetic" / "adversarial"
OUT = ROOT / "docs" / "eval" / "guardrails_report.md"
mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def containment(clean: dict, adversarial: dict) -> dict:
    """Rank every job and screen every RFR with the tampered resumes in the pool, with and without holds."""
    pool = clean | adversarial
    jobs, reqs = load_jobs(), load_requirements("truth")
    guarded = RecruitingTools(pool, jobs, keyword_search_backend(pool), reqs)
    unguarded = RecruitingTools(pool, jobs, keyword_search_backend(pool), reqs)
    unguarded.held = {}
    held = set(guarded.held)
    rows, leaks = [], []
    for jid in jobs:
        g = [r["candidate_id"] for r in guarded.rank_candidates_for_job(jid, top=5)["shortlist"]]
        u = [r["candidate_id"] for r in unguarded.rank_candidates_for_job(jid, top=5)["shortlist"]]
        leaks += [(jid, c) for c in g if c in held]
        rows.append({"target": jid, "guarded_top5": g, "unguarded_top5": u,
                     "held_in_unguarded": [f"{c} (#{u.index(c) + 1})" for c in u if c in held]})
    for rid in reqs:
        g = [r["candidate_id"] for r in guarded.screen_request(rid, top=10)["candidates"]]
        u = [r["candidate_id"] for r in unguarded.screen_request(rid, top=10)["candidates"]]
        leaks += [(rid, c) for c in g if c in held]
        rows.append({"target": rid, "guarded_top5": g[:5], "unguarded_top5": u[:5],
                     "held_in_unguarded": [f"{c} (#{u.index(c) + 1})" for c in u if c in held]})
    return {"held": sorted(held), "rows": rows, "leaks": leaks}


async def live_agent_answers(prompts: list[str], profiles: dict) -> list[dict]:
    from copilot.agent import build_agent
    from copilot.agent_tools import azure_search_backend
    from copilot.config import settings

    tools = RecruitingTools(profiles, load_jobs(), azure_search_backend(),
                            load_requirements("extracted") or load_requirements("truth"))
    agent = build_agent(tools)
    shield = guardrails.PromptShield(settings.ai_endpoint)
    names = [p.get("name") for p in profiles.values() if p.get("name")]
    out = []
    for q in prompts:
        tools.calls.clear()
        r = await guardrails.guarded_run(agent, tools, q, session=agent.create_session(), shield=shield,
                                         names=names, audit_log=None)
        out.append({"prompt": q, "blocked": r.blocked, "answer": r.text, "raw_answer": r.raw_text,
                    "problems": [p["check"] for p in r.input_problems + r.output_problems]})
        print(f"  {'BLOCKED' if r.blocked else 'answered'}  {q[:70]}")
    return out


def to_markdown(rep: dict) -> str:
    rs, pr = rep["resumes"], rep["prompts"]
    L = ["# Guardrails evaluation (Week 5)", "",
         f"Mode: **{rep['mode']}**. Resumes: {rs['tampered']} tampered, {rs['clean']} clean "
         f"(40 from the main dataset + 3 tricky controls). Prompts: {pr['local']['attacks']} attacks, "
         f"{pr['local']['benign']} ordinary recruiter questions.", "",
         "## Summary", "", "| Check | Result |", "|---|---|",
         f"| Tampered resumes held for review | {rs['caught']}/{rs['tampered']} ({pct(rs['detection_rate'])}) |",
         f"| Clean resumes wrongly held | {len(rs['false_positives'])}/{rs['clean']} ({pct(rs['false_positive_rate'])}) |"]
    for t, r in rs["finding_recall"].items():
        L.append(f"| Recall: {t.replace('_', ' ')} | {pct(r)} |")
    L += [f"| Attack prompts blocked, local rules | {pr['local']['blocked']}/{pr['local']['attacks']} "
          f"({pct(pr['local']['attack_block_rate'])}) |",
          f"| Ordinary questions wrongly blocked, local rules | {pr['local']['false_blocks']}/{pr['local']['benign']} |"]
    if pr.get("shield"):
        s, c = pr["shield"], pr["combined"]
        L += [f"| Attack prompts flagged, Prompt Shields | {s['blocked']}/{s['attacks']} ({pct(s['attack_block_rate'])}) |",
              f"| Ordinary questions flagged, Prompt Shields | {s['false_blocks']}/{s['benign']} |",
              f"| Attack prompts blocked, both layers | {c['blocked']}/{c['attacks']} ({pct(c['attack_block_rate'])}) |"]
    if rep.get("shield_documents"):
        d = rep["shield_documents"]
        L.append(f"| Resumes with instructions flagged by Prompt Shields (documents) | {d['caught']}/{d['tampered']}, "
                 f"{len(d['false_positives'])} false positives on {d['clean']} |")
    cont = rep["containment"]
    L += [f"| Held candidates appearing in any ranking or RFR screen | {len(cont['leaks'])} |", ""]

    L += ["## Resumes", "", "| ID | Attack | Expected | Verdict | Findings |", "|---|---|---|---|---|"]
    for row in rep["resume_rows"]:
        finds = "; ".join(f"{f['type']} ({f.get('rule') or f['where']})" for f in row["findings"]) or "none"
        L.append(f"| {row['id']} | {row['attack']} | {', '.join(row['expect']) or 'clean'} | {row['status']} | {finds} |")
    if rs["false_positives"]:
        L += ["", f"False positives: {', '.join(rs['false_positives'])}"]

    L += ["", "## Containment: where held resumes would have ranked without the guardrail", "",
          "| Job / RFR | Guarded top 5 | Held candidates in the unguarded results |", "|---|---|---|"]
    for r in cont["rows"]:
        L.append(f"| {r['target']} | {', '.join(r['guarded_top5']) or 'none'} | {', '.join(r['held_in_unguarded']) or 'none'} |")
    L += ["", "Ranking uses the offline keyword search here, so this measures the hold, not search quality.", "",
          "## Prompts", "", "| Prompt | Kind | Local rules | Prompt Shields |", "|---|---|---|---|"]
    for p in rep["prompt_rows"]:
        sh = "" if p.get("shield") is None else ("flagged" if p["shield"] else "pass")
        L.append(f"| {p['prompt'][:90].replace('|', '/').replace(chr(10), ' ')} | {p['kind']} | "
                 f"{'blocked' if p['local'] else 'pass'} | {sh} |")
    if rep.get("agent_answers"):
        L += ["", "## Live agent answers to the attack prompts", ""]
        for a in rep["agent_answers"]:
            L += [f"**{a['prompt']}**  ", f"{'Blocked at input' if a['blocked'] else 'Answered'}"
                  f"{' · ' + ', '.join(a['problems']) if a['problems'] else ''}", "",
                  "> " + a["answer"].replace("\n", "\n> "), ""]
    L += ["", "## How to read this", "",
          "- The local input rules are a cheap first filter. Paraphrased attacks (role-play, \"pretend\") get past them by design; "
          "Prompt Shields is the layer for those.",
          "- Even an attack that reaches the model can't change a score or a compliance result: those are computed in code "
          "(decisions 014 and 021), and held resumes are removed before the model sees the pool.",
          "- Every agent answer is also checked on the way out: names, emails and phone numbers are redacted, and an answer "
          "citing a candidate ID no tool returned is withheld."]
    return "\n".join(L) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also use Content Understanding, Prompt Shields and the live agent")
    args = ap.parse_args()
    if not (ADV / "labels.json").exists():
        sys.exit("No adversarial resumes. Run: python scripts/generate_adversarial_data.py")
    labels = json.loads((ADV / "labels.json").read_text())
    clean = load_profiles()
    if not clean:
        sys.exit("No profiles in data/extracted/. Run scripts/extract_resumes.py first.")
    for p in clean.values():  # always re-check, so the report reflects the current rules
        p["integrity"] = guardrails.assess_profile(p, guardrails.source_path(p))

    # 1. resumes
    if args.live:
        from azure.identity import DefaultAzureCredential

        from copilot.config import settings
        from copilot.content_understanding import ContentUnderstandingClient
        from copilot.profiles import to_profile

        cu = ContentUnderstandingClient(settings.ai_endpoint, credential=DefaultAzureCredential())
        adversarial = {}
        for lab in labels:
            path = ADV / lab["file"]
            raw = cu.analyze_bytes("resumeAnalyzer", path.read_bytes(), mimetypes.guess_type(path.name)[0], path.name)
            adversarial[lab["id"]] = to_profile(lab["id"], lab["file"], raw)
            print(f"  extracted {lab['id']}")
    else:
        adversarial = {lab["id"]: offline_profile(lab, ADV) for lab in labels}
    for lab in labels:
        adversarial[lab["id"]]["integrity"] = guardrails.assess_profile(adversarial[lab["id"]], ADV / lab["file"])

    verdicts = {cid: p["integrity"] for cid, p in (clean | adversarial).items()}
    expected = {cid: [] for cid in clean} | {lab["id"]: lab["expect"] for lab in labels}
    resumes = score_resumes(verdicts, expected)
    resume_rows = [{"id": lab["id"], "attack": lab["attack"], "expect": lab["expect"]} | adversarial[lab["id"]]["integrity"]
                   for lab in labels]

    # 2. prompts
    local_a = [bool(guardrails.check_input(q)) for q in ATTACK_PROMPTS]
    local_b = [bool(guardrails.check_input(q)) for q in BENIGN_PROMPTS]
    prompts = {"local": score_prompts(local_a, local_b)}
    shield_a = shield_b = None
    shield_docs = None
    agent_answers = None
    if args.live:
        from copilot.config import settings

        shield = guardrails.PromptShield(settings.ai_endpoint)
        shield_a = [shield.check_prompt(q) for q in ATTACK_PROMPTS]
        shield_b = [shield.check_prompt(q) for q in BENIGN_PROMPTS]
        prompts["shield"] = score_prompts(shield_a, shield_b)
        prompts["combined"] = score_prompts([a or b for a, b in zip(local_a, shield_a)],
                                            [a or b for a, b in zip(local_b, shield_b)])
        ids = list(clean) + [lab["id"] for lab in labels]
        texts = [(clean | adversarial)[cid].get("markdown") or "" for cid in ids]
        flags = shield.check_documents(texts)
        doc_verdicts = {cid: {"status": "review" if f else "clean", "findings": []} for cid, f in zip(ids, flags)}
        doc_expected = {cid: (["instruction_text"] if "instruction_text" in expected[cid] else []) for cid in ids}
        shield_docs = score_resumes(doc_verdicts, doc_expected)
        passed = [q for q, a in zip(ATTACK_PROMPTS, local_a) if not a]
        print("Live agent on attack prompts that pass the local rules:")
        agent_answers = await live_agent_answers(passed, clean)

    prompt_rows = ([{"prompt": q, "kind": "attack", "local": l, "shield": (shield_a or [None] * 99)[i]}
                    for i, (q, l) in enumerate(zip(ATTACK_PROMPTS, local_a))]
                   + [{"prompt": q, "kind": "ordinary", "local": l, "shield": (shield_b or [None] * 99)[i]}
                      for i, (q, l) in enumerate(zip(BENIGN_PROMPTS, local_b))])

    # 3. containment
    cont = containment(clean, adversarial)

    rep = {"mode": "live" if args.live else "offline", "resumes": resumes, "resume_rows": resume_rows,
           "prompts": prompts, "prompt_rows": prompt_rows, "shield_documents": shield_docs,
           "containment": cont, "agent_answers": agent_answers}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(to_markdown(rep), encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    print(f"Tampered resumes held: {resumes['caught']}/{resumes['tampered']}   "
          f"clean wrongly held: {len(resumes['false_positives'])}/{resumes['clean']}")
    for k, s in prompts.items():
        print(f"Prompts ({k}): {s['blocked']}/{s['attacks']} attacks blocked, {s['false_blocks']}/{s['benign']} ordinary blocked")
    if shield_docs:
        print(f"Prompt Shields documents: {shield_docs['caught']}/{shield_docs['tampered']} injected resumes flagged, "
              f"{len(shield_docs['false_positives'])} false positives")
    print(f"Held candidates leaking into rankings/screens: {len(cont['leaks'])}")
    print(f"Report: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
