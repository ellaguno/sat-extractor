"""Entry point: python -m satextractor"""

import sys
from pathlib import Path

from rich.console import Console

from .config import Config

console = Console()


def main():
    config = None
    config_path = None
    use_classic = False

    # Parsear argumentos
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--config" and i + 1 < len(args):
            config_path = Path(args[i + 1])
        elif arg.startswith("--config="):
            config_path = Path(arg.split("=", 1)[1])
        elif arg == "--classic":
            use_classic = True

    try:
        config = Config.load(config_path)
    except FileNotFoundError:
        console.print(
            "[yellow]No se encontró config.toml. "
            "La descarga del SAT no estará disponible.[/yellow]"
            "\n[dim]Copia config.example.toml a config.toml y "
            "configura tu FIEL y RFC.[/dim]\n"
        )
    except Exception as e:
        console.print(f"[yellow]Error cargando config: {e}[/yellow]\n")

    db_path = Path("~/satextractor.db").expanduser()
    if config:
        db_path = config.database.path

    if use_classic:
        from .ui.app import App
        app = App(db_path=db_path, config=config)
        app.run()
    else:
        from .ui.tui import run_tui
        run_tui(db_path=db_path, config=config)


if __name__ == "__main__":
    main()
