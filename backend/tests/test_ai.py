import json
import httpx
import pytest
from app.services.ai.provider import DemoProvider, GenerationError, OllamaProvider
from app.schemas.content import ProductAnalysis


def test_demo_is_explicit_and_has_no_invented_benefits():
    provider = DemoProvider()
    analysis = provider.analyze_product_image("unused")
    content = provider.generate_social_content(analysis, {})
    assert "DEMO" in analysis.confidence_or_limitations
    assert content.benefits == []
    assert "not AI-generated" in content.disclaimer_or_assumptions


def test_valid_structured_output(monkeypatch):
    analysis = DemoProvider().analyze_product_image("unused")
    monkeypatch.setattr(OllamaProvider, "_post", lambda *args: {"message": {"content": analysis.model_dump_json()}})
    result = OllamaProvider()._generate(ProductAnalysis, "test", "test")
    assert result == analysis


def test_malformed_response_retries_once(monkeypatch):
    calls = []
    def bad(*args):
        calls.append(1)
        return {"message": {"content": "not JSON"}}
    monkeypatch.setattr(OllamaProvider, "_post", bad)
    with pytest.raises(GenerationError) as exc:
        OllamaProvider()._generate(ProductAnalysis, "test", "test")
    assert exc.value.code == "AI_INVALID_CONTENT"
    assert len(calls) == 2


def test_non_vision_model_fails_clearly(monkeypatch):
    monkeypatch.setattr(OllamaProvider, "_post", lambda *args: {"capabilities": ["completion"]})
    with pytest.raises(GenerationError) as exc:
        OllamaProvider().analyze_product_image("unused")
    assert exc.value.code == "VISION_MODEL_REQUIRED"
