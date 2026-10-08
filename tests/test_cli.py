from pathlib import Path

from passagekeep.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_import(tmp_path, capsys):
    db = tmp_path / "cli.db"
    rc = main(["--db", str(db), "import", str(FIXTURES / "sample_clippings.txt")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Added: 8" in out
    assert db.exists()


def test_cli_import_then_reimport_idempotent(tmp_path, capsys):
    db = tmp_path / "cli.db"
    main(["--db", str(db), "import", str(FIXTURES / "sample_clippings.txt")])
    capsys.readouterr()
    rc = main(["--db", str(db), "import", str(FIXTURES / "sample_clippings.txt")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Added: 0" in out


def test_cli_export(tmp_path, capsys):
    db = tmp_path / "cli.db"
    main(["--db", str(db), "import", str(FIXTURES / "sample_clippings.txt")])
    capsys.readouterr()
    out_file = tmp_path / "out.md"
    rc = main(
        [
            "--db",
            str(db),
            "export",
            "Pride and Prejudice",
            "--output",
            str(out_file),
        ]
    )
    assert rc == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "Pride and Prejudice" in content


def test_cli_export_unknown_book(tmp_path, capsys):
    db = tmp_path / "cli.db"
    main(["--db", str(db), "import", str(FIXTURES / "sample_clippings.txt")])
    capsys.readouterr()
    rc = main(["--db", str(db), "export", "Nonexistent Book"])
    assert rc == 1
