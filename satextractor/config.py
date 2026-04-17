"""Gestión de configuración desde archivo TOML."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_SEARCH_PATHS = [
    Path("config.toml"),
    Path.home() / ".config" / "satextractor" / "config.toml",
]


@dataclass
class FielConfig:
    cer_path: Path = field(default_factory=lambda: Path(""))
    key_path: Path = field(default_factory=lambda: Path(""))
    password: str | None = None


@dataclass
class SATConfig:
    rfc: str = ""


@dataclass
class DatabaseConfig:
    path: Path = field(default_factory=lambda: Path("~/satextractor.db").expanduser())


@dataclass
class ExportConfig:
    output_dir: Path = field(default_factory=lambda: Path("~/reportes_sat").expanduser())


@dataclass
class ContribuyenteConfig:
    regimen: str = "612"
    actividad: str = ""
    coeficiente_utilidad: float = 0.0  # Solo PM 601 (ejercicio anterior)
    actividad_plataforma: str = ""  # Solo 625: transporte/alimentos/hospedaje/venta_bienes/otros


@dataclass
class IAConfig:
    provider: str = "anthropic"  # anthropic, deepseek, openrouter
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    base_url: str = ""  # URL base para OpenRouter u otros proveedores OpenAI-compatible
    cache_dias: int = 90


@dataclass
class Config:
    fiel: FielConfig = field(default_factory=FielConfig)
    sat: SATConfig = field(default_factory=SATConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    contribuyente: ContribuyenteConfig = field(default_factory=ContribuyenteConfig)
    ia: IAConfig = field(default_factory=IAConfig)
    _config_path: Path | None = field(default=None, repr=False)

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
                cer_path=Path(fiel["cer_path"]).expanduser() if "cer_path" in fiel else Path(""),
                key_path=Path(fiel["key_path"]).expanduser() if "key_path" in fiel else Path(""),
                password=fiel.get("password"),
            ),
            sat=SATConfig(rfc=sat.get("rfc", "")),
            database=DatabaseConfig(
                path=Path(db.get("path", "~/satextractor.db")).expanduser(),
            ),
            export=ExportConfig(
                output_dir=Path(export.get("output_dir", "~/reportes_sat")).expanduser(),
            ),
            contribuyente=ContribuyenteConfig(
                regimen=contrib.get("regimen", "612"),
                actividad=contrib.get("actividad", ""),
                coeficiente_utilidad=float(contrib.get("coeficiente_utilidad", 0.0)),
                actividad_plataforma=contrib.get("actividad_plataforma", ""),
            ),
            ia=IAConfig(
                provider=ia.get("provider", "anthropic"),
                api_key=ia.get("api_key", ""),
                model=ia.get("model", "claude-sonnet-4-6"),
                base_url=ia.get("base_url", ""),
                cache_dias=ia.get("cache_dias", 90),
            ),
            _config_path=path,
        )

    @classmethod
    def create_default(cls) -> "Config":
        """Crea una Config con valores por defecto (sin FIEL ni RFC)."""
        return cls()

    def save(self, path: Path | None = None) -> Path:
        """Escribe la configuración actual a un archivo TOML."""
        save_path = path or self._config_path or Path("config.toml")

        lines = []

        # [fiel]
        lines.append("[fiel]")
        lines.append(f'cer_path = "{self.fiel.cer_path}"')
        lines.append(f'key_path = "{self.fiel.key_path}"')
        if self.fiel.password:
            lines.append(f'password = "{self.fiel.password}"')
        lines.append("")

        # [sat]
        lines.append("[sat]")
        lines.append(f'rfc = "{self.sat.rfc}"')
        lines.append("")

        # [database]
        lines.append("[database]")
        lines.append(f'path = "{self.database.path}"')
        lines.append("")

        # [export]
        lines.append("[export]")
        lines.append(f'output_dir = "{self.export.output_dir}"')
        lines.append("")

        # [contribuyente]
        lines.append("[contribuyente]")
        lines.append(f'regimen = "{self.contribuyente.regimen}"')
        if self.contribuyente.actividad:
            lines.append(f'actividad = "{self.contribuyente.actividad}"')
        if self.contribuyente.coeficiente_utilidad > 0:
            lines.append(f"coeficiente_utilidad = {self.contribuyente.coeficiente_utilidad}")
        if self.contribuyente.actividad_plataforma:
            lines.append(f'actividad_plataforma = "{self.contribuyente.actividad_plataforma}"')
        lines.append("")

        # [ia]
        if self.ia.api_key:
            lines.append("[ia]")
            lines.append(f'provider = "{self.ia.provider}"')
            lines.append(f'api_key = "{self.ia.api_key}"')
            lines.append(f'model = "{self.ia.model}"')
            if self.ia.base_url:
                lines.append(f'base_url = "{self.ia.base_url}"')
            lines.append(f"cache_dias = {self.ia.cache_dias}")
            lines.append("")

        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text("\n".join(lines), encoding="utf-8")
        self._config_path = save_path
        return save_path


def _find_config() -> Path:
    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No se encontró config.toml. Copia config.example.toml a config.toml "
        "y llena los datos de tu FIEL y RFC."
    )
