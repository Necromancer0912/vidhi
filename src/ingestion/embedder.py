"""
NyayaBot — Embedding via Ollama (GPU-accelerated).

Run on your RTX 4060 Ti PC:
  ollama pull nomic-embed-text    (768d, 274MB, very fast on GPU)
  ollama pull mxbai-embed-large   (1024d, 670MB, higher quality)
  ollama pull bge-m3              (1024d, 1.2GB, multilingual, best for Hindi too)

Then run this script on the PC, copy the output JSON to this Mac.
On Mac (production API), embeddings are generated for query-time only
using the Ollama API over the network (or locally if Ollama is installed here too).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class OllamaEmbedder:
    """
    GPU-accelerated embeddings via Ollama.

    Embeds text using the Ollama API (local or remote).
    Falls back to sentence-transformers (CPU) if Ollama is unavailable.

    For GPU embedding on 4060 Ti:
        - nomic-embed-text: ~2ms/chunk on GPU vs ~80ms on CPU → 40x faster
        - Can embed all 500+ legal chunks in under 5 seconds
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None
        self._fallback_model = None

        # nomic-embed-text: 768d
        # mxbai-embed-large: 1024d
        # bge-m3: 1024d
        self._dim_map = {
            "nomic-embed-text": 768,
            "mxbai-embed-large": 1024,
            "bge-m3": 1024,
            "bge-large-en-v1.5": 1024,
            "qwen3-embedding": 1024,
            "qwen3-embedding:0.6b": 1024,
            "qwen3-embedding:4b": 2560,
            "snowflake-arctic-embed": 1024,
            "snowflake-arctic-embed:335m": 1024,
            "bge-large": 1024,
            "bge-large:335m": 1024,
        }

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def is_available(self) -> bool:
        """Check if Ollama server is reachable and the embedding model is pulled."""
        try:
            r = self._get_client().get(f"{self.base_url}/api/tags", timeout=3)
            if r.status_code != 200:
                return False

            # Check if model is pulled
            try:
                models = [m["name"] for m in r.json().get("models", [])]
                model_exists = any(
                    self.model == m or f"{self.model}:latest" == m or m.startswith(f"{self.model}:")
                    for m in models
                )
                if not model_exists:
                    logger.warning(
                        f"\n"
                        f"⚠ Ollama is running, but model '{self.model}' was not found in the installed models list.\n"
                        f"  Available models on your GPU PC: {models}\n"
                        f"  Please open a terminal and run: ollama pull {self.model}\n"
                    )
                    return False
            except Exception as e:
                logger.warning(f"Failed to check pulled Ollama models: {e}")
            return True
        except Exception:
            return False

    def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns normalized float vector."""
        try:
            client = self._get_client()
            embedding = None
            is_nomic = "nomic" in self.model.lower()
            input_text = f"search_document: {text}" if is_nomic else text

            try:
                # Try the modern /api/embed endpoint first
                resp = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": input_text},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    logger.warning(f"Ollama /api/embed returned {resp.status_code}: {resp.text}")
                resp.raise_for_status()
                embedding = resp.json()["embeddings"][0]
            except Exception as e1:
                # Fallback to the legacy /api/embeddings endpoint
                resp = client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": input_text},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Ollama /api/embeddings returned {resp.status_code}: {resp.text}"
                    )
                resp.raise_for_status()
                embedding = resp.json()["embedding"]

            # L2 normalize
            v = np.array(embedding)
            norm = np.linalg.norm(v)
            return (v / norm if norm > 0 else v).tolist()

        except Exception as e:
            logger.warning(f"Ollama embed failed: {e}, falling back to sentence-transformers")
            return self._fallback_embed(text)

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """
        Embed a batch of texts using Ollama's /api/embed batch endpoint.
        """
        if not texts:
            return []

        try:
            client = self._get_client()
            results = []
            is_nomic = "nomic" in self.model.lower()

            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i : i + batch_size]
                formatted_texts = [f"search_document: {t}" if is_nomic else t for t in batch_texts]
                resp = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": formatted_texts},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Ollama batch /api/embed returned {resp.status_code}: {resp.text}"
                    )
                resp.raise_for_status()
                embeddings = resp.json()["embeddings"]

                for emb in embeddings:
                    v = np.array(emb)
                    norm = np.linalg.norm(v)
                    normalized = (v / norm if norm > 0 else v).tolist()
                    results.append(normalized)
            return results

        except Exception as e:
            logger.warning(f"Ollama batch embed failed: {e}, falling back to sequential embed")
            results = []
            for text in texts:
                results.append(self.embed(text))
            return results

    def _fallback_embed(self, text: str) -> list[float]:
        """Fallback using HuggingFace sentence-transformers if Ollama is down."""
        if self._fallback_model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            hf_model = "nomic-ai/nomic-embed-text-v1" if "nomic" in self.model else self.model
            logger.info(f"Loading HF fallback model: {hf_model}")

            # Load model (sentence-transformers will automatically use CUDA if torch.cuda.is_available() is True)
            self._fallback_model = SentenceTransformer(hf_model, trust_remote_code=True)

            if torch.backends.mps.is_available():
                self._fallback_model = self._fallback_model.to("mps")
                logger.info("✓ HF fallback running on Apple Silicon GPU (MPS)")
            elif torch.cuda.is_available():
                self._fallback_model = self._fallback_model.to("cuda")
                logger.info("✓ HF fallback running on NVIDIA GPU (CUDA)")
            else:
                logger.info("✓ HF fallback running on CPU")

        # Nomic model requires search_document prefix
        is_nomic = "nomic" in self.model.lower()
        input_text = f"search_document: {text}" if is_nomic else text

        v = self._fallback_model.encode(input_text, normalize_embeddings=True)
        return v.tolist()

    @property
    def dimension(self) -> int:
        return self._dim_map.get(self.model, 768)


class LlamaCppEmbedder:
    """
    Embeddings via llama.cpp's OpenAI-compatible /v1/embeddings endpoint.

    Exposes the same embed() / embed_batch() / dimension interface as OllamaEmbedder
    so it can be used as a drop-in replacement.

    Falls back to sentence-transformers (CPU) if the llama-server is unreachable.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        model: str = "nomic-embed-text",
        api_key: str = "",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None
        self._fallback_model = None

        self._dim_map = {
            "nomic-embed-text": 768,
            "mxbai-embed-large": 1024,
            "bge-m3": 1024,
            "bge-large-en-v1.5": 1024,
            "qwen3-embedding": 1024,
            "qwen3-embedding:0.6b": 1024,
            "qwen3-embedding:4b": 2560,
            "snowflake-arctic-embed": 1024,
            "snowflake-arctic-embed:335m": 1024,
            "bge-large": 1024,
            "bge-large:335m": 1024,
        }

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            )
        return self._client

    def embed(self, text: str) -> list[float]:
        """
        Embed a single text for query-time retrieval.

        Uses the 'search_query:' nomic prefix (NOT 'search_document:' — that is
        for indexing).  Returns an L2-normalised float vector.
        """
        try:
            is_nomic = "nomic" in self.model.lower()
            input_text = f"search_query: {text}" if is_nomic else text

            resp = self._get_client().post(
                f"{self.base_url}/v1/embeddings",
                json={"model": self.model, "input": input_text},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            embedding = resp.json()["data"][0]["embedding"]

            v = np.array(embedding)
            norm = np.linalg.norm(v)
            return (v / norm if norm > 0 else v).tolist()

        except Exception as e:
            logger.warning(f"llama.cpp embed failed: {e}, falling back to sentence-transformers")
            return self._fallback_embed(text)

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """
        Embed a batch of texts for document ingestion.

        Uses the 'search_document:' nomic prefix (indexing path).
        Falls back to sequential embed() calls if the batch request fails.
        """
        if not texts:
            return []

        try:
            client = self._get_client()
            results = []
            is_nomic = "nomic" in self.model.lower()

            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i : i + batch_size]
                formatted = [f"search_document: {t}" if is_nomic else t for t in batch_texts]
                resp = client.post(
                    f"{self.base_url}/v1/embeddings",
                    json={"model": self.model, "input": formatted},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                for item in resp.json()["data"]:
                    v = np.array(item["embedding"])
                    norm = np.linalg.norm(v)
                    results.append((v / norm if norm > 0 else v).tolist())

            return results

        except Exception as e:
            logger.warning(f"llama.cpp batch embed failed: {e}, falling back to sequential embed")
            return [self.embed(t) for t in texts]

    def _fallback_embed(self, text: str) -> list[float]:
        """Fallback using HuggingFace sentence-transformers if llama-server is down."""
        if self._fallback_model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            hf_model = "nomic-ai/nomic-embed-text-v1" if "nomic" in self.model else self.model
            logger.info(f"Loading HF fallback model: {hf_model}")

            self._fallback_model = SentenceTransformer(hf_model, trust_remote_code=True)

            if torch.backends.mps.is_available():
                self._fallback_model = self._fallback_model.to("mps")
                logger.info("✓ HF fallback running on Apple Silicon GPU (MPS)")
            elif torch.cuda.is_available():
                self._fallback_model = self._fallback_model.to("cuda")
                logger.info("✓ HF fallback running on NVIDIA GPU (CUDA)")
            else:
                logger.info("✓ HF fallback running on CPU")

        is_nomic = "nomic" in self.model.lower()
        input_text = f"search_document: {text}" if is_nomic else text

        v = self._fallback_model.encode(input_text, normalize_embeddings=True)
        return v.tolist()

    @property
    def dimension(self) -> int:
        return self._dim_map.get(self.model, 768)


# NOTE: get_embedding_model() is cached per-process via lru_cache.
# Changing EMBED_PROVIDER (ollama <-> llamacpp) requires a full server restart.
@lru_cache(maxsize=1)
def get_embedding_model():
    """Return the singleton embedder selected by settings.embed_provider."""
    from src.config import settings

    if settings.embed_provider == "llamacpp":
        # Use the dedicated embedding server (port 8081), not the LLM server (port 8080)
        embedder = LlamaCppEmbedder(
            base_url=settings.llamacpp_embed_url,
            model=settings.llamacpp_embed_model,
            api_key=settings.llamacpp_api_key,
        )
        logger.info(
            f"✓ llama.cpp embedder ready: {settings.llamacpp_embed_model} @ {settings.llamacpp_embed_url}"
        )
        return embedder
    else:  # ollama (default)
        embedder = OllamaEmbedder(
            model=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        if embedder.is_available():
            logger.info(
                f"✓ Ollama embedder ready: {settings.ollama_embed_model} @ {settings.ollama_base_url}"
            )
        else:
            logger.warning("⚠ Ollama not reachable — will use CPU fallback (sentence-transformers)")
        return embedder
