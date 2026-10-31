import pytest

from src.config.config import ConfigManager, GetUnknownKey


@pytest.fixture(autouse=True)
def clean_config_state():
    """隔离类级全局配置字典，测试后还原"""
    saved = dict(ConfigManager.config_dict)
    ConfigManager.config_dict.clear()
    yield
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict.update(saved)


def test_get_returns_none_valued_key():
    ConfigManager.config_dict["demo"] = {"maybe": None, "v": 3}
    assert ConfigManager.get("demo", "maybe") is None
    assert ConfigManager.get("demo", "v") == 3


def test_get_unknown_dict_message_names_the_dict():
    ConfigManager.config_dict["a"] = {"k": 1}
    ConfigManager.config_dict["zzz"] = {"k": 2}
    with pytest.raises(GetUnknownKey) as e:
        ConfigManager.get("missing", "k")
    # 报错必须是请求的字典名，而不是遍历到的最后一个
    assert "missing" in str(e.value)


def test_get_unknown_key_message_names_the_key():
    ConfigManager.config_dict["a"] = {"k1": 1, "k2": 2}
    with pytest.raises(GetUnknownKey) as e:
        ConfigManager.get("a", "nope")
    assert "nope" in str(e.value)
    assert "a" in str(e.value)


def test_base_path_placeholder_replaced():
    ConfigManager.config_dict["demo"] = {"p": "./${BASE_PATH}/datas"}
    assert ConfigManager.get("demo", "p") == f"./{ConfigManager.base_path}/datas"


def test_env_override_memory_only(monkeypatch, tmp_path):
    # base_path 指到空目录，验证环境变量覆盖不会写任何文件
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    ConfigManager.config_dict["update_setting"] = {"do_update": False}
    monkeypatch.setenv("UPDATE_SETTING_DO_UPDATE", "true")

    ConfigManager._apply_env_overrides()

    assert ConfigManager.get("update_setting", "do_update") is True
    assert list(tmp_path.iterdir()) == []  # 配置文件没有被持久化改写


def test_reload_reapplies_env_override(monkeypatch, tmp_path):
    confs = tmp_path / "confs"
    confs.mkdir()
    (confs / "update_setting.yaml").write_text("do_update: false\n", encoding="utf-8")
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    monkeypatch.setenv("UPDATE_SETTING_DO_UPDATE", "true")

    ConfigManager.load_all_configs()

    # 热重载后环境变量覆盖依然生效
    assert ConfigManager.get("update_setting", "do_update") is True


def test_load_builds_copy_then_swaps(monkeypatch, tmp_path):
    """副本换入语义：单个文件损坏只丢该段；目录整体缺失时旧配置原样保留"""
    confs = tmp_path / "confs"
    confs.mkdir()
    (confs / "a.yaml").write_text("k: v1\n", encoding="utf-8")
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))

    ConfigManager.load_all_configs()
    assert ConfigManager.get("a", "k") == "v1"

    # a 损坏：该段不再出现，但不影响其他段的加载
    (confs / "a.yaml").write_text("k: [unclosed\n", encoding="utf-8")
    (confs / "b.yaml").write_text("x: 1\n", encoding="utf-8")
    ConfigManager.load_all_configs()
    assert ConfigManager.get("b", "x") == 1
    with pytest.raises(GetUnknownKey):
        ConfigManager.get("a", "k")

    # 目录整体缺失：抛异常且当前内存配置原样保留（不再有清空后的空窗）
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path / "nowhere"))
    with pytest.raises(FileNotFoundError):
        ConfigManager.load_all_configs()
    assert ConfigManager.get("b", "x") == 1


def test_replace_section_validates_swaps_and_saves(monkeypatch, tmp_path):
    confs = tmp_path / "confs"
    confs.mkdir()
    (confs / "demo.yaml").write_text("k: old\n", encoding="utf-8")
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    ConfigManager.load_all_configs()

    ConfigManager.replace_section("demo", {"k": "new", "extra": [1, 2]})
    assert ConfigManager.get("demo", "k") == "new"
    assert ConfigManager.get("demo", "extra") == [1, 2]
    assert "k: new" in (confs / "demo.yaml").read_text(encoding="utf-8")

    with pytest.raises(KeyError):
        ConfigManager.replace_section("ghost", {"k": 1})
    with pytest.raises(ValueError):
        ConfigManager.replace_section("demo", [1, 2, 3])
