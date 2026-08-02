import tempfile
from pathlib import Path

import pytest

from scrappad import cli


def test_no_file_uses_ephemeral_system_temp_file(monkeypatch) -> None:
    observed: dict[str, Path | bool] = {}

    class FakeApp:
        def __init__(self, path: Path) -> None:
            observed["path"] = path
            observed["exists_during_init"] = path.exists()

        def run(self) -> None:
            path = observed["path"]
            assert isinstance(path, Path)
            assert path.exists()

    monkeypatch.setattr(cli, "ScrappadApp", FakeApp)

    cli.main([])

    path = observed["path"]
    assert isinstance(path, Path)
    assert observed["exists_during_init"] is True
    assert path.name == "scratch.py"
    assert path.is_relative_to(Path(tempfile.gettempdir()))
    assert not path.exists()
    assert not path.parent.exists()


def test_explicit_file_is_not_temporary(monkeypatch, tmp_path) -> None:
    path = tmp_path / "kept.py"
    observed: list[Path] = []

    class FakeApp:
        def __init__(self, app_path: Path) -> None:
            observed.append(app_path)

        def run(self) -> None:
            return

    monkeypatch.setattr(cli, "ScrappadApp", FakeApp)

    cli.main([str(path)])

    assert observed == [path.resolve()]


def test_unsupported_platform_exits_before_starting_app(monkeypatch, capsys) -> None:
    class UnexpectedApp:
        def __init__(self, path: Path) -> None:
            pytest.fail(f"App unexpectedly started with {path}")

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "ScrappadApp", UnexpectedApp)

    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2
    assert "Scrappad only supports macOS and Linux" in capsys.readouterr().err
