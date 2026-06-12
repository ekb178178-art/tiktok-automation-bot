import os
import logging
import httpx

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRIGGER_WORD = "нейро"

ACCESS_TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN", "")

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

DM_TEXT = (
    "Привет! 👋 Как и обещал, лови ссылку на нашего бота.\n\n"
    "Твои любимые зарубежные сервисы в разы дешевле уже внутри. "
    "Запускай бота и забирай доступ:\n"
    "https://t.me/ConnectShop_ai_bot\n\n"
    "💡 Важно: если ссылка не нажимается (в ТикТоке такое бывает), "
    "просто скопируй это сообщение, отправь себе в «Избранное» в Телеграме и перейди оттуда."
)

COMMENT_REPLY_TEXT = (
    "Уже отправил в ЛС! Проверяй директ 🚀 "
    "Если у тебя закрытый профиль — напиши мне в личку слово НЕЙРО"
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="TikTok Automation Webhook")


# ---------------------------------------------------------------------------
# Helper: headers for TikTok API
# ---------------------------------------------------------------------------
def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# TikTok API: reply to comment
# ---------------------------------------------------------------------------
async def reply_to_comment(video_id: str, comment_id: str, text: str) -> None:
    url = f"{TIKTOK_API_BASE}/comment/reply/create/"
    payload = {
        "video_id": video_id,
        "parent_comment_id": comment_id,
        "text": text,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers=_auth_headers(), json=payload)
    if response.status_code != 200:
        logger.error("reply_to_comment failed: %s %s", response.status_code, response.text)
    else:
        logger.info("Comment reply sent to comment_id=%s", comment_id)


# ---------------------------------------------------------------------------
# TikTok API: send DM
# ---------------------------------------------------------------------------
async def send_dm(recipient_open_id: str, text: str) -> None:
    url = f"{TIKTOK_API_BASE}/message/send/"
    payload = {
        "to_user_open_id": recipient_open_id,
        "message_type": "TEXT",
        "content": {"text": text},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers=_auth_headers(), json=payload)
    if response.status_code != 200:
        logger.error("send_dm failed: %s %s", response.status_code, response.text)
    else:
        logger.info("DM sent to open_id=%s", recipient_open_id)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def handle_comment(event: dict) -> None:
    """
    Triggered when a new comment is posted.
    Checks for the trigger word and fires reply + DM.
    """
    comment_text: str = event.get("comment_text", "")
    if TRIGGER_WORD not in comment_text.lower():
        return

    video_id: str = event.get("video_id", "")
    comment_id: str = event.get("comment_id", "")
    user_open_id: str = event.get("user_open_id", "")

    logger.info("Trigger word detected in comment from open_id=%s", user_open_id)

    # Fire both actions concurrently
    import asyncio
    await asyncio.gather(
        reply_to_comment(video_id, comment_id, COMMENT_REPLY_TEXT),
        send_dm(user_open_id, DM_TEXT),
    )


async def handle_direct_message(event: dict) -> None:
    """
    Triggered when a user sends a DM.
    Checks for the trigger word and replies with the bot link.
    """
    message_text: str = event.get("message", {}).get("text", "")
    if TRIGGER_WORD not in message_text.lower():
        return

    sender_open_id: str = event.get("sender_open_id", "")
    logger.info("Trigger word detected in DM from open_id=%s", sender_open_id)

    await send_dm(sender_open_id, DM_TEXT)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=PlainTextResponse)
@app.head("/")
async def verify_webhook(request: Request) -> Response:
    """
    TikTok sends a GET request with a 'challenge' query parameter
    to verify the webhook endpoint. We must echo it back.
    """
    challenge = request.query_params.get("challenge", "")
    if challenge:
        logger.info("Webhook verification challenge received.")
        return PlainTextResponse(content=challenge)
    return PlainTextResponse(content="OK")


@app.post("/webhook")
async def receive_webhook(request: Request) -> dict:
    """
    Receives all TikTok webhook events.
    Routes to the appropriate handler based on event type.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.error("Failed to parse request body: %s", exc)
        return {"status": "error", "detail": "invalid json"}

    logger.info("Webhook received: %s", body)

    event_type: str = body.get("event", "")
    data: dict = body.get("data", {})

    if event_type == "comment.create" and data:
        await handle_comment(data)
    elif event_type == "message.receive" and data:
        await handle_direct_message(data)
    else:
        logger.info("Unhandled event type: %s", event_type)

    # TikTok expects a 200 OK response
    return {"status": "ok"}
