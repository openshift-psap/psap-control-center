from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from starlette.concurrency import run_in_threadpool

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import resource_observations
from app.core.auth import require_admin
from app.core.config import settings
from app.schemas.hearth import (
    HearthClusterListResponse,
    HearthClusterResponse,
    HearthConnectResponse,
    HearthCredentialConnectRequest,
    HearthStatusResponse,
)
from app.services.hearth_service import get_hearth_service
from app.services.kubernetes_service import KubernetesService
from app.utils.logger import create_logger

router = APIRouter()
logger = create_logger("HearthAPI")


async def _inventory(db, service, ttl):
    # Only the parsed public inventory enters the database. A changed management
    # connection uses a separate key even when two API workers overlap a reconnect.
    source = await run_in_threadpool(service.inventory_source)

    def discover():
        items = service.list_clusters()
        if source != service.inventory_source():
            raise RuntimeError("Management connection changed")
        return [c.model_dump(mode="json", exclude={"observed_at"}) for c in sorted(items, key=lambda c: c.name)], None

    items, meta = await resource_observations.observe(
        db, source, "inventory", ttl=ttl, discover=lambda *_: run_in_threadpool(discover),
    )
    if source != await run_in_threadpool(service.inventory_source):
        raise HTTPException(503, "Management connection changed")
    return items or [], meta


def _observed_cluster(item, meta):
    if meta["last_check_failed"] or meta["last_checked_at"] is None:
        item = {
            **item, "locked": None, "availability_verified": False, "owner": None, "owner_set_at": None,
            "lock_expires_at": None, "lock_job_name": None, "kubeconfig_status": "Unknown", "conditions": [],
        }
    return HearthClusterResponse(**item, observed_at=meta["last_checked_at"])


@router.get("/status", response_model=HearthStatusResponse)
async def get_hearth_status(db: AsyncSession = Depends(get_db)):
    service = get_hearth_service()
    if not settings.HEARTH_ENABLED or not service.is_configured():
        return HearthStatusResponse(available=False, configured=False)
    try:
        items, meta = await _inventory(db, service, resource_observations.INVENTORY_TTL)
        return HearthStatusResponse(
            available=not meta["last_check_failed"] and meta["last_checked_at"] is not None, configured=True,
            cluster_count=len(items), cluster_names=[c["name"] for c in items],
            total_gpus=sum((c.get("hardware") or {}).get("total_gpus", 0) for c in items),
            locked_clusters=sum(bool(c.get("locked")) for c in items), observed_at=meta["last_checked_at"],
        )
    except Exception as exc:
        logger.warning(f"Hearth status unavailable: {type(exc).__name__}")
        return HearthStatusResponse(available=False, configured=True, error="Hearth is unavailable")


@router.post(
    "/connect",
    response_model=HearthConnectResponse,
)
async def connect_hearth(
    file: UploadFile = File(...),
    _user: dict = Depends(require_admin),
):
    """Upload a kubeconfig for the management cluster to enable Hearth."""
    if not settings.HEARTH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Hearth integration is disabled",
        )

    content = await file.read()
    try:
        kubeconfig_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid file encoding",
        )

    service = get_hearth_service()
    service.save_kubeconfig(kubeconfig_content)

    status = await run_in_threadpool(service.get_status)
    if status.available:
        return HearthConnectResponse(
            success=True,
            message=(
                f"Connected to Hearth — "
                f"{status.cluster_count} cluster(s) discovered"
            ),
        )
    else:
        service.remove_kubeconfig()
        raise HTTPException(
            status_code=400,
            detail=(
                f"Kubeconfig saved but connection failed: "
                f"{status.error}"
            ),
        )


@router.post(
    "/connect/credentials",
    response_model=HearthConnectResponse,
)
async def connect_hearth_with_credentials(
    credentials: HearthCredentialConnectRequest,
    _user: dict = Depends(require_admin),
):
    """Connect to the Hearth/Fournos management cluster as a specific user."""
    if not settings.HEARTH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Hearth integration is disabled",
        )

    login_result = await KubernetesService.login_with_credentials(
        api_server=credentials.api_server_url,
        username=credentials.username,
        password=credentials.password,
        storage_path=settings.KUBECONFIG_STORAGE_PATH,
        cluster_name="hearth-management",
        use_service_account=False,
        allow_stored_password=False,
    )
    if not login_result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=login_result.get("error", "OpenShift login failed"),
        )

    service = get_hearth_service()
    service.reset()
    status = await run_in_threadpool(service.get_status)
    if status.available:
        return HearthConnectResponse(
            success=True,
            message=(
                f"Connected to the management cluster as "
                f"{credentials.username} — "
                f"{status.cluster_count} cluster(s) discovered"
            ),
        )

    service.remove_kubeconfig()
    raise HTTPException(
        status_code=400,
        detail=(
            "OpenShift login succeeded, but the user cannot access Hearth: "
            f"{status.error}"
        ),
    )


@router.post(
    "/disconnect",
    response_model=HearthConnectResponse,
)
async def disconnect_hearth(
    _user: dict = Depends(require_admin),
):
    """Remove the saved Hearth kubeconfig and disconnect."""
    service = get_hearth_service()
    service.remove_kubeconfig()
    return HearthConnectResponse(
        success=True,
        message="Disconnected from Hearth",
    )


@router.get(
    "/clusters",
    response_model=HearthClusterListResponse,
)
async def list_hearth_clusters(db: AsyncSession = Depends(get_db)):
    if not settings.HEARTH_ENABLED:
        return HearthClusterListResponse(clusters=[], total=0, available=False)
    try:
        items, meta = await _inventory(db, get_hearth_service(), resource_observations.LOCK_TTL)
        return HearthClusterListResponse(
            clusters=[_observed_cluster(item, meta) for item in items], total=len(items), observed_at=meta["last_checked_at"],
            available=meta["last_checked_at"] is not None and not meta["last_check_failed"],
        )
    except Exception as exc:
        logger.warning(f"Hearth inventory unavailable: {type(exc).__name__}")
        return HearthClusterListResponse(clusters=[], total=0, available=False)


@router.get("/clusters/{cluster_name}", response_model=HearthClusterResponse)
async def get_hearth_cluster(cluster_name: str, db: AsyncSession = Depends(get_db), allow_saved_hardware: bool = False):
    if not settings.HEARTH_ENABLED:
        raise HTTPException(503, "Hearth integration is disabled")
    try:
        items, meta = await _inventory(db, get_hearth_service(), resource_observations.LOCK_TTL)
    except Exception as exc:
        raise HTTPException(503, "Hearth is unavailable") from exc
    verified = meta["last_checked_at"] is not None and not meta["last_check_failed"]
    if not verified and not allow_saved_hardware:
        raise HTTPException(503, "Hearth availability could not be verified")
    for item in items:
        if item["name"] == cluster_name:
            return _observed_cluster(item, meta)
    if not verified:
        raise HTTPException(503, "Hearth availability could not be verified")
    raise HTTPException(404, f"Hearth cluster '{cluster_name}' not found")
