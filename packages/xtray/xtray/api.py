"""FastAPI app exposing Computer Manager profile operations for Home Assistant integration.

Run with:
    xtray api serve --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, status
except ImportError as e:
    raise ImportError(
        "FastAPI is not installed. Install with: pip install -e .[api]"
    ) from e

from . import __version__, config
from .core import app_logging


def _load_display_modules() -> tuple[Any | None, Any | None, ImportError | None]:
    try:
        from computer_manager.display_manager import backend as display
        from computer_manager.display_manager import profiles
    except ImportError as exc:
        return None, None, exc
    return display, profiles, None


def create_app(*, unsafe_no_auth: bool | None = None) -> FastAPI:
    display, profiles, display_import_error = _load_display_modules()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app_logging.configure_logging(component="api")
        yield
        app_logging.mark_clean_shutdown("api")

    app = FastAPI(title="XTray", version=__version__, lifespan=lifespan)
    app.state.unsafe_no_auth = (
        config.auth_disabled_by_env() if unsafe_no_auth is None else unsafe_no_auth
    )
    app.state.display_import_error = display_import_error

    def require_bearer_token(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        if app.state.unsafe_no_auth:
            return
        token = config.get_api_token()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API token is not configured; run `xtray config token`",
            )
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing bearer token",
            )

    @app.get("/health")
    def get_health() -> dict:
        profiles_dir = None
        if profiles is not None:
            profiles_dir = str(profiles.profiles_dir())
        return {
            "status": "ok",
            "version": __version__,
            "profiles_dir": profiles_dir,
            "profiles_available": profiles is not None,
            "auth_required": not app.state.unsafe_no_auth,
        }

    @app.get("/profiles")
    def get_profiles() -> dict:
        if profiles is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        return {"profiles": profiles.list_profiles()}

    @app.get("/favorites")
    def get_favorites() -> dict:
        if profiles is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        return {"favorites": profiles.list_favorite_profiles()}

    @app.get("/profiles/{name}")
    def get_profile(name: str) -> dict:
        if profiles is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        try:
            return profiles.load(name)
        except profiles.ProfileNotFound:
            raise HTTPException(
                status_code=404,
                detail=f"profile not found: {name}",
            ) from None
        except profiles.InvalidProfile as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/displays/current")
    def get_current_displays() -> dict:
        if display is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        try:
            return display.get_state().to_dict()
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

    @app.post("/profiles/{name}/apply", dependencies=[Depends(require_bearer_token)])
    def post_apply(name: str) -> dict:
        if profiles is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        try:
            result = profiles.apply(name)
        except profiles.ProfileNotFound:
            raise HTTPException(
                status_code=404,
                detail=f"profile not found: {name}",
            ) from None
        except profiles.InvalidProfile as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        status_text = "ok" if result.ok else "error"
        return {"status": status_text, "applied": name, "result": result.to_dict()}

    @app.post("/profiles/{name}/capture", dependencies=[Depends(require_bearer_token)])
    def post_capture(name: str, overwrite: bool = False) -> dict:
        if profiles is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        try:
            path = profiles.capture(name, overwrite=overwrite)
        except profiles.ProfileAlreadyExists as exc:
            raise HTTPException(
                status_code=409,
                detail=f"profile already exists: {name} (pass ?overwrite=true to replace)",
            ) from exc
        except profiles.InvalidProfile as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return {"status": "ok", "saved": str(path)}

    @app.delete("/profiles/{name}", dependencies=[Depends(require_bearer_token)])
    def delete_profile(name: str) -> dict:
        if profiles is None:
            raise HTTPException(status_code=503, detail="computer_manager is not installed")
        try:
            profiles.delete(name)
        except profiles.ProfileNotFound:
            raise HTTPException(
                status_code=404,
                detail=f"profile not found: {name}",
            ) from None
        except profiles.InvalidProfile as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "ok", "deleted": name}

    return app


def __getattr__(name: str):
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
