from google.genai import types

from app.services.gemini_client import client

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768


def embed_text(text: str) -> list[float]:
    response = client.models.embed_content(
        model=EMBED_MODEL,
        contents=[text],
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
    )
    return response.embeddings[0].values