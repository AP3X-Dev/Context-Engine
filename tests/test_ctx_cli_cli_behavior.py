import configparser


def test_config_manager_default_collection_from_ctxrc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    (tmp_path / ".ctxrc").write_text(
        "[search]\n"
        "default_collection = my-collection\n",
        encoding="utf-8",
    )

    from scripts.ctx_cli.utils.config import ConfigManager

    cfg = ConfigManager()
    assert cfg.get_default_collection() == "my-collection"


def test_config_manager_default_collection_env_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CTX_SEARCH_DEFAULT_COLLECTION", "env-collection")

    from scripts.ctx_cli.utils.config import ConfigManager

    cfg = ConfigManager()
    assert cfg.get_default_collection() == "env-collection"


def test_search_uses_default_collection_from_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("COLLECTION_NAME", raising=False)
    monkeypatch.delenv("CTX_SEARCH_DEFAULT_COLLECTION", raising=False)

    (tmp_path / ".ctxrc").write_text(
        "[search]\n"
        "default_collection = cfg-collection\n",
        encoding="utf-8",
    )

    from scripts.ctx_cli.commands import search as search_cmd

    class DummyClient:
        last_call = None

        def __init__(self, *args, **kwargs):
            from scripts.ctx_cli.utils.config import ConfigManager

            self.config = ConfigManager()

        def call_tool(self, name, **kwargs):
            DummyClient.last_call = (name, kwargs)
            return {"ok": True, "results": [], "total": 0}

    monkeypatch.setattr(search_cmd, "MCPClient", DummyClient)

    search_cmd.call_mcp_search("hello", limit=1)
    tool, kwargs = DummyClient.last_call
    assert tool == "repo_search"
    assert kwargs["collection"] == "cfg-collection"


def test_answer_uses_default_collection_from_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("COLLECTION_NAME", raising=False)
    monkeypatch.delenv("CTX_SEARCH_DEFAULT_COLLECTION", raising=False)

    (tmp_path / ".ctxrc").write_text(
        "[search]\n"
        "default_collection = cfg-collection\n",
        encoding="utf-8",
    )

    from scripts.ctx_cli.commands import answer as answer_cmd

    class DummyClient:
        last_call = None

        def __init__(self, *args, **kwargs):
            from scripts.ctx_cli.utils.config import ConfigManager

            self.config = ConfigManager()

        def call_tool(self, name, **kwargs):
            DummyClient.last_call = (name, kwargs)
            return {"ok": True, "answer": "ok", "citations": []}

    monkeypatch.setattr(answer_cmd, "MCPClient", DummyClient)

    answer_cmd.call_mcp_context_answer("hello", budget_tokens=10)
    tool, kwargs = DummyClient.last_call
    assert tool == "context_answer"
    assert kwargs["collection"] == "cfg-collection"


def test_collections_switch_persists_default_collection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    from scripts.ctx_cli.commands import collections as collections_cmd

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def call_tool(self, name, **kwargs):
            if name == "qdrant_list":
                return {"collections": ["c1"]}
            raise AssertionError(f"Unexpected tool call: {name}")

    monkeypatch.setattr(collections_cmd, "MCPClient", DummyClient)

    class Args:
        name = "c1"

    assert collections_cmd.switch_collection(Args()) == 0

    cfg_path = tmp_path / ".ctxrc"
    assert cfg_path.exists()

    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    assert parser.get("search", "default_collection") == "c1"


def test_index_tool_resolution_maps_subdir_via_host_index_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HOST_INDEX_PATH", str(tmp_path))

    from scripts.ctx_cli.commands import index as index_cmd

    subdir = tmp_path / "repo"
    subdir.mkdir(parents=True, exist_ok=True)

    tool, params, _display = index_cmd._index_tool_for_path(
        target_path=subdir,
        recreate=False,
        explicit_path=True,
    )
    assert tool == "qdrant_index"
    assert params["subdir"] == "repo"


def test_index_tool_resolution_rejects_paths_outside_host_index_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    host_root = tmp_path / "mounted"
    host_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOST_INDEX_PATH", str(host_root))

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)

    from scripts.ctx_cli.commands import index as index_cmd

    try:
        index_cmd._index_tool_for_path(
            target_path=outside,
            recreate=False,
            explicit_path=True,
        )
    except ValueError as e:
        assert "outside the mounted workspace" in str(e).lower()
    else:
        raise AssertionError("Expected ValueError for path outside HOST_INDEX_PATH")
