import os
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type

EXPECTED_DIMENSION = 768

class EmbeddingDimensionError(Exception):
    """Raised when an embedding provider produces a vector with unexpected dimensionality."""
    pass

class EmbeddingProviderError(Exception):
    """Raised when the configured embedding provider fails or is misconfigured."""
    pass

def _get_embedding_config():
    """Reads embedding provider configuration dynamically from environment."""
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
    
    # Model defaults based on provider
    if provider == "ollama":
        model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
    else:  # cloud / openai
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
        
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    
    return {
        "provider": provider,
        "model": model,
        "host": host,
        "api_key": api_key
    }

def _generate_ollama_embedding(text: str, model: str, host: str) -> List[float]:
    """Generates embedding via local or remote Ollama server."""
    try:
        import ollama
        client = ollama.Client(host=host, timeout=15.0)
        response = client.embeddings(
            model=model,
            prompt=text
        )
        return response["embedding"]
    except Exception as e:
        raise EmbeddingProviderError(f"Ollama embedding error on host '{host}': {str(e)}") from e

def _generate_cloud_embedding(text: str, model: str, api_key: str) -> List[float]:
    """Generates embedding via cloud API with explicit 768-dimension enforcement."""
    if not api_key:
        raise EmbeddingProviderError(
            "Cloud embedding requested, but neither EMBEDDING_API_KEY nor OPENAI_API_KEY is set."
        )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        # Note: text-embedding-3-small natively supports dimensions=768
        response = client.embeddings.create(
            input=text,
            model=model,
            dimensions=EXPECTED_DIMENSION
        )
        return response.data[0].embedding
    except Exception as e:
        raise EmbeddingProviderError(f"Cloud embedding API error: {str(e)}") from e

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((EmbeddingDimensionError, EmbeddingProviderError)),
    reraise=True
)
def generate_embedding(text: str) -> List[float]:
    """
    Generates an embedding vector using the configured provider.
    Strictly validates that the output is exactly 768 dimensions.
    """
    config = _get_embedding_config()
    provider = config["provider"]
    model = config["model"]
    
    if provider == "ollama":
        raw_vec = _generate_ollama_embedding(text, model, config["host"])
    elif provider in ["cloud", "openai"]:
        raw_vec = _generate_cloud_embedding(text, model, config["api_key"])
    else:
        raise EmbeddingProviderError(f"Unsupported EMBEDDING_PROVIDER: '{provider}'. Supported: ollama, cloud, openai.")
        
    # Strict 768-dimension validation
    if not isinstance(raw_vec, (list, tuple)) or len(raw_vec) != EXPECTED_DIMENSION:
        actual_dim = len(raw_vec) if isinstance(raw_vec, (list, tuple)) else type(raw_vec).__name__
        raise EmbeddingDimensionError(
            f"Embedding dimension mismatch from provider '{provider}': "
            f"expected exactly {EXPECTED_DIMENSION}, got {actual_dim}."
        )
        
    return list(raw_vec)