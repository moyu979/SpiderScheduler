"""ScriptDispatcher 测试：website 路由、兜底、失败重载保路由与依赖声明解析。
"""
import pytest

from src.service.dispatcher import (
    ScriptDispatcher,
    ScriptRouteError,
    _satisfied,
    ensure_requirements,
    parse_requirements,
)


def _write(tmp_path, content, name="script.py"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_routes_by_website_attribute(tmp_path):
    """测试按 website 属性路由脚本类，支持单站点与站点列表。"""
    path = _write(tmp_path, '''
class PixivWork:
    website = "pixiv"

class DanbooruWork:
    website = ["danbooru", "gelbooru"]
''')
    d = ScriptDispatcher(path, fallback_class_name="DownloadWork")
    assert d.get("pixiv").__name__ == "PixivWork"
    assert d.get("danbooru").__name__ == "DanbooruWork"
    assert d.get("gelbooru").__name__ == "DanbooruWork"
    assert d.websites() == ["danbooru", "gelbooru", "pixiv"]


def test_fallback_without_website(tmp_path):
    """测试无 website 声明的兜底类对任何站点都生效。"""
    path = _write(tmp_path, '''
class DownloadWork:
    pass
''')
    d = ScriptDispatcher(path, fallback_class_name="DownloadWork")
    assert d.get("pixiv").__name__ == "DownloadWork"
    assert d.get("anything").__name__ == "DownloadWork"


def test_unknown_website_error_lists_available(tmp_path):
    """测试未知站点报 ScriptRouteError 且错误信息列出可用站点。"""
    path = _write(tmp_path, '''
class A:
    website = "pixiv"
''')
    d = ScriptDispatcher(path, fallback_class_name="DownloadWork")
    with pytest.raises(ScriptRouteError) as e:
        d.get("danbooru")
    assert "danbooru" in str(e.value)
    assert "pixiv" in str(e.value)


def test_missing_fallback_class_raises(tmp_path):
    """测试脚本中兜底类缺失时初始化抛 AttributeError。"""
    path = _write(tmp_path, "X = 1")
    with pytest.raises(AttributeError):
        ScriptDispatcher(path, fallback_class_name="DownloadWork")


def test_failed_reload_preserves_old_routes(tmp_path):
    """测试重载失败（语法错误或缺兜底类）时旧路由原样保留。"""
    path = _write(tmp_path, '''
class PixivWork:
    website = "pixiv"
''')
    d = ScriptDispatcher(path, fallback_class_name="DownloadWork")
    assert d.get("pixiv").__name__ == "PixivWork"
    assert d.snapshot() == {"websites": {"pixiv": "PixivWork"}, "fallback": None}

    # 脚本改成语法错误 → 重载失败抛异常，旧路由原样保留
    path2 = _write(tmp_path, "this is not python !!!!", name="script.py")
    assert path2 == path
    with pytest.raises(Exception):
        d.load()
    assert d.get("pixiv").__name__ == "PixivWork"

    # 脚本改成合法但无 website 声明且缺兜底类 → 同样保留旧路由
    from pathlib import Path
    Path(path).write_text("X = 1", encoding="utf-8")
    with pytest.raises(AttributeError):
        d.load()
    assert d.get("pixiv").__name__ == "PixivWork"
    assert d.snapshot()["fallback"] is None


def test_reload_switches_routes_on_success(tmp_path):
    """测试重载成功后路由表切换到新脚本内容。"""
    path = _write(tmp_path, '''
class DownloadWork:
    pass
''')
    d = ScriptDispatcher(path, fallback_class_name="DownloadWork")
    assert d.snapshot() == {"websites": {}, "fallback": "DownloadWork"}

    from pathlib import Path
    Path(path).write_text('''
class DanbooruWork:
    website = "danbooru"
''', encoding="utf-8")
    d.load()
    assert d.snapshot() == {"websites": {"danbooru": "DanbooruWork"}, "fallback": None}


# ---------- 脚本依赖自动安装 ----------

def test_parse_requirements_extracts_header_lines():
    """测试提取脚本头部 requirements 声明，忽略 docstring 内的伪声明。"""
    text = (
        "# requirements: requests>=2.31, beautifulsoup4\n"
        "# requirements: lxml\n"
        "import requests\n"
        "'\n# 这行在 docstring 里，不应被提取：# requirements: fake-package\n'\n"
    )
    assert parse_requirements(text) == ["requests>=2.31", "beautifulsoup4", "lxml"]
    assert parse_requirements("no declarations here") == []


def test_satisfied_checks_installed_and_version():
    """测试依赖满足判断：已安装、版本约束满足与不满足、未安装。"""
    assert _satisfied("flask") is True            # 环境里已安装
    assert _satisfied("flask>=2.0") is True
    assert _satisfied("flask<1.0") is False       # 版本约束不满足
    assert _satisfied("definitely-not-installed-pkg-xyz") is False


def test_ensure_requirements_skips_pip_when_satisfied(tmp_path, monkeypatch):
    """测试依赖全部满足时不触发 pip 安装。"""
    script = tmp_path / "s.py"
    script.write_text("# requirements: flask\nclass DownloadWork:\n    pass\n", encoding="utf-8")

    def boom(*a, **kw):
        raise AssertionError("全部已满足时不应触发 pip")
    monkeypatch.setattr("src.service.dispatcher.subprocess.run", boom)

    ensure_requirements(str(script))  # 不应抛出


def test_ensure_requirements_installs_missing(tmp_path, monkeypatch):
    """测试只有缺失依赖进入 pip install，已满足的不重复安装。"""
    calls = []
    monkeypatch.setattr(
        "src.service.dispatcher.subprocess.run",
        lambda cmd, **kw: calls.append(cmd) or type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})(),
    )
    script = tmp_path / "s.py"
    script.write_text("# requirements: some-missing-pkg-xyz, flask\nX = 1\n", encoding="utf-8")

    ensure_requirements(str(script))

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1:4] == ["-m", "pip", "install"]
    assert "some-missing-pkg-xyz" in cmd and "flask" not in cmd  # 已满足的不进 pip


def test_dispatcher_load_ensures_requirements(tmp_path, monkeypatch):
    """测试分发器加载脚本前先执行依赖确保流程。"""
    called = []
    monkeypatch.setattr("src.service.dispatcher.ensure_requirements", lambda path: called.append(path))
    path = tmp_path / "script.py"
    path.write_text("class DownloadWork:\n    pass\n", encoding="utf-8")

    ScriptDispatcher(str(path), fallback_class_name="DownloadWork")

    assert called == [str(path)]
