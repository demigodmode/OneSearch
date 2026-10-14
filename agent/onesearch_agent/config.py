"""Non-secret local agent configuration."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from onesearch_shared import AllowedRoot
from platformdirs import user_state_dir
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


class ConfigError(ValueError):
    """The config file can't be used. The message is meant for the person running the agent."""


def _root_problem(path: Path) -> str | None:
    if not path.is_absolute():
        return "path must be absolute"
    # stat() rather than exists(): from 3.14 exists() returns False for a
    # parent we can't enter, which would blame a missing mount
    try:
        info = path.stat()
    except FileNotFoundError:
        return "path does not exist (running in Docker? check that it is mounted)"
    except OSError as error:
        return f"path can't be checked: {error.strerror or error}"
    if not stat.S_ISDIR(info.st_mode):
        return "path is not a directory"
    if not os.access(path, os.R_OK | os.X_OK):
        return "path is not readable by this user"
    return None


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
        # check every root so one run of `config check` shows all of the problems
        problems = []
        ids = set()
        for root in self.allowed_roots:
            if root.root_id in ids:
                problems.append(f"root '{root.root_id}' ({root.path}): root_id is used more than once")
            ids.add(root.root_id)
            problem = _root_problem(Path(root.path))
            if problem:
                problems.append(f"root '{root.root_id}' ({root.path}): {problem}")
        if problems:
            raise ValueError("\n".join(problems))
        if self.state_dir.exists() and self.state_dir.is_symlink():
            raise ValueError("state directory must not be a symlink")
        if not self.state_dir.is_absolute():
            raise ValueError("state directory must be absolute")
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
    except OSError as error:
        raise ConfigError(f"unable to read agent configuration {target}: {error.strerror}") from error
    except tomllib.TOMLDecodeError as error:
        hint = ""
        if "overwrite" in str(error).lower():
            hint = " (each allowed root needs its own [[allowed_roots]] line above it)"
        raise ConfigError(f"agent configuration {target} is not valid TOML: {error}{hint}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(
            f"agent configuration {target} is not valid UTF-8 (byte {error.start})"
        ) from error
    try:
        return AgentConfig.model_validate(data)
    except ValidationError as error:
        raise ConfigError(f"agent configuration {target} has problems:\n{_describe(error)}") from error


def _describe(error: ValidationError) -> str:
    # Only the location and message. Pydantic's own text includes the input
    # values, which would print the whole config back.
    lines = []
    for item in error.errors():
        message = item["msg"].removeprefix("Value error, ")
        location = ".".join(str(part) for part in item["loc"])
        for line in message.splitlines():
            lines.append(f"  {location}: {line}" if location else f"  {line}")
    return "\n".join(lines)
