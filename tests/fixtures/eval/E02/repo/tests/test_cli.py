from inventory.cli import main


def test_summary_prints_total(capsys):
    assert main(["summary"]) == 0
    assert "total=1300" in capsys.readouterr().out


def test_list_still_works(capsys):
    assert main(["list"]) == 0
    assert "pen" in capsys.readouterr().out
