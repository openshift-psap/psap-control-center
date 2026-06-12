from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    PROJECT_NAME: str = "PSAP Control Center"
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    
    DATABASE_URL: str = "sqlite+aiosqlite:///./psap_control_center.db"
    
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    KUBECONFIG_STORAGE_PATH: str = "./kubeconfigs"
    
    MLFLOW_BASE_URL: Optional[str] = None
    
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"

    USER_USERNAME: str = "user"
    USER_PASSWORD: str = "user"

    HEARTH_ENABLED: bool = True
    HEARTH_NAMESPACE: str = "hearth"
    HEARTH_KUBECONFIG_PATH: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

os.makedirs(settings.KUBECONFIG_STORAGE_PATH, exist_ok=True)
