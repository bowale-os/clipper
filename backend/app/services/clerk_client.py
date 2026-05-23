from clerk_backend_api import Clerk


from ..config.secrets import settings



clerk_secret = settings.CLERK_SECRET_KEY

clerk_client = Clerk(bearer_auth=clerk_secret)