"""Environment-backed settings for Noodle Box."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    questionnaire_url: str = os.getenv(
        "QUESTIONNAIRE_URL", "http://localhost:8000/feedback?source=questionnaire"
    )
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    location_codes_raw: str = os.getenv("LOCATION_CODES", "LOC-UNI-01,LOC-APT-02")
    default_location_code: str = os.getenv("DEFAULT_LOCATION_CODE", "LOC-UNI-01")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    database_path: str = os.getenv("DATABASE_PATH", "data/noodlebox.db")

    @property
    def location_codes(self) -> list[str]:
        values = [part.strip() for part in self.location_codes_raw.split(",") if part.strip()]
        if self.default_location_code not in values:
            values.insert(0, self.default_location_code)
        return values


settings = Settings()
