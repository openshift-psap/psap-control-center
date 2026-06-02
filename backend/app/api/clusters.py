from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.auth import require_auth
from app.services.cluster_service import ClusterService
from app.services.kubernetes_service import KubernetesService
from app.schemas.cluster import (
    ClusterCreate,
    ClusterUpdate,
    ClusterResponse,
    ClusterStatus,
    ClusterListResponse,
    GpuAllocationStatus as GpuAllocationStatusSchema,
)
from app.utils.logger import create_logger

router = APIRouter()
logger = create_logger("ClustersAPI")


# Static routes must be registered before dynamic /{cluster_id} routes
@router.post("/validate-kubeconfig")
async def validate_kubeconfig(
    file: UploadFile = File(...),
    _user: str = Depends(require_auth),
):
    content = await file.read()
    try:
        kubeconfig_content = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid file encoding")
    
    result = KubernetesService.parse_kubeconfig(kubeconfig_content)
    
    if not result.get("valid"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result


from pydantic import BaseModel

class CredentialsLogin(BaseModel):
    api_server_url: str
    username: str
    password: str


@router.post("/test-credentials")
async def test_credentials(
    credentials: CredentialsLogin,
    _user: str = Depends(require_auth),
):
    """
    Test if credentials can connect to an OpenShift cluster.
    Does not save anything, just validates the connection.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await KubernetesService.login_with_credentials(
            api_server=credentials.api_server_url,
            username=credentials.username,
            password=credentials.password,
            storage_path=tmpdir,
            cluster_name="test-connection"
        )
        
        if result.get("success"):
            kubeconfig_path = result.get("kubeconfig_path")
            if kubeconfig_path and os.path.exists(kubeconfig_path):
                os.remove(kubeconfig_path)
            
            return {
                "valid": True,
                "api_server": result.get("api_server"),
                "auth_type": result.get("auth_type")
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error"))


@router.get("", response_model=ClusterListResponse)
async def list_clusters(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    service = ClusterService(db)
    clusters, total = await service.get_clusters(skip, limit, active_only)
    return ClusterListResponse(
        clusters=[ClusterResponse.model_validate(c) for c in clusters],
        total=total
    )


@router.post("", response_model=ClusterResponse, status_code=201)
async def create_cluster(
    cluster_data: ClusterCreate,
    _user: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    service = ClusterService(db)
    
    existing = await service.get_cluster_by_name(cluster_data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Cluster with this name already exists")
    
    try:
        cluster = await service.create_cluster(cluster_data)
        return ClusterResponse.model_validate(cluster)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    return ClusterResponse.model_validate(cluster)


@router.put("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    cluster_data: ClusterUpdate,
    _user: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    service = ClusterService(db)
    cluster = await service.update_cluster(cluster_id, cluster_data)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    return ClusterResponse.model_validate(cluster)


@router.delete("/{cluster_id}", status_code=204)
async def delete_cluster(
    cluster_id: str,
    _user: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    service = ClusterService(db)
    deleted = await service.delete_cluster(cluster_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Cluster not found")


@router.get("/{cluster_id}/status", response_model=ClusterStatus)
async def get_cluster_status(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    service = ClusterService(db)
    status = await service.get_cluster_status(cluster_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    return status


@router.post("/{cluster_id}/refresh", response_model=ClusterStatus)
async def refresh_cluster_status(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    service = ClusterService(db)
    status = await service.refresh_cluster_status(cluster_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    return status


@router.post("/{cluster_id}/kubeconfig", response_model=ClusterResponse)
async def upload_kubeconfig(
    cluster_id: str,
    file: UploadFile = File(...),
    _user: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    service = ClusterService(db)
    
    content = await file.read()
    try:
        kubeconfig_content = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid file encoding")
    
    try:
        cluster = await service.upload_kubeconfig(cluster_id, kubeconfig_content)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster not found")
        return ClusterResponse.model_validate(cluster)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{cluster_id}/login", response_model=ClusterResponse)
async def login_with_credentials(
    cluster_id: str,
    credentials: CredentialsLogin,
    _user: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Login to an existing cluster using kubeadmin credentials.
    This will authenticate and update the cluster's kubeconfig.
    """
    from app.core.config import settings
    
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    try:
        login_result = await KubernetesService.login_with_credentials(
            api_server=credentials.api_server_url,
            username=credentials.username,
            password=credentials.password,
            storage_path=settings.KUBECONFIG_STORAGE_PATH,
            cluster_name=cluster.name
        )
        
        if not login_result.get("success"):
            raise HTTPException(status_code=400, detail=login_result.get("error"))
        
        cluster.kubeconfig_path = login_result.get("kubeconfig_path")
        cluster.api_server_url = login_result.get("api_server")
        cluster.status = "pending"
        
        await db.commit()
        await db.refresh(cluster)
        
        await service.refresh_cluster_status(cluster_id)
        await db.refresh(cluster)
        
        return ClusterResponse.model_validate(cluster)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{cluster_id}/reauthenticate", response_model=ClusterResponse)
async def reauthenticate_cluster(
    cluster_id: str,
    credentials: CredentialsLogin,
    _user: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-authenticate to a cluster with fresh credentials.
    Use when the OAuth token has expired.
    """
    from app.core.config import settings
    
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    try:
        login_result = await KubernetesService.login_with_credentials(
            api_server=credentials.api_server_url,
            username=credentials.username,
            password=credentials.password,
            storage_path=settings.KUBECONFIG_STORAGE_PATH,
            cluster_name=cluster.name
        )
        
        if not login_result.get("success"):
            raise HTTPException(status_code=400, detail=login_result.get("error"))
        
        cluster.kubeconfig_path = login_result.get("kubeconfig_path")
        cluster.api_server_url = login_result.get("api_server")
        cluster.status = "pending"
        
        await db.commit()
        await db.refresh(cluster)
        
        await service.refresh_cluster_status(cluster_id)
        await db.refresh(cluster)
        
        return ClusterResponse.model_validate(cluster)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{cluster_id}/topology")
async def get_cluster_topology(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get cluster topology for visualization."""
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    if not cluster.kubeconfig_path:
        raise HTTPException(status_code=400, detail="Cluster has no kubeconfig configured")
    
    try:
        k8s_service = KubernetesService(cluster.kubeconfig_path)
        topology = k8s_service.get_topology()
        return topology
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{cluster_id}/gpu-status", response_model=GpuAllocationStatusSchema)
async def get_gpu_status(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get live GPU allocation status via DRA or legacy counting."""
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    if not cluster.kubeconfig_path:
        raise HTTPException(status_code=400, detail="Cluster has no kubeconfig configured")

    try:
        k8s_service = KubernetesService(cluster.kubeconfig_path)
        allocation = k8s_service.get_gpu_allocation()
        return GpuAllocationStatusSchema(
            gpu_allocation_mode=allocation.gpu_allocation_mode,
            dra_available=allocation.dra_available,
            dra_api_version=allocation.dra_api_version,
            total_gpus=allocation.total_gpus,
            allocated_gpus=allocation.allocated_gpus,
            free_gpus=allocation.free_gpus,
            gpu_types=[{
                "product": t.product,
                "count": t.count,
                "allocated": t.allocated,
                "free": t.free,
                "node_count": t.node_count,
            } for t in allocation.gpu_types],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{cluster_id}/ocp-details")
async def get_ocp_details(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get OpenShift-specific cluster details."""
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    if not cluster.kubeconfig_path:
        raise HTTPException(status_code=400, detail="Cluster has no kubeconfig configured")
    
    try:
        k8s_service = KubernetesService(cluster.kubeconfig_path)
        ocp_details = k8s_service.get_ocp_details()
        return ocp_details
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{cluster_id}/operators")
async def get_cluster_operators(
    cluster_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get installed operators."""
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    if not cluster.kubeconfig_path:
        raise HTTPException(status_code=400, detail="Cluster has no kubeconfig configured")
    
    try:
        k8s_service = KubernetesService(cluster.kubeconfig_path)
        operators = k8s_service.get_operators()
        return {"operators": operators, "total": len(operators)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{cluster_id}/workloads")
async def get_cluster_workloads(
    cluster_id: str,
    namespace: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get pods and deployments with node information."""
    service = ClusterService(db)
    cluster = await service.get_cluster(cluster_id)
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    if not cluster.kubeconfig_path:
        raise HTTPException(status_code=400, detail="Cluster has no kubeconfig configured")
    
    try:
        k8s_service = KubernetesService(cluster.kubeconfig_path)
        workloads = k8s_service.get_workloads(namespace)
        return workloads
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
