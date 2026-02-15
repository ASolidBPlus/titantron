import json
import logging
from pathlib import Path

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    db_path: str = "data/titantron.db"
    log_level: str = "info"

    # Jellyfin connection (persisted after setup)
    jellyfin_url: str = ""
    jellyfin_token: str = ""
    jellyfin_user_id: str = ""
    jellyfin_device_id: str = ""
    jellyfin_public_url: str = ""  # Client-facing URL (if different from jellyfin_url)

    # Admin
    admin_password: str = ""

    # Frontend static files (set in Docker, empty for dev)
    frontend_dir: str = ""

    # CORS origins (comma-separated, for dev mode)
    cors_origins: str = "http://localhost:5173"

    # Path mapping (Jellyfin path prefix → local path prefix)
    path_map_from: str = ""
    path_map_to: str = ""

    # ML audio detection (opt-in, requires titantron-ml sidecar)
    ml_audio_enabled: bool = False
    ml_service_url: str = ""
    ml_window_secs: int = 30  # analysis window size (2-60, lower = more precise but slower)

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

# Runtime overrides from settings.json (UI-configurable settings)
_runtime_overrides: dict = {}

# Keys that can be changed via the admin settings UI
CONFIGURABLE_KEYS = {"jellyfin_public_url", "admin_password", "scrape_rate_limit", "scrape_burst", "path_map_from", "path_map_to", "ml_audio_enabled", "ml_service_url", "ml_window_secs"}


def _settings_path() -> Path:
    return settings.db_dir / "settings.json"


def load_runtime_settings() -> None:
    global _runtime_overrides
    path = _settings_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            _runtime_overrides = {k: v for k, v in data.items() if k in CONFIGURABLE_KEYS}
            logger.info(f"Loaded runtime settings: {list(_runtime_overrides.keys())}")
        except Exception as e:
            logger.error(f"Failed to load settings.json: {e}")
            _runtime_overrides = {}
    else:
        _runtime_overrides = {}


def save_runtime_settings(data: dict) -> None:
    global _runtime_overrides
    # Only allow configurable keys
    filtered = {k: v for k, v in data.items() if k in CONFIGURABLE_KEYS}
    _runtime_overrides.update(filtered)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_runtime_overrides, indent=2))
    logger.info(f"Saved runtime settings: {list(_runtime_overrides.keys())}")


def get_setting(key: str):
    """Get a setting value, preferring runtime override over env/default."""
    if key in _runtime_overrides:
        return _runtime_overrides[key]
    return getattr(settings, key)
