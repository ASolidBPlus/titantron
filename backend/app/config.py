from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/titantron.db"
    log_level: str = "info"

    # Jellyfin connection (persisted after setup)
    jellyfin_url: str = ""
    jellyfin_token: str = ""
    jellyfin_user_id: str = ""
    jellyfin_device_id: str = ""

    # Admin
    admin_password: str = ""

    # Frontend static files (set in Docker, empty for dev)
    frontend_dir: str = ""

    # CORS origins (comma-separated, for dev mode)
    cors_origins: str = "http://localhost:5173"

    # Cagematch scraping
    scrape_rate_limit: float = 0.5  # requests per second
    scrape_burst: int = 3
    scrape_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

    model_config = {"env_prefix": "TITANTRON_", "env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def db_dir(self) -> Path:
        return Path(self.db_path).parent


settings = Settings()
