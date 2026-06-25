import os
import json
import logging
from pathlib import Path
from typing import List

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sachcheck.embeddings")

CACHE_FILE = Path(__file__).parent.parent / "data" / "embedding_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

# In-memory cache loaded from disk
_EMBEDDING_CACHE = {}

def _load_cache():
    global _EMBEDDING_CACHE
    if not _EMBEDDING_CACHE and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _EMBEDDING_CACHE = json.load(f)
            logger.info(f"Loaded {len(_EMBEDDING_CACHE)} cached embeddings from disk.")
        except Exception as e:
            logger.warning(f"Failed to load embedding cache: {e}")
            _EMBEDDING_CACHE = {}

def _save_cache():
    try:
         with open(CACHE_FILE, "w", encoding="utf-8") as f:
             json.dump(_EMBEDDING_CACHE, f, indent=2, ensure_ascii=False)
    except Exception as e:
         logger.warning(f"Failed to save embedding cache: {e}")

def get_embedding(text: str) -> List[float]:
    """
    Generates a 768-dimensional vector embedding for the input text using Gemini's
    text-embedding-004 model. Results are cached locally to save API costs.
    """
    text = text.strip()
    if not text:
        return []

    _load_cache()
    
    # Check cache first
    if text in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[text]

    logger.info(f"Cache miss. Generating Gemini embedding for: \"{text[:40]}...\"")
    
    try:
        from llm import _initialize_gemini
        client = _initialize_gemini()
        
        response = client.models.embed_content(
            model="gemini-embedding-2",
            contents=text
        )
        
        if not response.embeddings:
            raise RuntimeError("Failed to retrieve embeddings from Gemini API response.")
            
        embedding_values = response.embeddings[0].values
        
        # Save to cache
        _EMBEDDING_CACHE[text] = embedding_values
        _save_cache()
        
        return embedding_values
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        # In case of API failure or missing keys during offline testing/evaluation,
        # return a dummy vector of 768 dimensions (all zeros) so downstream code doesn't crash.
        logger.warning("Returning a fallback dummy vector due to embedding generation failure.")
        return [0.0] * 768
