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


def test_memory_budget_is_sent_to_ollama(monkeypatch):
    analysis = DemoProvider().analyze_product_image("unused")
    seen = []
    def capture(self, endpoint, payload):
        seen.append(payload)
        return {"message": {"content": analysis.model_dump_json()}}
    monkeypatch.setattr(OllamaProvider, "_post", capture)
    OllamaProvider()._generate(ProductAnalysis, "test", "test")
    assert seen[0]["options"]["num_ctx"] == 4096
    assert seen[0]["keep_alive"] == "60s"


def test_placeholder_product_name_is_normalized_to_none():
    analysis = DemoProvider().analyze_product_image("unused").model_dump()
    for placeholder in ["null", "None", "N/A", "unknown", " "]:
        assert ProductAnalysis.model_validate({**analysis, "product_name": placeholder}).product_name is None
    assert ProductAnalysis.model_validate({**analysis, "product_name": "Desk Lamp"}).product_name == "Desk Lamp"


def test_copy_prompt_asks_for_on_screen_captions_not_camera_directions(monkeypatch):
    prompts = []
    def capture(self, schema, model, prompt, image=None):
        prompts.append(prompt)
        return DemoProvider().generate_social_content(DemoProvider().analyze_product_image("unused"), {})
    monkeypatch.setattr(OllamaProvider, "_generate", capture)
    OllamaProvider().generate_social_content(DemoProvider().analyze_product_image("unused"), {})
    assert "on-screen" in prompts[0] and "camera directions" in prompts[0]


def test_video_analysis_sends_storyboard_with_time_order_prompt(monkeypatch, tmp_path):
    sheet = tmp_path / "storyboard.jpg"
    sheet.write_bytes(b"jpeg-bytes")
    analysis = DemoProvider().analyze_product_image("unused")
    seen = []
    def capture(self, endpoint, payload):
        seen.append(payload)
        if endpoint == "/api/show":
            return {"capabilities": ["vision"]}
        return {"message": {"content": analysis.model_dump_json()}}
    monkeypatch.setattr(OllamaProvider, "_post", capture)
    OllamaProvider().analyze_product_video(str(sheet))
    message = seen[-1]["messages"][0]
    assert len(message["images"]) == 1
    assert "2x2" in message["content"] and "time order" in message["content"]


def test_analysis_schema_ends_with_the_concluding_field():
    # The model treats the limitations summary as an ending; a required field after it made
    # constrained decoding loop on whitespace until the token budget ran out.
    properties = list(ProductAnalysis.model_json_schema()["properties"])
    assert properties[-1] == "confidence_or_limitations"
    assert properties.index("facts_needing_user_confirmation") < properties.index("confidence_or_limitations")


def test_each_schema_gets_a_tight_token_budget(monkeypatch):
    from app.schemas.content import SocialContent
    analysis = DemoProvider().analyze_product_image("unused")
    content = DemoProvider().generate_social_content(analysis, {})
    budgets = []
    def capture(self, endpoint, payload):
        budgets.append(payload["options"]["num_predict"])
        body = analysis if payload["format"]["title"] == "ProductAnalysis" else content
        return {"message": {"content": body.model_dump_json()}, "done_reason": "stop"}
    monkeypatch.setattr(OllamaProvider, "_post", capture)
    OllamaProvider()._generate(ProductAnalysis, "test", "test")
    OllamaProvider()._generate(SocialContent, "test", "test")
    assert budgets[0] <= 800 and budgets[1] <= 1500
    assert all(budget <= OllamaProvider().settings.ollama_num_predict for budget in budgets)


def test_truncated_output_is_retried_up_to_three_times_and_logged(monkeypatch, caplog):
    analysis = DemoProvider().analyze_product_image("unused")
    calls = []
    def flaky(self, endpoint, payload):
        calls.append(1)
        if len(calls) < 3:
            return {"message": {"content": '{"product_name": "SECRET-PRODUCT-TEXT"'}, "done_reason": "length"}
        return {"message": {"content": analysis.model_dump_json()}, "done_reason": "stop"}
    monkeypatch.setattr(OllamaProvider, "_post", flaky)
    with caplog.at_level("WARNING"):
        assert OllamaProvider()._generate(ProductAnalysis, "test", "test") == analysis
    assert len(calls) == 3
    assert "truncated=True" in caplog.text and "json_invalid" in caplog.text
    assert "SECRET-PRODUCT-TEXT" not in caplog.text  # model output never reaches logs
