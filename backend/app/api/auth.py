from fastapi import APIRouter, Request, HTTPException, status
from svix.webhooks import Webhook, WebhookVerificationError
from datetime import datetime, timezone
import json

from app.config.secrets import settings
from app.services.mongo_client import database

a_router = APIRouter()

CLERK_WEBHOOK_SECRET = settings.CLERK_WEBHOOK_SIGNING_SECRET

@a_router.post("/clerk-auth")
async def clerk_auth(request: Request):

    #Get raw user data message from clerk as bytes (.body()) not as a dict(.json())
    payload = await request.body()
    headers = dict(request.headers)

    try:
        wh = Webhook(CLERK_WEBHOOK_SECRET)
        message = wh.verify(payload, headers)

        event_type = message.get("type")
        event_data = message.get("data")

        print(event_data, event_type)

        if event_type != "user.created":
            raise HTTPException(status_code=400, detail="user was not authenticated correctly")
        
        return await create_user(event_data)

    except WebhookVerificationError as e:
        print("Webhook verification failed:", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature"
        )

    except Exception as e:
        print("Error processing webhook:", e)
        # Still return 200 in so
        # me cases to stop retries, or 400 to retry
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


async def create_user(data: dict):
    try:
        first_name = data.get("first_name") or ""
        last_name = data.get("last_name") or ""
        email_addresses = data.get("email_addresses", [])
        
        if not email_addresses or not email_addresses[0].get("email_address"):
            raise ValueError("No email address found in Clerk data")

        user_doc = {
            "clerk_id": data["id"],
            "email": email_addresses[0]["email_address"],
            "name": f"{first_name} {last_name}".strip(),
            "created_at": datetime.now(timezone.utc)
        }

        response = await database.users.insert_one(user_doc)
        
        if response.inserted_id:
            print(f"✅ User created successfully: {response.inserted_id}")
            return {
                "success": True,
                "message": "User created successfully",
                "clerk_id": data.get("id"),
                "db_id": str(response.inserted_id)
            }

    except Exception as e:
        print("🔴 Detailed Error creating user:")
        print(f"   Type: {type(e).__name__}")
        print(f"   Message: {e}")
        import traceback
        traceback.print_exc()   # This will show full stack trace
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create user: {str(e)}"
        )