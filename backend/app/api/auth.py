from fastapi import APIRouter, Request, HTTPException, status
from svix.webhooks import Webhook, WebhookVerificationError
from sqlalchemy.dialects.postgresql import insert as pg_insert
import logging

from app.config.secrets import settings
from app.db.models import User
from app.db.session import get_session

a_router = APIRouter()
logger = logging.getLogger(__name__)

CLERK_WEBHOOK_SECRET = settings.CLERK_WEBHOOK_SIGNING_SECRET

@a_router.post("/clerk-auth")
async def clerk_auth(request: Request):

    #Get raw user data message from clerk as bytes (.body()) not as a dict(.json())
    payload = await request.body()
    headers = dict(request.headers)

    wh = Webhook(CLERK_WEBHOOK_SECRET)

    try:
        message = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        logger.warning("Webhook verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    event_type = message.get("type")
    event_data = message.get("data")
    logger.info("Received Clerk webhook event: %s", event_type)


    if event_type != "user.created":
        # Acknowledge unhandled events so Clerk does not retry them.
       return {"success": True, "message": f"Ignored event: {event_type}"}

    try:
        return create_user(event_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing webhook")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


def create_user(data: dict):
    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""
    email_addresses = data.get("email_addresses", [])

    if not email_addresses or not email_addresses[0].get("email_address"):
        raise ValueError("No email address found in Clerk data")

    email = email_addresses[0]["email_address"]
    name = f"{first_name} {last_name}".strip()

    # Upsert: backfills stub rows created by get_current_user_record and handles webhook replays.
    stmt = (
        pg_insert(User)
        .values(clerk_id=data["id"], email=email, name=name)
        .on_conflict_do_update(
            index_elements=["clerk_id"],
            set_={"email": email, "name": name},
        )
        .returning(User.id)
    )

    db = get_session()
    try:
        user_id = db.execute(stmt).scalar_one()
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Failed to create user from Clerk webhook")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create user: {str(e)}"
        )
    finally:
        db.close()

    logger.info("User upserted from Clerk webhook: %s", user_id)
    return {
        "success": True,
        "message": "User created successfully",
        "clerk_id": data.get("id"),
        "db_id": str(user_id),
    }
