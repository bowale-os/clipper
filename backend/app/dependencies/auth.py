import logging

from fastapi import Request, HTTPException, status
from clerk_backend_api import Clerk
import jwt
import httpx

from app.config.secrets import settings

logger = logging.getLogger(__name__)

ENV = settings.ENV
CLERK_FRONTEND_API = settings.CLERK_FRONTEND_API

if ENV == "development":
    CLERK_FRONTEND_API = settings.CLERK_DEV_FRONTEND_API

# The origins allowed to hold a token, kept in step with the CORS list in
# app/main.py. Clerk stamps the asking origin onto the token as "azp".
ALLOWED_PARTIES = {
    "http://localhost:5173",
    "https://clippper.vercel.app",
    "https://clippper.fyi",
    "https://www.clippper.fyi",
}

# Clerk tokens live about 60 seconds, so a slightly fast client clock is enough
# to make a fresh token look expired.
LEEWAY_SECONDS = 30

# cache the keys in memory
_jwks_cache = None

async def get_jwks():
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache

    # Make sure we add the JWKS path
    base_url = CLERK_FRONTEND_API.strip().rstrip("/")
    
    # Remove https:// if user accidentally included it
    if base_url.startswith("https://"):
        base_url = base_url[8:]
    
    jwks_url = f"https://{base_url}"

    logger.debug("Fetching JWKS from: %s", jwks_url)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)

        logger.debug("JWKS fetch status: %s", response.status_code)

        if response.status_code != 200:
            logger.error("JWKS fetch failed (%s): %s", response.status_code, response.text[:400])
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to fetch JWKS: {response.status_code}"
            )
        
        _jwks_cache = response.json()
        return _jwks_cache
    

async def get_current_user(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )
    
    token = auth_header.removeprefix("Bearer ").strip()

    try:
        jwks = await get_jwks()
        header = jwt.get_unverified_header(token)
        
        public_key = None
        for key in jwks["keys"]:
            if key["kid"] == header["kid"]:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break
        
        if not public_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token key"
            )

        # Clerk session tokens carry an "aud" claim we have nothing to match
        # against, and PyJWT rejects a token whose aud we do not name. Clerk's
        # own guidance is to check "azp" (the origin that asked for the token)
        # instead, which is what happens below.
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_exp": True, "verify_aud": False},
            leeway=LEEWAY_SECONDS,
        )

        authorized_party = payload.get("azp")
        if authorized_party and authorized_party not in ALLOWED_PARTIES:
            logger.warning("Token came from an unlisted origin: %s", authorized_party)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        return payload["sub"]

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except jwt.InvalidTokenError as error:
        # Without this the reason is lost and every rejection looks the same.
        logger.warning("Token rejected: %s: %s", type(error).__name__, error)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
