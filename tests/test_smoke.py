from editorial_agent import __version__
from editorial_agent.cli import main


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_starts(capsys) -> None:
    main()

    captured = capsys.readouterr()

    assert captured.out == "Editorial Agent alpha\n"