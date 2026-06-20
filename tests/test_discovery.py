import json
from pathlib import Path

from common.config import settings
from daemon import discovery

FIX = Path(__file__).parent / "fixtures" / "openrouter_sample.json"


def _sample(i: int) -> dict:
    return discovery.normalize_model(json.loads(FIX.read_text())["data"][i])


def test_normalize_extracts_fields():
    m = discovery.normalize_model({
        "id": "a/b", "name": "N", "context_length": 100,
        "architecture": {"modality": "text->text"},
        "pricing": {"prompt": "0.5", "completion": "1"},
    })
    assert m["slug"] == "a/b" and m["name"] == "N" and m["context_length"] == 100
    assert m["price_prompt"] == 0.5 and m["price_completion"] == 1.0
    assert m["raw"]["id"] == "a/b"


def test_normalize_builds_modality_from_lists():
    m = discovery.normalize_model({
        "id": "a/b",
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
    })
    assert m["modality"] == "text+image->text"


def test_normalize_rejects_bad_items():
    assert discovery.normalize_model({}) is None
    assert discovery.normalize_model("x") is None
    assert discovery.normalize_model({"id": 123}) is None


def test_fetch_unwraps_data_envelope():
    fixture = json.loads(FIX.read_text())
    assert len(discovery.fetch_openrouter_models(lambda: fixture)) == 3
    assert discovery.fetch_openrouter_models(lambda: {"nope": 1}) == []


def test_relevance_text_model_passes():
    assert discovery.passes_relevance(_sample(0)) is True


def test_relevance_non_text_output_fails():
    assert discovery.passes_relevance(_sample(1)) is False  # text->image


def test_relevance_small_context_fails():
    assert discovery.passes_relevance(_sample(2)) is False  # 2048 < 8000 floor


def test_relevance_price_cap(monkeypatch):
    pricey = {"modality": "text->text", "context_length": 128000, "price_prompt": 0.001}
    monkeypatch.setattr(settings, "relevance_max_price_prompt", 0.000001)
    assert discovery.passes_relevance(pricey) is False
    monkeypatch.setattr(settings, "relevance_max_price_prompt", None)
    assert discovery.passes_relevance(pricey) is True
