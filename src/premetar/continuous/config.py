"""Versioned conservative experiment settings; no credentials or LLM runtime."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from premetar.pws.models import QCConfig
from premetar.sources import STATIONS


class PollPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    minimum_poll_interval: float = Field(default=300, ge=300)
    maximum_poll_interval: float = Field(default=1800, ge=300)
    request_spacing: float = Field(default=1, ge=1, le=30)
    timeout_seconds: float = Field(default=20, ge=1, le=60)
    max_attempts: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def ordered(self) -> "PollPolicy":
        if self.maximum_poll_interval < self.minimum_poll_interval:
            raise ValueError("Invalid provider interval bounds")
        return self


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    experiment: str = "continuous-v1"
    airports: list[str] = ["EDDM", "EHAM", "EPWA", "EGLL"]
    providers: list[str] = ["opensensemap", "sensor_community"]
    polling_limits: dict[str, PollPolicy] = Field(default_factory=dict)
    max_stations_per_provider_airport: int = Field(default=4, ge=1, le=20)
    minimum_poll_interval: float = Field(default=300, ge=300)
    maximum_poll_interval: float = Field(default=1800, ge=300)
    discovery_seconds: float = Field(default=86400, ge=3600)
    qc: QCConfig = Field(default_factory=QCConfig)
    quality_seconds: float = Field(default=3600, ge=3600)
    checkpoints: list[int] = [600, 300, 180, 120, 60]
    checkpoint_tolerance: float = Field(default=5, gt=0, le=10)
    database_path: Path = Path("data/continuous-v1.sqlite3")
    raw_storage_path: Path = Path("data/continuous-v1-raw")
    log_path: Path = Path("logs/continuous")
    storage_warning_bytes: int = Field(default=10_000_000_000, gt=0)

    def polling(self, provider: str) -> PollPolicy:
        return self.polling_limits.get(
            provider,
            PollPolicy(
                minimum_poll_interval=self.minimum_poll_interval,
                maximum_poll_interval=self.maximum_poll_interval,
            ),
        )

    @property
    def stop_path(self) -> Path:
        return self.database_path.with_suffix(".stop")

    @model_validator(mode="after")
    def validate_policy(self) -> "Config":
        if (
            not self.airports
            or not set(self.airports) <= STATIONS.keys()
            or len(set(self.airports)) != len(self.airports)
        ):
            raise ValueError("Unique configured airports required")
        if (
            not self.providers
            or not set(self.providers) <= {"opensensemap", "sensor_community"}
            or len(set(self.providers)) != len(self.providers)
        ):
            raise ValueError("Only verified public providers enabled")
        if set(self.polling_limits) - set(self.providers):
            raise ValueError("Polling policy for disabled/unknown provider")
        if self.maximum_poll_interval < self.minimum_poll_interval:
            raise ValueError("Invalid polling bounds")
        if (
            not self.checkpoints
            or any(c not in {600, 300, 180, 120, 60, 30} for c in self.checkpoints)
            or len(set(self.checkpoints)) != len(self.checkpoints)
        ):
            raise ValueError("Unique supported checkpoints required")
        return self


def load(path: Path) -> Config:
    return Config.model_validate_json(path.read_text(encoding="utf-8"))
