import pytest

from editorial_agent import __version__
from editorial_agent.cli import main


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_starts(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0

    captured = capsys.readouterr()

    assert "usage: editorial-agent" in captured.out
    assert "run" in captured.out