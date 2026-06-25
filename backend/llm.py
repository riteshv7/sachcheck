import os
import json
import time
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sachcheck.llm")

# Load environment variables from .env
load_dotenv()

_GEMINI_CLIENT = None
_ANTHROPIC_CLIENT = None

# Fallback chain for Gemini models to bypass daily free-tier quotas on specific preview models
GEMINI_MODEL_FALLBACK_CHAIN = [
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-pro-latest"
]

def get_llm_provider():
    """Get the configured LLM provider and model from environment variables."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "anthropic":
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    else:
        provider = "gemini"
        # Use first model in chain as default if not specified
        model = os.getenv("GEMINI_MODEL", GEMINI_MODEL_FALLBACK_CHAIN[0])
    return provider, model

def _initialize_gemini():
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is not None:
        return _GEMINI_CLIENT
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
    if not api_key:
        raise ValueError(
            "Gemini API key is missing. Please set GEMINI_API_KEY in backend/.env or your environment.\n"
            "You can get a free key from https://aistudio.google.com"
        )
    
    from google import genai
    _GEMINI_CLIENT = genai.Client(api_key=api_key)
    return _GEMINI_CLIENT

def _initialize_anthropic():
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is not None:
        return _ANTHROPIC_CLIENT
        
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "Anthropic API key is missing. Please set ANTHROPIC_API_KEY in backend/.env or your environment.\n"
            "You can get a key from https://console.anthropic.com"
        )
    
    import anthropic
    _ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=api_key)
    return _ANTHROPIC_CLIENT

def call_llm(prompt: str, system_instruction: str = None, json_mode: bool = False) -> str:
    """
    Calls the configured LLM (Gemini or Claude) and returns the text response.
    Includes robust retry logic with exponential backoff and a multi-model fallback chain
    for rate limits (429) and server errors (503).
    
    Args:
        prompt: The main user prompt.
        system_instruction: Optional system instruction/prompt to guide the model.
        json_mode: If True, requests and configures the LLM to return valid JSON.
    """
    provider, config_model = get_llm_provider()
    
    if provider == "gemini":
        client = _initialize_gemini()
        from google.genai import types
        from google.genai.errors import APIError
        
        # Configure generation parameters using the new SDK's types
        config = types.GenerateContentConfig()
        if system_instruction:
            config.system_instruction = system_instruction
        if json_mode:
            config.response_mime_type = "application/json"
            
        # Construct the model list: try the configured model first, then fall back to others in the chain
        models_to_try = [config_model]
        for m in GEMINI_MODEL_FALLBACK_CHAIN:
            if m not in models_to_try:
                models_to_try.append(m)
                
        last_exception = None
        
        for model_name in models_to_try:
            max_retries = 3
            base_delay = 3.0
            
            logger.info(f"Attempting LLM call with model: {model_name}")
            
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config
                    )
                    return response.text
                except APIError as e:
                    # Check if error is rate limit (429) or temporary server error (503)
                    is_quota_exhausted = (e.code == 429 and "quota" in str(e).lower())
                    is_retryable = (e.code == 429 or e.code == 503) and not is_quota_exhausted
                    
                    # If it's a hard daily quota limit, don't waste time retrying this model; fall back immediately
                    if is_quota_exhausted:
                        logger.warning(
                            f"Daily quota exhausted for model '{model_name}'. "
                            f"Moving to next fallback model in the chain..."
                        )
                        last_exception = e
                        break  # Break out of the retry loop to try the next model
                        
                    if is_retryable and attempt < max_retries - 1:
                        sleep_time = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Gemini API error (code {e.code}) for '{model_name}' on attempt {attempt+1}/{max_retries}. "
                            f"Retrying in {sleep_time:.1f}s... Details: {e.message or str(e)}"
                        )
                        time.sleep(sleep_time)
                        continue
                        
                    # If we've exhausted retries on this model or it's non-retryable
                    logger.warning(f"Model '{model_name}' failed after {attempt+1} attempts: {e}")
                    last_exception = e
                    break  # Try next model in chain
                except Exception as e:
                    # Catch other network/unexpected errors
                    if attempt < max_retries - 1:
                        sleep_time = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Unexpected error for '{model_name}' on attempt {attempt+1}/{max_retries}. "
                            f"Retrying in {sleep_time:.1f}s... Details: {str(e)}"
                        )
                        time.sleep(sleep_time)
                        continue
                    logger.warning(f"Unexpected error for '{model_name}' failed: {e}")
                    last_exception = e
                    break  # Try next model in chain
                    
        # If we got here, all models in the chain failed
        logger.error("All models in the Gemini fallback chain failed.")
        raise last_exception
        
    elif provider == "anthropic":
        client = _initialize_anthropic()
        
        kwargs = {
            "model": model_name,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        if system_instruction:
            kwargs["system"] = system_instruction
            
        if json_mode:
            if "json" not in prompt.lower() and "json" not in (system_instruction or "").lower():
                kwargs["messages"][0]["content"] = prompt + "\n\nCRITICAL: Return the response strictly as a valid JSON object."
                
        # Simple retry for Anthropic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.messages.create(**kwargs)
                return response.content[0].text
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise e
    
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
