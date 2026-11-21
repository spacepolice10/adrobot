from typing import Annotated

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_ignore_empty=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    database_url: str = "sqlite:///adrobot.db"


class Settings(DatabaseSettings):
    keitaro_url: HttpUrl | None = None
    keitaro_api_key: SecretStr | None = None
    keitaro_campaign_domain_id: Annotated[int, Field(gt=0, le=2_147_483_647)] | None = (
        None
    )
    keitaro_campaign_domain: str = "in.posdk.xyz"

    @field_validator("keitaro_url")
    @classmethod
    def validate_tracker_base_url(cls, url: HttpUrl | None) -> HttpUrl | None:
        if url is not None and any(
            part is not None
            for part in (url.username, url.password, url.query, url.fragment)
        ):
            raise ValueError(
                "KEITARO_URL must contain only the scheme, host, optional port and path"
            )
        return url
