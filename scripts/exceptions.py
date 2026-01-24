"""Structured exception hierarchy for Context-Engine.

Provides a clear taxonomy of errors for better error handling,
logging, and debugging. All exceptions include context about
what operation failed and why.

Usage:
    try:
        parse_file(path)
    except ParsingError as e:
        logger.error(f"Failed to parse {e.file_path}: {e}")
    except ContextEngineError as e:
        logger.error(f"Operation failed: {e}")
"""

from __future__ import annotations

from typing import Optional, Any, Dict


class ContextEngineError(Exception):
    """Base exception for all Context-Engine errors."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}
    
    def __str__(self) -> str:
        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} [{ctx_str}]"
        return self.message


class ValidationError(ContextEngineError):
    """Invalid input or configuration."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        context = {}
        if field:
            context["field"] = field
        if value is not None:
            context["value"] = repr(value)[:100]
        super().__init__(message, context)
        self.field = field
        self.value = value


class ParsingError(ContextEngineError):
    """Failed to parse a file or content."""
    
    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        language: Optional[str] = None,
        line: Optional[int] = None,
    ):
        context = {}
        if file_path:
            context["file"] = file_path
        if language:
            context["language"] = language
        if line is not None:
            context["line"] = line
        super().__init__(message, context)
        self.file_path = file_path
        self.language = language
        self.line = line


class ChunkingError(ContextEngineError):
    """Failed to chunk content."""
    
    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        chunk_index: Optional[int] = None,
    ):
        context = {}
        if file_path:
            context["file"] = file_path
        if chunk_index is not None:
            context["chunk_index"] = chunk_index
        super().__init__(message, context)
        self.file_path = file_path
        self.chunk_index = chunk_index


class EmbeddingError(ContextEngineError):
    """Failed to generate embeddings."""
    
    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
    ):
        context = {}
        if provider:
            context["provider"] = provider
        if model:
            context["model"] = model
        if batch_size is not None:
            context["batch_size"] = batch_size
        super().__init__(message, context)
        self.provider = provider
        self.model = model
        self.batch_size = batch_size


class IndexingError(ContextEngineError):
    """Failed to index content into vector database."""
    
    def __init__(
        self,
        message: str,
        collection: Optional[str] = None,
        file_path: Optional[str] = None,
        point_count: Optional[int] = None,
    ):
        context = {}
        if collection:
            context["collection"] = collection
        if file_path:
            context["file"] = file_path
        if point_count is not None:
            context["points"] = point_count
        super().__init__(message, context)
        self.collection = collection
        self.file_path = file_path
        self.point_count = point_count


class DatabaseError(ContextEngineError):
    """Database operation failed."""
    
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        collection: Optional[str] = None,
    ):
        context = {}
        if operation:
            context["operation"] = operation
        if collection:
            context["collection"] = collection
        super().__init__(message, context)
        self.operation = operation
        self.collection = collection


class SearchError(ContextEngineError):
    """Search operation failed."""
    
    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        collection: Optional[str] = None,
    ):
        context = {}
        if query:
            context["query"] = query[:100]
        if collection:
            context["collection"] = collection
        super().__init__(message, context)
        self.query = query
        self.collection = collection


class ConfigurationError(ContextEngineError):
    """Invalid or missing configuration."""
    
    def __init__(self, message: str, config_key: Optional[str] = None):
        context = {}
        if config_key:
            context["key"] = config_key
        super().__init__(message, context)
        self.config_key = config_key


class ProviderError(ContextEngineError):
    """External provider/service error."""
    
    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
    ):
        context = {}
        if provider:
            context["provider"] = provider
        if status_code is not None:
            context["status"] = status_code
        super().__init__(message, context)
        self.provider = provider
        self.status_code = status_code


class CacheError(ContextEngineError):
    """Cache operation failed."""
    
    def __init__(
        self,
        message: str,
        cache_type: Optional[str] = None,
        key: Optional[str] = None,
    ):
        context = {}
        if cache_type:
            context["cache"] = cache_type
        if key:
            context["key"] = key[:100]
        super().__init__(message, context)
        self.cache_type = cache_type
        self.key = key


class RateLimitError(ProviderError):
    """Rate limit exceeded."""
    
    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        retry_after: Optional[float] = None,
    ):
        super().__init__(message, provider, status_code=429)
        self.retry_after = retry_after
        if retry_after is not None:
            self.context["retry_after"] = retry_after


class TimeoutError(ContextEngineError):
    """Operation timed out."""
    
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        context = {}
        if operation:
            context["operation"] = operation
        if timeout_seconds is not None:
            context["timeout"] = timeout_seconds
        super().__init__(message, context)
        self.operation = operation
        self.timeout_seconds = timeout_seconds


__all__ = [
    "ContextEngineError",
    "ValidationError",
    "ParsingError",
    "ChunkingError",
    "EmbeddingError",
    "IndexingError",
    "DatabaseError",
    "SearchError",
    "ConfigurationError",
    "ProviderError",
    "CacheError",
    "RateLimitError",
    "TimeoutError",
]
