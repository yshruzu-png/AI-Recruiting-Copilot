"""
Week 6: the web API (FastAPI), deployed to Azure Container Apps.

    uvicorn copilot.api:app --app-dir src --port 8000      # local; open http://localhost:8000

Endpoints
    GET  /                 chat page (web/)
    GET  /health           liveness + pool size, for Container Apps probes
    GET  /api/jobs         open requisitions
    GET  /api/requests     open Requests for Resumes
    GET  /api/held         resumes held for review (Week 5), with the reasons
    POST /api/chat         {question, session_id?} -> one guarded agent turn

Security
- Sign-in is done in front of the app by Container Apps authentication (Entra ID). The app reads the
  signed-in user from the X-MS-CLIENT-PRINCIPAL-NAME header for the audit log, and refuses requests
  without it when REQUIRE_AUTH=true (set in Terraform), in case the auth layer is ever switched off.
- The app signs in to Azure with its managed identity (DefaultAzureCredential). No keys anywhere.
- Each browser session gets its own tools and agent, so one recruiter's tool results can never
  "ground" another recruiter's answer, and sessions expire after SESSION_TTL_SECONDS.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from copilot import guardrails, telemetry
from copilot.agent_tools import RecruitingTools

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
MAX_SESSIONS = 200
SESSION_TTL_SECONDS = 60 * 60
log = logging.getLogger("copilot")


# ---------------------------------------------------------------------------
# Dependencies (real ones built at startup; tests pass fakes)
# ---------------------------------------------------------------------------
@dataclass
class Deps:
    profiles: dict[str, dict]
    jobs: dict[str, dict]
    requests: dict[str, dict]
    search: Callable[..., list[dict]]
    agent_factory: Callable[[RecruitingTools], Any]       # tools -> agent with .run() and .create_session()
    shield: guardrails.PromptShield | None = None
    require_auth: bool = False
    audit_log: Path | None = guardrails.AUDIT_LOG
    names: list[str] = field(default_factory=list)


def azure_deps() -> Deps:
    """Everything from Azure, signed in with the managed identity (or `az login` locally)."""
    from azure.identity import DefaultAzureCredential

    from copilot.agent import build_agent, default_chat_client
    from copilot.agent_tools import azure_search_backend, load_jobs, load_profiles
    from copilot.config import settings
    from copilot.requirements import load_requirements

    cred = DefaultAzureCredential()
    profiles = load_profiles()
    if not profiles:
        raise RuntimeError("No candidate profiles found in data/extracted/.")
    if os.getenv("DEMO_INCLUDE_ADVERSARIAL", "false").lower() == "true":
        profiles |= adversarial_profiles()
    client = default_chat_client()
    use_shield = os.getenv("USE_PROMPT_SHIELDS", "true").lower() != "false"
    return Deps(
        profiles=profiles, jobs=load_jobs(),
        requests=load_requirements("extracted") or load_requirements("truth"),
        search=azure_search_backend(cred), agent_factory=lambda tools: build_agent(tools, client),
        shield=guardrails.PromptShield(settings.ai_endpoint, cred) if use_shield else None,
        require_auth=os.getenv("REQUIRE_AUTH", "false").lower() == "true",
        audit_log=Path(os.getenv("AUDIT_LOG", str(guardrails.AUDIT_LOG))),
        names=[p["name"] for p in profiles.values() if p.get("name")],
    )


def adversarial_profiles() -> dict[str, dict]:
    """Demo only: add the Week 5 tampered resumes (CAND-101..110) so the 'held for review' panel has
    something to show. They aren't in the search index, so they never rank either way."""
    import json

    from copilot.guardrail_eval import offline_profile

    folder = ROOT / "data" / "synthetic" / "adversarial"
    labels = json.loads((folder / "labels.json").read_text()) if (folder / "labels.json").exists() else []
    out = {}
    for lab in labels:
        p = offline_profile(lab, folder)
        p["integrity"] = guardrails.assess_profile(p, folder / lab["file"])
        out[p["id"]] = p
    return out


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@dataclass
class ChatSession:
    tools: RecruitingTools
    agent: Any
    thread: Any
    last_used: float


class Sessions:
    def __init__(self, deps: Deps):
        self.deps = deps
        self._items: OrderedDict[str, ChatSession] = OrderedDict()

    def get(self, session_id: str | None) -> tuple[str, ChatSession]:
        now = time.time()
        for sid in [s for s, v in self._items.items() if now - v.last_used > SESSION_TTL_SECONDS]:
            del self._items[sid]
        if session_id and session_id in self._items:
            s = self._items[session_id]
            s.last_used = now
            self._items.move_to_end(session_id)
            return session_id, s
        d = self.deps
        tools = RecruitingTools(d.profiles, d.jobs, d.search, d.requests)
        agent = d.agent_factory(tools)
        sid = uuid.uuid4().hex
        self._items[sid] = ChatSession(tools, agent, agent.create_session(), now)
        while len(self._items) > MAX_SESSIONS:
            self._items.popitem(last=False)
        return sid, self._items[sid]

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=guardrails.MAX_QUESTION_CHARS)
    session_id: str | None = Field(default=None, max_length=64)


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(deps_factory: Callable[[], Deps] = azure_deps) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        deps = deps_factory()
        app.state.deps = deps
        app.state.sessions = Sessions(deps)
        app.state.base_tools = RecruitingTools(deps.profiles, deps.jobs, deps.search, deps.requests)
        telemetry.HELD.add(len(app.state.base_tools.held))
        log.info("Ready: %d profiles, %d held for review", len(deps.profiles), len(app.state.base_tools.held))
        yield

    app = FastAPI(title="AI Recruiting Copilot", version="1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)  # no public schema browser

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    def signed_in_user(request: Request) -> str | None:
        user = request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
        if request.app.state.deps.require_auth and not user:
            raise HTTPException(401, "Sign-in required.")
        return user

    @app.get("/health")
    async def health(request: Request):
        st = request.app.state
        return {"status": "ok", "profiles": len(st.deps.profiles), "held_for_review": len(st.base_tools.held),
                "sessions": len(st.sessions)}

    @app.get("/api/me")
    async def me(request: Request):
        return {"user": signed_in_user(request)}

    @app.get("/api/jobs")
    async def jobs(request: Request):
        signed_in_user(request)
        return request.app.state.base_tools.list_jobs()

    @app.get("/api/requests")
    async def requests_for_resumes(request: Request):
        signed_in_user(request)
        return request.app.state.base_tools.list_requests()

    @app.get("/api/held")
    async def held(request: Request):
        signed_in_user(request)
        profiles = request.app.state.deps.profiles
        out = []
        for cid, reason in request.app.state.base_tools.held.items():
            findings = (profiles[cid].get("integrity") or {}).get("findings", [])
            out.append({"candidate_id": cid, "reason": reason,
                        "findings": [{"type": f["type"], "where": f["where"]} for f in findings]})
        return out

    @app.post("/api/chat")
    async def chat(body: ChatIn, request: Request):
        user = signed_in_user(request)
        st = request.app.state
        sid, s = st.sessions.get(body.session_id)
        try:
            reply = await guardrails.guarded_run(s.agent, s.tools, body.question, session=s.thread,
                                                 shield=st.deps.shield, names=st.deps.names,
                                                 audit_log=st.deps.audit_log, user=user)
        except Exception:
            log.exception("chat turn failed")
            return JSONResponse({"session_id": sid, "error": "The copilot couldn't answer just now. Try again."},
                                status_code=502)
        return {"session_id": sid, "answer": reply.text, "blocked": reply.blocked, "tools": reply.tool_calls,
                "checks": [p["check"] for p in reply.input_problems + reply.output_problems]}

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=WEB), name="static")

        @app.get("/")
        async def index():
            return FileResponse(WEB / "index.html")

    return app


def _lazy_app() -> FastAPI:
    # Telemetry first, so Azure Monitor can instrument FastAPI requests. No-op without a connection string.
    telemetry.setup_telemetry()
    return create_app()


app = _lazy_app()
