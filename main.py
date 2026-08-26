"""
TopologyBuilder: #TODO beschreibung einfügen
"""

from dotenv import load_dotenv

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


def main():
    load_dotenv()
    from src.cli import app, typer, Settings, Verbosity

    try:
        app()
    except Exception as e:
        if Settings.VERBOSITY_LEVEL.level == Verbosity.DEBUG.level:
            raise e
        typer.secho(f"{e.__str__()}", fg=typer.colors.RED)


if __name__ == "__main__":
    main()
