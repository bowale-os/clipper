from groq import Groq

from app.config.secrets import settings

client = Groq(api_key=settings.GROQ_API_KEY)
