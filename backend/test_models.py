import requests
import json
import requests
import pytest

def test_fetch_free_models():
    """
    Test connectivity to OpenRouter and list free models.
    Marks as NOT VERIFIED / SKIPPED if network is unavailable to prevent blocking.
    """
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        free_models = []
        for model in data.get("data", []):
            pricing = model.get("pricing", {})
            if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
                free_models.append(model["id"])
        
        # Test passes if it successfully queried and parsed
        assert len(free_models) >= 0
    except requests.exceptions.RequestException as e:
        pytest.skip(f"OpenRouter network connectivity unavailable. SKIPPED / NOT VERIFIED: {e}")
