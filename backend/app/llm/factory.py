import logging
from backend.app.core.config import Settings
from backend.app.llm.gemini_provider import GeminiProvider
from backend.app.llm.http_provider import JsonHttpProvider
from backend.app.llm.interface import LLMProvider

logger = logging.getLogger(__name__)


def build_provider(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "disabled":
        return None
    # Adapter registration is the only provider-specific extension point.
    if settings.llm_provider == "gemini":
        if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
            logger.warning("GEMINI_API_KEY is not configured; using local fallback")
            return None
        return GeminiProvider(settings.gemini_api_key.get_secret_value(),
                              settings.gemini_model, settings.llm_timeout_seconds)
    factories = {"http_json": JsonHttpProvider}
    factory = factories.get(settings.llm_provider)
    if factory is None:
        logger.warning("Unknown LLM_PROVIDER=%s; using local fallback", settings.llm_provider)
        return None
    if (not settings.llm_endpoint or settings.llm_api_key is None or
            not settings.llm_api_key.get_secret_value()):
        logger.warning("LLM endpoint/key are incomplete; using local fallback")
        return None
    return factory(settings.llm_endpoint, settings.llm_api_key.get_secret_value(),
                   settings.llm_timeout_seconds)
