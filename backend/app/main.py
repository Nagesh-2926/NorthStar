import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from backend.app.api.router import api_router
from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory
from backend.app.llm.factory import build_provider
from backend.app.llm.service import StudyPlanService
from backend.app.ml.model_manager import ModelManager
from backend.app.services.email_notifications import EmailNotificationService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    engine = build_engine(config.database_url)

    app = FastAPI(title="Student Support API", version="1.0.0",
        description="Human-reviewed student support, academic records, and ML decision-support APIs.")
    app.state.settings = config
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.model_manager = ModelManager(config.model_dir)
    app.state.email_notifications = EmailNotificationService(config)
    app.state.study_plan_service = StudyPlanService(build_provider(config))
    app.add_middleware(CORSMiddleware, allow_origins=config.allowed_origins,
        allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        # Chrome sends Access-Control-Request-Private-Network on local preflights;
        # without this the preflight is rejected with 400 and the UI cannot reach the API.
        allow_private_network=True)
    app.include_router(api_router, prefix="/api")

    @app.get("/health", tags=["system"])
    def health():
        # Readiness verifies the configured database without disclosing its URL.
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.warning("Database health check failed")
            raise HTTPException(status_code=503, detail="Database is temporarily unavailable") from exc
        return {"status": "ok"}

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        safe_errors = [{"loc": error.get("loc", []), "msg": error.get("msg", "Invalid value"),
                        "type": error.get("type", "value_error")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        # Database and provider exception text can contain credentials or submitted
        # records. Keep operational context without logging the exception payload.
        logger.error("Unhandled API error for %s %s (%s)",
                     request.method, request.url.path, type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred"})

    return app


app = create_app()
