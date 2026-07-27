from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.core.auth import require_admin
from app.core.config import settings
from app.services import billing_csv_service
from app.schemas.cluster import BillingReportInfo, BillingReportListResponse
from app.utils.logger import create_logger
import os

logger = create_logger("BillingAPI")

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post("/upload", response_model=BillingReportInfo)
async def upload_billing_csv(
    file: UploadFile = File(...),
    _user: dict = Depends(require_admin),
):
    """Upload an IBM Cloud billing CSV export."""
    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be a valid UTF-8 CSV")

    billing_month = billing_csv_service._extract_billing_month_from_content(text)
    if not billing_month:
        raise HTTPException(
            status_code=400,
            detail="Could not extract billing month from CSV header. "
            "Expected IBM Cloud billing export format.",
        )

    file_name = f"{billing_month}.csv"
    file_path = os.path.join(settings.BILLING_CSV_STORAGE_PATH, file_name)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    infra_ids = billing_csv_service._read_cluster_ids_from_header(file_path)
    stat = os.stat(file_path)

    logger.info(
        f"Billing CSV uploaded: {billing_month}, "
        f"{stat.st_size} bytes, {len(infra_ids)} clusters detected"
    )

    from datetime import datetime
    return BillingReportInfo(
        billing_month=billing_month,
        file_name=file_name,
        file_size=stat.st_size,
        uploaded_at=datetime.fromtimestamp(stat.st_mtime),
        cluster_count=len(infra_ids),
    )


@router.get("/reports", response_model=BillingReportListResponse)
async def list_billing_reports(
    _user: dict = Depends(require_admin),
):
    """List all uploaded billing CSV reports."""
    reports = billing_csv_service.get_available_reports()
    infos = []
    for r in reports:
        infos.append(BillingReportInfo(
            billing_month=r["billing_month"],
            file_name=r["file_name"],
            file_size=r["file_size"],
            uploaded_at=r["uploaded_at"],
            cluster_count=r.get("cluster_count", 0),
        ))
    return BillingReportListResponse(reports=infos)


@router.delete("/{billing_month}", status_code=204)
async def delete_billing_report(
    billing_month: str,
    _user: dict = Depends(require_admin),
):
    """Delete a billing CSV report by month."""
    file_path = billing_csv_service.find_csv_for_month(billing_month)
    if not file_path:
        raise HTTPException(status_code=404, detail=f"No billing report for {billing_month}")

    os.remove(file_path)
    logger.info(f"Billing CSV deleted: {billing_month}")
