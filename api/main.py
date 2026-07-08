from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.config import settings
from api.dashboard_auth import clear_dashboard_cookies
from api.rate_limit import limiter
from api.routers import admin, check, context, escalations, lifecycle, rules, slack
from api.services.lifecycle_service import run_consolidation, run_staleness_check


app = FastAPI(
    title="Signal",
    description="Operational intelligence for AI agent escalations.",
    version="0.1.0",
)
scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.app_timezone))
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.mount("/static", StaticFiles(directory="api/static"), name="static")
templates = Jinja2Templates(directory="api/templates")

app.include_router(escalations.router)
app.include_router(check.router)
app.include_router(rules.router)
app.include_router(context.router)
app.include_router(lifecycle.router)
app.include_router(slack.router)
app.include_router(admin.router)


def _is_expired_dashboard_session(exc: HTTPException) -> bool:
    if exc.status_code != status.HTTP_401_UNAUTHORIZED:
        return False
    return str(exc.detail) in {
        "Please sign in again.",
        "Dashboard session could not be verified.",
        "Please sign in.",
    }


@app.exception_handler(HTTPException)
async def signal_http_exception_handler(request: Request, exc: HTTPException):
    path = request.url.path
    if path.startswith(("/admin", "/dashboard")) and _is_expired_dashboard_session(exc):
        message = "Your session expired. Sign in again to continue."
        if request.method == "GET" and path.startswith("/dashboard") and path not in {
            "/dashboard/auth/config",
            "/dashboard/session",
            "/dashboard/logout",
            "/dashboard/org-session",
        }:
            response = RedirectResponse(url="/login?session_expired=1", status_code=status.HTTP_303_SEE_OTHER)
        else:
            response = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": message, "code": "session_expired"},
            )
        clear_dashboard_cookies(response)
        return response
    return await http_exception_handler(request, exc)


@app.on_event("startup")
async def start_scheduler() -> None:
    if not scheduler.get_job("staleness_check"):
        scheduler.add_job(run_staleness_check, "cron", hour=2, id="staleness_check")
    if not scheduler.get_job("consolidation"):
        scheduler.add_job(run_consolidation, "cron", day_of_week="mon", hour=3, id="consolidation")
    if not scheduler.running:
        scheduler.start()


@app.on_event("shutdown")
async def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/health")
async def health() -> dict[str, str]:
    _ = settings
    return {"status": "ok"}
