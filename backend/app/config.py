"""Application settings and filesystem paths for KabloCast."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment or defaults."""

    model_config = SettingsConfigDict(env_prefix="KABLOCAST_", extra="ignore")

    app_name: str = "KabloCast"
    host: str = "127.0.0.1"
    port: int = 8765
    project_root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = project_root / "data"
    db_path: Path = data_dir / "kablocast.db"
    uxplay_dir: Path = project_root / "runtime" / "uxplay"
    frontend_dist_dir: Path = project_root / "frontend" / "dist"
    driver_backup_dir: Path = data_dir / "driver_backups"
    airplay_name: str = "KabloCast"
    default_hotspot_mbps: float = 8.5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings and ensure runtime data directories exist."""
    cfg = Settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.driver_backup_dir.mkdir(parents=True, exist_ok=True)
    return cfg
