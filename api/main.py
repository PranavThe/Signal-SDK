from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.config import settings
from api.dashboard_auth import clear_dashboard_cookies
from api.rate_limit import limiter
from api.routers import admin, check, context, escalations, guard, lifecycle, rules, slack
from api.services.lifecycle_service import run_consolidation, run_staleness_check


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_STATIC_DIR = PROJECT_ROOT / "api" / "static"
API_TEMPLATE_DIR = PROJECT_ROOT / "api" / "templates"
WEBSITE_DIST_DIR = PROJECT_ROOT / "signal-website" / "dist"
WEBSITE_ASSETS_DIR = WEBSITE_DIST_DIR / "assets"
BACKEND_PATH_PREFIXES = {
    "admin",
    "api-docs",
    "api-redoc",
    "dashboard",
    "health",
    "login",
    "openapi.json",
    "slack",
    "static",
    "stripe",
    "v1",
}

app = FastAPI(
    title="Signal",
    description="Operational intelligence for AI agent escalations.",
    version="0.1.0",
    docs_url="/api-docs",
    redoc_url="/api-redoc",
)
scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.app_timezone))
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.mount("/static", StaticFiles(directory=str(API_STATIC_DIR)), name="static")
if WEBSITE_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(WEBSITE_ASSETS_DIR)), name="website-assets")
templates = Jinja2Templates(directory=str(API_TEMPLATE_DIR))

app.include_router(escalations.router)
app.include_router(guard.router)
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


def _serve_website_file(path: str) -> FileResponse:
    if not WEBSITE_DIST_DIR.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website build not found")

    requested = (WEBSITE_DIST_DIR / path).resolve()
    dist_root = WEBSITE_DIST_DIR.resolve()
    try:
        requested.relative_to(dist_root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    if requested.is_file():
        return FileResponse(requested)

    index_file = WEBSITE_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website build not found")


@app.get("/", include_in_schema=False)
async def website_root() -> FileResponse:
    return _serve_website_file("index.html")


@app.get("/{website_path:path}", include_in_schema=False)
async def website_fallback(website_path: str) -> FileResponse:
    first_segment = website_path.split("/", 1)[0]
    if first_segment in BACKEND_PATH_PREFIXES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _serve_website_file(website_path)
