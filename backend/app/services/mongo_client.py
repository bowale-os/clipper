from pymongo import AsyncMongoClient


from ..config.secrets import settings

client = AsyncMongoClient(settings.MONGO_CONNECT)

database = client["clipper"]