import os
from jd2candidates import env


def test_load_reads_dotenv_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("# c\nA_KEY=abc\nB_KEY=keep\n\n")
    monkeypatch.setenv("B_KEY", "orig")
    monkeypatch.delenv("A_KEY", raising=False)
    env.load()
    assert os.environ["A_KEY"] == "abc"
    assert os.environ["B_KEY"] == "orig"
