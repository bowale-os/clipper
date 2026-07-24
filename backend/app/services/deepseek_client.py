from openai import OpenAI

from app.config.secrets import settings

# DeepSeek is OpenAI-compatible, so the OpenAI SDK talks to it by pointing base_url at their
# host. Only detect uses this; transcribe stays on Groq (Whisper) via groq_client.
client = OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
