from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import require_admin
from app.services.settings_service import SettingsService
from app.services.slack_notifier import send_test_message
from app.utils.logger import create_logger

router = APIRouter()
logger = create_logger("SettingsAPI")

SLACK_WEBHOOK_KEY = "slack_webhook_url"


class SlackSettingsResponse(BaseModel):
    webhook_url: Optional[str] = None
    enabled: bool = False


class SlackSettingsUpdate(BaseModel):
    webhook_url: Optional[str] = None


@router.get("/slack", response_model=SlackSettingsResponse)
async def get_slack_settings(
    _user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    service = SettingsService(db)
    url = await service.get(SLACK_WEBHOOK_KEY)
    return SlackSettingsResponse(
        webhook_url=url,
        enabled=bool(url),
    )


@router.put("/slack", response_model=SlackSettingsResponse)
async def update_slack_settings(
    body: SlackSettingsUpdate,
    _user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    service = SettingsService(db)
    url = body.webhook_url.strip() if body.webhook_url else None
    await service.set(SLACK_WEBHOOK_KEY, url)
    logger.info(f"Slack webhook {'configured' if url else 'cleared'} by {_user['username']}")
    return SlackSettingsResponse(
        webhook_url=url,
        enabled=bool(url),
    )


@router.post("/slack/test")
async def test_slack_webhook(
    _user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    service = SettingsService(db)
    url = await service.get(SLACK_WEBHOOK_KEY)
    if not url:
        raise HTTPException(status_code=400, detail="No Slack webhook URL configured")

    success = await send_test_message(url)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to send test message to Slack")

    return {"status": "ok", "message": "Test message sent successfully"}
