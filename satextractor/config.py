"""Gestión de configuración desde archivo TOML."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


CONFIG_SEARCH_PATHS = [
    Path("config.toml"),
    Path.home() / ".config" / "satextractor" / "config.toml",
]


@dataclass
class FielConfig:
    cer_path: Path
    key_path: Path
    password: str | None = None


@dataclass
class SATConfig:
    rfc: str


@dataclass
class DatabaseConfig:
    path: Path


@dataclass
class ExportConfig:
    output_dir: Path


@dataclass
class Config:
    fiel: FielConfig
    sat: SATConfig
    database: DatabaseConfig
    export: ExportConfig

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Config":
        if config_path:
            path = config_path
        else:
            path = _find_config()

        with open(path, "rb") as f:
            data = tomllib.load(f)

        fiel = data.get("fiel", {})
        sat = data.get("sat", {})
        db = data.get("database", {})
        export = data.get("export", {})

        return cls(
            fiel=FielConfig(
                cer_path=Path(fiel["cer_path"]).expanduser(),
                key_path=Path(fiel["key_path"]).expanduser(),
                password=fiel.get("password"),
            ),
            sat=SATConfig(rfc=sat["rfc"]),
            database=DatabaseConfig(
                path=Path(db.get("path", "~/satextractor.db")).expanduser(),
            ),
            export=ExportConfig(
                output_dir=Path(export.get("output_dir", "~/reportes_sat")).expanduser(),
            ),
        )


def _find_config() -> Path:
    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No se encontró config.toml. Copia config.example.toml a config.toml "
        "y llena los datos de tu FIEL y RFC."
    )
