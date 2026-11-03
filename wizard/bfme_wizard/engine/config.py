"""The player's settings in <data dir>/config.env.

The file holds plain `KEY=value` lines, as the setup script wrote them. Its values win over the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PROTONPATH = "UMU-Proton-10.0-4"
GRAPHICS = ("vulkan", "opengl")
GPUS = ("auto", "dedicated", "integrated")  # which graphics card, on a computer with two


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    graphics: str = "vulkan"
    graphics_chosen: bool = False  # set by the player or an earlier setup; detection never overrides it
    protonpath: str = DEFAULT_PROTONPATH
    extra_env: dict[str, str] = field(default_factory=dict)
    keep_aotr_download: bool = False  # keep the Age of the Ring zip the app downloaded, after unpacking it
    gpu: str = "auto"


class ConfigFile:
    """config.env: plain `KEY=value` lines, as the setup script wrote them. Its values win over the environment."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _parse(line: str) -> tuple[str, str] | None:
        """(key, value) for a `KEY=value` or `export KEY=value` line, else None. Quotes around the value are removed."""
        line = line.strip()

        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        key, sep, value = line.partition("=")

        if not sep or not key.isidentifier():
            return None

        value = value.strip()

        # Remove surrounding quotes from the value, if any.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]

        return key, value

    def _lines(self) -> list[str]:
        try:
            return self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

    def read(self) -> dict[str, str]:
        """The file's keys and values."""
        values = {}

        for line in self._lines():
            pair = self._parse(line)

            if pair is not None:
                values[pair[0]] = pair[1]

        return values

    def load(self, environ: dict[str, str] | None = None) -> Config:
        """The settings: the file's, then any BFME_ variable of the environment it does not set."""
        env = os.environ if environ is None else environ
        values: dict[str, str] = {}

        for key, value in env.items():
            if key.startswith("BFME_"):
                values[key] = value

        # The file's values win over the environment.
        values.update(self.read())

        graphics = values.get("BFME_GRAPHICS", "")

        if graphics and graphics not in GRAPHICS:
            raise ConfigError(f'BFME_GRAPHICS must be vulkan or opengl, not "{graphics}".')

        gpu = values.get("BFME_GPU") or "auto"

        if gpu not in GPUS:
            raise ConfigError(f'BFME_GPU must be auto, dedicated or integrated, not "{gpu}".')

        extra: dict[str, str] = {}

        for word in values.get("BFME_EXTRA_ENV", "").split():
            name, sep, extra_value = word.partition("=")

            if sep:
                extra[name] = extra_value

        return Config(
            graphics=graphics or "vulkan",
            graphics_chosen=bool(graphics),
            protonpath=values.get("BFME_PROTONPATH") or DEFAULT_PROTONPATH,
            extra_env=extra,
            keep_aotr_download=values.get("BFME_KEEP_AOTR_DOWNLOAD", "") in ("1", "yes", "true"),
            gpu=gpu,
        )

    def save(self, key: str, value: str) -> None:
        """Set one key, keeping every other line."""
        kept: list[str] = []

        for line in self._lines():
            parsed = self._parse(line)

            # Drop the old line for this key; keep everything else.
            if parsed is not None and parsed[0] == key:
                continue

            kept.append(line)

        kept.append(f"{key}={value}")

        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.new.{os.getpid()}")

        content = ""

        for line in kept:
            content += f"{line}\n"

        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
