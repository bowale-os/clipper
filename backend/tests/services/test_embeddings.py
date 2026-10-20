from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.services.embeddings as embeddings


def test_embed_text_requests_768_dimensions_and_returns_the_vector(monkeypatch):
    fake = MagicMock()
    fake.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])
    monkeypatch.setattr(embeddings, "client", fake)

    assert embeddings.embed_text("my video.mp4") == [0.1, 0.2]

    kwargs = fake.models.embed_content.call_args.kwargs
    assert kwargs["model"] == "gemini-embedding-001"
    assert kwargs["contents"] == ["my video.mp4"]
    assert kwargs["config"].output_dimensionality == 768 == embeddings.EMBED_DIM


def test_provider_errors_propagate_so_callers_can_degrade(monkeypatch):
    fake = MagicMock()
    fake.models.embed_content.side_effect = RuntimeError("quota")
    monkeypatch.setattr(embeddings, "client", fake)
    with pytest.raises(RuntimeError, match="quota"):
        embeddings.embed_text("x")
