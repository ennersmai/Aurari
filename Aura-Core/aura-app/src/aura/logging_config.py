"""Custom logging configuration for uvicorn."""
import logging
from typing import Any

# ---------------------------------------------------------------------------
# Embedding / vector sanitisation – keeps console logs readable
# ---------------------------------------------------------------------------

_EMBEDDING_KEYS = frozenset({
    "embedding",
    "description_embedding",
    "query_embedding",
    "state_vector",
    "momentum_vector",
})


def sanitize_log_payload(obj: Any, max_list_preview: int = 6) -> Any:
    """Recursively replace embedding/vector lists with a compact placeholder.

    A SurrealDB ``create`` or ``select`` can return records containing
    768‑float ``embedding`` arrays that flood the console.  This helper
    walks any dict / list structure and replaces every value whose key
    matches :data:`_EMBEDDING_KEYS` with a string like
    ``"[embedding hidden: 768 floats]"``.

    Returns a *new* object; the original is never mutated.
    """
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for key, value in obj.items():
            if key in _EMBEDDING_KEYS and isinstance(value, list) and value and isinstance(value[0], (int, float)):
                result[key] = f"[{key} hidden: {len(value)} floats]"
            else:
                result[key] = sanitize_log_payload(value, max_list_preview)
        return result

    if isinstance(obj, list):
        # Truncate long non-embedding lists as well (but not embedding lists
        # themselves – those are already caught by the dict branch above).
        if len(obj) > max_list_preview:
            truncated = obj[:max_list_preview]
            return [sanitize_log_payload(v, max_list_preview) for v in truncated] + [
                f"... ({len(obj) - max_list_preview} more items)"
            ]
        return [sanitize_log_payload(v, max_list_preview) for v in obj]

    return obj


class HealthCheckFilter(logging.Filter):
    """Filter out noisy polling requests from access logs."""
    
    # Endpoints to silence
    NOISY_ENDPOINTS = ['/health', '/emotion/current', '/memory/recent', '/api/conversations/', '/goal/active']
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out health checks, emotion polls, and memory polls."""
        # Check if this is an access log message
        if hasattr(record, 'args') and record.args:
            message = str(record.getMessage())
            # Filter out any of the noisy endpoints
            for endpoint in self.NOISY_ENDPOINTS:
                if endpoint in message and 'GET' in message:
                    return False
        return True


def setup_logging_filters():
    """Set up logging filters to reduce noise."""
    # Get uvicorn access logger
    access_logger = logging.getLogger("uvicorn.access")
    
    # Add health check filter
    access_logger.addFilter(HealthCheckFilter())
    
    logging.info("Custom logging filters applied")

