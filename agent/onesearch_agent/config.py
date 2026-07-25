"""Non-secret local agent configuration."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from onesearch_shared import AllowedRoot
from platformdirs import user_state_dir
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    server_url: str
    agent_name: str = Field(default_factory=socket.gethostname)
    allowed_roots: list[AllowedRoot] = Field(min_length=1)
    state_dir: Path = Field(default_factory=lambda: Path(user_state_dir("onesearch-agent")))
    credential_store: str = "auto"
    auto_update: bool = False

    @field_validator("server_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("server URL must not have surrounding whitespace")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "server URL must be an http(s) host without credentials, query, or fragment"
            )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

    @field_validator("credential_store")
    @classmethod
    def check_store(cls, value: str) -> str:
        if value not in {"auto", "keyring", "file"}:
            raise ValueError("credential_store must be auto, keyring, or file")
        return value

    @model_validator(mode="after")
    def check_roots(self) -> AgentConfig:
        ids = set()
        for root in self.allowed_roots:
            path = Path(root.path)
            if (
                root.root_id in ids
                or not path.is_absolute()
                or not path.is_dir()
                or not os.access(path, os.R_OK)
            ):
                raise ValueError(
                    "allowed roots must have unique IDs and be readable existing absolute directories"
                )
            ids.add(root.root_id)
        if self.state_dir.exists() and self.state_dir.is_symlink():
            raise ValueError("state directory must not be a symlink")
        return self


def config_path(value: str | None = None) -> Path:
    return Path(
        value
        or os.environ.get(
            "ONESEARCH_AGENT_CONFIG", Path(user_state_dir("onesearch-agent")) / "config.toml"
        )
    )


def load_config(path: Path | str | None = None) -> AgentConfig:
    target = config_path(str(path) if path else None)
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError("unable to load agent configuration") from error
    return AgentConfig.model_validate(data)
