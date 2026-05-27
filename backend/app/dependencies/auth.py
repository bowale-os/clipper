from fastapi import Request, HTTPException, status
from clerk_backend_api import Clerk
import jwt
import httpx

from app.config.secrets import settings

ENV = settings.ENV
CLERK_FRONTEND_API = settings.CLERK_FRONTEND_API

if ENV == "development":
    CLERK_FRONTEND_API = settings.CLERK_DEV_FRONTEND_API

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

    print(f"🔑 Fetching JWKS from: {jwks_url}")   # ← Debug line

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        
        print(f"Status: {response.status_code}")   # ← Debug
        
        if response.status_code != 200:
            print(f"Response: {response.text[:400]}")
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
    
    token = auth_header.replace("Bearer ", "")

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

        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_exp": True}
        )

        return payload["sub"]

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
