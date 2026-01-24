"""Protocol-based embedding provider interface.

Defines the abstract interface for embedding implementations, enabling
pluggable backends (FastEmbed, OpenAI, local models, etc.) while maintaining
consistent behavior and type safety.

Usage:
    class FastEmbedProvider:
        '''Implements EmbeddingProvider protocol.'''
        
        @property
        def name(self) -> str:
            return "fastembed"
        
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return list(self.model.embed(texts))
    
    # Manager for multiple providers
    manager = EmbeddingManager()
    manager.register_provider(FastEmbedProvider(), set_default=True)
    
    embeddings = await manager.embed(["hello", "world"])
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)


@dataclass
class RerankResult:
    """Result from reranking operation."""
    index: int
    score: float
    text: Optional[str] = None


@dataclass
class EmbeddingConfig:
    """Configuration for embedding providers."""
    provider: str
    model: str
    dims: int
    distance: str = "cosine"
    batch_size: int = 100
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Abstract protocol for embedding providers.
    
    All embedding implementations must follow this interface.
    Enables pluggable backends (OpenAI, local models, etc.)
    """

    @property
    def name(self) -> str:
        """Provider name (e.g., 'fastembed', 'openai')."""
        ...

    @property
    def model(self) -> str:
        """Model name (e.g., 'BAAI/bge-base-en-v1.5')."""
        ...

    @property
    def dims(self) -> int:
        """Embedding dimensions."""
        ...

    @property
    def distance(self) -> str:
        """Distance metric ('cosine' | 'l2' | 'ip')."""
        ...

    @property
    def batch_size(self) -> int:
        """Maximum batch size for embedding requests."""
        ...

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        ...

    async def embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        ...

    async def embed_batch(
        self, texts: List[str], batch_size: Optional[int] = None
    ) -> List[List[float]]:
        """Generate embeddings in batches for optimal performance."""
        ...

    def is_available(self) -> bool:
        """Check if the provider is available and properly configured."""
        ...

    def get_optimal_batch_size(self) -> int:
        """Get optimal batch size for this provider."""
        ...

    def get_max_tokens_per_batch(self) -> int:
        """Get maximum tokens per batch for this provider."""
        ...

    def get_recommended_concurrency(self) -> int:
        """Get recommended concurrent batch count based on provider's rate limits."""
        ...

    def supports_reranking(self) -> bool:
        """Return True if this provider supports reranking."""
        ...


class BaseEmbeddingProvider(ABC):
    """Base class with default implementations for common operations."""

    def __init__(self, config: EmbeddingConfig):
        self._config = config
        self._total_tokens = 0
        self._total_requests = 0

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    @property
    def name(self) -> str:
        return self._config.provider

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def dims(self) -> int:
        return self._config.dims

    @property
    def distance(self) -> str:
        return self._config.distance

    @property
    def batch_size(self) -> int:
        return self._config.batch_size

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        ...

    async def embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        results = await self.embed([text])
        return results[0]

    async def embed_batch(
        self, texts: List[str], batch_size: Optional[int] = None
    ) -> List[List[float]]:
        """Generate embeddings in batches."""
        effective_batch_size = batch_size or self.batch_size
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), effective_batch_size):
            batch = texts[i : i + effective_batch_size]
            embeddings = await self.embed(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def embed_streaming(self, texts: List[str]) -> AsyncIterator[List[float]]:
        """Generate embeddings with streaming results."""
        for text in texts:
            embedding = await self.embed_single(text)
            yield embedding

    def is_available(self) -> bool:
        """Check if provider is available."""
        return True

    def get_optimal_batch_size(self) -> int:
        return self.batch_size

    def get_max_tokens_per_batch(self) -> int:
        return self._config.max_tokens or 8192

    def get_max_documents_per_batch(self) -> int:
        return self.batch_size

    def get_recommended_concurrency(self) -> int:
        return 4

    def get_max_rerank_batch_size(self) -> int:
        return 64

    def supports_reranking(self) -> bool:
        return False

    async def rerank(
        self, query: str, documents: List[str], top_k: Optional[int] = None
    ) -> List[RerankResult]:
        raise NotImplementedError("Reranking not supported by this provider")

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (chars / 4)."""
        return len(text) // 4

    def get_usage_stats(self) -> Dict[str, Any]:
        return {
            "total_tokens": self._total_tokens,
            "total_requests": self._total_requests,
        }

    def reset_usage_stats(self) -> None:
        self._total_tokens = 0
        self._total_requests = 0


@dataclass
class EmbeddingManager:
    """Manager for multiple embedding providers.
    
    Centralizes provider registration and selection.
    """
    
    _providers: Dict[str, EmbeddingProvider] = field(default_factory=dict)
    _default_provider: Optional[str] = None

    def register_provider(
        self, provider: EmbeddingProvider, set_default: bool = False
    ) -> None:
        """Register an embedding provider."""
        self._providers[provider.name] = provider
        if set_default or self._default_provider is None:
            self._default_provider = provider.name

    def get_provider(self, name: Optional[str] = None) -> EmbeddingProvider:
        """Get a provider by name or the default provider."""
        provider_name = name or self._default_provider
        if provider_name is None:
            raise ValueError("No default provider set and no name provided")
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not registered")
        return self._providers[provider_name]

    def list_providers(self) -> List[str]:
        """List registered provider names."""
        return list(self._providers.keys())

    async def embed(
        self, texts: List[str], provider_name: Optional[str] = None
    ) -> List[List[float]]:
        """Generate embeddings using specified or default provider."""
        provider = self.get_provider(provider_name)
        return await provider.embed(texts)

    async def embed_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        provider_name: Optional[str] = None,
    ) -> List[List[float]]:
        """Generate embeddings in batches."""
        provider = self.get_provider(provider_name)
        return await provider.embed_batch(texts, batch_size)


_default_manager: Optional[EmbeddingManager] = None


def get_embedding_manager() -> EmbeddingManager:
    """Get or create the default embedding manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = EmbeddingManager()
    return _default_manager


__all__ = [
    "RerankResult",
    "EmbeddingConfig",
    "EmbeddingProvider",
    "BaseEmbeddingProvider",
    "EmbeddingManager",
    "get_embedding_manager",
]
