def test_quickstart_step_index_indexes_even_if_collection_exists_when_paths_explicit(
    tmp_path, monkeypatch
):
    from scripts.ctx_cli.commands import quickstart as quickstart_cmd

    dev_workspace = tmp_path / "dev-workspace"
    repo1 = dev_workspace / "repo1"
    repo1.mkdir(parents=True, exist_ok=True)
    (repo1 / "a.py").write_text("print('hi')\n", encoding="utf-8")

    monkeypatch.setenv("HOST_INDEX_PATH", str(dev_workspace))
    monkeypatch.setenv("COLLECTION_NAME", "c1")

    class DummyClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def call_tool(self, name, **kwargs):
            DummyClient.calls.append((name, kwargs))
            if name == "qdrant_status":
                return {"count": 123}
            if name == "qdrant_list":
                return {"collections": ["c1"]}
            if name in {"qdrant_index", "qdrant_index_root"}:
                return {"ok": True, "total_files": 0, "changed": 0, "deleted": 0, "skipped": 0}
            return {"ok": True}

    monkeypatch.setattr(quickstart_cmd, "MCPClient", DummyClient)

    rc = quickstart_cmd.step_index(
        skip_index=False,
        recreate=False,
        paths=[str(repo1)],
        import_repos=False,
    )
    assert rc == 0
    assert any(name == "qdrant_index" for name, _kwargs in DummyClient.calls)


def test_quickstart_step_index_recreate_applied_to_each_path_in_multi_repo_mode(
    tmp_path, monkeypatch
):
    from scripts.ctx_cli.commands import quickstart as quickstart_cmd

    dev_workspace = tmp_path / "dev-workspace"
    repo1 = dev_workspace / "repo1"
    repo2 = dev_workspace / "repo2"
    repo1.mkdir(parents=True, exist_ok=True)
    repo2.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOST_INDEX_PATH", str(dev_workspace))
    monkeypatch.setenv("MULTI_REPO_MODE", "1")

    class DummyClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def call_tool(self, name, **kwargs):
            DummyClient.calls.append((name, kwargs))
            if name == "qdrant_status":
                return {"count": 0}
            if name == "qdrant_list":
                return {"collections": []}
            if name in {"qdrant_index", "qdrant_index_root"}:
                return {"ok": True, "total_files": 0, "changed": 0, "deleted": 0, "skipped": 0}
            return {"ok": True}

    monkeypatch.setattr(quickstart_cmd, "MCPClient", DummyClient)

    rc = quickstart_cmd.step_index(
        skip_index=False,
        recreate=True,
        paths=[str(repo1), str(repo2)],
        import_repos=False,
    )
    assert rc == 0

    index_calls = [(n, kw) for n, kw in DummyClient.calls if n == "qdrant_index"]
    assert len(index_calls) == 2
    assert all(bool(kw.get("recreate")) for _n, kw in index_calls)


def test_quickstart_step_index_recreate_only_first_in_single_repo_mode(tmp_path, monkeypatch):
    from scripts.ctx_cli.commands import quickstart as quickstart_cmd

    dev_workspace = tmp_path / "dev-workspace"
    repo1 = dev_workspace / "repo1"
    repo2 = dev_workspace / "repo2"
    repo1.mkdir(parents=True, exist_ok=True)
    repo2.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOST_INDEX_PATH", str(dev_workspace))
    monkeypatch.setenv("MULTI_REPO_MODE", "0")

    class DummyClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def call_tool(self, name, **kwargs):
            DummyClient.calls.append((name, kwargs))
            if name == "qdrant_status":
                return {"count": 0}
            if name == "qdrant_list":
                return {"collections": []}
            if name in {"qdrant_index", "qdrant_index_root"}:
                return {"ok": True, "total_files": 0, "changed": 0, "deleted": 0, "skipped": 0}
            return {"ok": True}

    monkeypatch.setattr(quickstart_cmd, "MCPClient", DummyClient)

    rc = quickstart_cmd.step_index(
        skip_index=False,
        recreate=True,
        paths=[str(repo1), str(repo2)],
        import_repos=False,
    )
    assert rc == 0

    index_calls = [kw for n, kw in DummyClient.calls if n == "qdrant_index"]
    assert len(index_calls) == 2
    assert index_calls[0].get("recreate") is True
    assert index_calls[1].get("recreate") is False


def test_quickstart_import_repos_copies_external_path(tmp_path, monkeypatch):
    from scripts.ctx_cli.commands import quickstart as quickstart_cmd

    dev_workspace = tmp_path / "dev-workspace"
    source = tmp_path / "source_repo"
    (source / "pkg").mkdir(parents=True, exist_ok=True)
    (source / "pkg" / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setenv("HOST_INDEX_PATH", str(dev_workspace))

    class DummyClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        def call_tool(self, name, **kwargs):
            DummyClient.calls.append((name, kwargs))
            if name == "qdrant_status":
                return {"count": 0}
            if name == "qdrant_list":
                return {"collections": []}
            if name in {"qdrant_index", "qdrant_index_root"}:
                return {"ok": True, "total_files": 0, "changed": 0, "deleted": 0, "skipped": 0}
            return {"ok": True}

    monkeypatch.setattr(quickstart_cmd, "MCPClient", DummyClient)

    rc = quickstart_cmd.step_index(
        skip_index=False,
        recreate=False,
        paths=[str(source)],
        import_repos=True,
    )
    assert rc == 0

    imported = dev_workspace / source.name
    assert imported.exists()
    assert imported.is_dir()
    assert not imported.is_symlink()

    # Ensure we indexed the imported path as a subdir under /work
    index_calls = [(n, kw) for n, kw in DummyClient.calls if n == "qdrant_index"]
    assert len(index_calls) == 1
    assert index_calls[0][1]["subdir"] == source.name
