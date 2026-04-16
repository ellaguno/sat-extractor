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
class ContribuyenteConfig:
    regimen: str = "612"
    actividad: str = ""


@dataclass
class IAConfig:
    provider: str = "anthropic"
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    cache_dias: int = 90


@dataclass
class Config:
    fiel: FielConfig
    sat: SATConfig
    database: DatabaseConfig
    export: ExportConfig
    contribuyente: ContribuyenteConfig = None  # type: ignore[assignment]
    ia: IAConfig = None  # type: ignore[assignment]

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
        contrib = data.get("contribuyente", {})
        ia = data.get("ia", {})

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
            contribuyente=ContribuyenteConfig(
                regimen=contrib.get("regimen", "612"),
                actividad=contrib.get("actividad", ""),
            ),
            ia=IAConfig(
                provider=ia.get("provider", "anthropic"),
                api_key=ia.get("api_key", ""),
                model=ia.get("model", "claude-sonnet-4-6"),
                cache_dias=ia.get("cache_dias", 90),
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
