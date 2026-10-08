from app.cli import main


def test_classify_without_key_is_actionable(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = main(["classify", "--subject", "VPN", "--description", "Cannot connect."])
    assert status == 1
    output = capsys.readouterr()
    assert "OPENAI_API_KEY" in output.err
    assert output.out == ""


def test_inspect_does_not_overwrite_source(tmp_path, capsys):
    path = tmp_path / "tickets.csv"
    path.write_text("original contents", encoding="utf-8")
    assert main(["inspect", "--data", str(path), "--output", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == "original contents"
    assert "must differ" in capsys.readouterr().err
