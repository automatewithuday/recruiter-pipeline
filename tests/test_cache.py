from jd2candidates.cache import RunDir


def test_rundir_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = RunDir("slug-a")
    assert r.read("spec") is None
    r.write("spec", {"k": [1, 2]})
    assert r.read("spec") == {"k": [1, 2]}
    assert (tmp_path / "runs" / "slug-a" / "spec.json").exists()
