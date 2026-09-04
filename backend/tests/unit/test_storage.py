from pathlib import Path

from app.core.storage import Storage


def test_json_roundtrip(tmp_path: Path) -> None:
    store = Storage(tmp_path)
    store.write_json({"ok": True, "n": 1}, "runs", "a.json")
    assert store.read_json("runs", "a.json") == {"ok": True, "n": 1}
    assert store.exists("runs", "a.json")
    names = [p.name for p in store.list("runs")]
    assert names == ["a.json"]
    store.delete("runs", "a.json")
    assert not store.exists("runs", "a.json")


def test_yaml_roundtrip(tmp_path: Path) -> None:
    store = Storage(tmp_path)
    store.write_yaml({"name": "matcher", "version": "1"}, "agents", "v.yaml")
    assert store.read_yaml("agents", "v.yaml")["name"] == "matcher"


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    store = Storage(tmp_path)
    target = store.write_json({"v": 2}, "pipelines", "p.json")
    leftover_json = list(target.parent.glob("*.tmp"))
    assert leftover_json == []
    assert target.read_text(encoding="utf-8")


def test_write_bytes(tmp_path: Path) -> None:
    store = Storage(tmp_path)
    path = store.write_bytes(b"xlsx-bytes", "runs", "r1", "artifacts", "a.xlsx")
    assert path.read_bytes() == b"xlsx-bytes"
    assert store.exists("runs", "r1", "artifacts", "a.xlsx")
    assert list(path.parent.glob("*.tmp")) == []
