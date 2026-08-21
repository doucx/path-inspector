import json
from pathlib import Path
from typer.testing import CliRunner
from path_inspector.config import find_config_file, load_preset, get_all_presets
from path_inspector.cli import app

runner = CliRunner()


def test_find_and_load_preset(tmp_path, monkeypatch):
    """测试配置文件的发现与指定 preset 读取"""
    config_content = {
        "presets": {
            "default": {"extension": ["py", "md"]},
            "web": {"extension": ["js", "ts", "html"], "format": "json"},
        }
    }
    cfg_file = tmp_path / "piconfig.json"
    cfg_file.write_text(json.dumps(config_content), encoding="utf-8")

    # 显式路径查找
    found = find_config_file(cfg_file)
    assert found == cfg_file.resolve()

    # 读取 default 预设
    preset_default = load_preset(cfg_file)
    assert preset_default["extension"] == ["py", "md"]

    # 读取 web 预设
    preset_web = load_preset(cfg_file, "web")
    assert preset_web["extension"] == ["js", "ts", "html"]
    assert preset_web["format"] == "json"

    # 读取不存在的预设
    preset_non_exist = load_preset(cfg_file, "non_existent")
    assert preset_non_exist == {}


def test_cli_preset_default_and_override(tmp_path, monkeypatch):
    """测试 CLI 中默认加载 default 预设，且支持显式参数覆盖"""
    # 构建测试工作区
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "a.py").write_text("print('hello')", encoding="utf-8")
    (workspace / "b.txt").write_text("plain text", encoding="utf-8")
    (workspace / "c.md").write_text("# Markdown Title", encoding="utf-8")

    config_content = {
        "presets": {
            "default": {"extension": ["py"], "format": "json"},
            "docs": {"extension": ["md"], "format": "json"},
        }
    }
    (workspace / "piconfig.json").write_text(
        json.dumps(config_content), encoding="utf-8"
    )

    monkeypatch.chdir(workspace)

    # 1. 不带任何参数运行，应自动应用 default 预设 (json 格式, 读取 .py 内容)
    result = runner.invoke(app, ["."])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    results = data["results"][0]["children"]
    a_py = next(c for c in results if c["name"] == "a.py")
    b_txt = next(c for c in results if c["name"] == "b.txt")
    assert a_py.get("content") == "print('hello')"
    assert "content" not in b_txt

    # 2. 使用 -x docs 切换预设
    result_docs = runner.invoke(app, [".", "-x", "docs"])
    assert result_docs.exit_code == 0
    data_docs = json.loads(result_docs.stdout)
    results_docs = data_docs["results"][0]["children"]
    c_md = next(c for c in results_docs if c["name"] == "c.md")
    assert c_md.get("content") == "# Markdown Title"

    # 3. 命令行显式参数覆盖预设：使用 -x docs 但覆盖 format 为 compact
    result_override = runner.invoke(app, [".", "-x", "docs", "-f", "compact"])
    assert result_override.exit_code == 0
    data_compact = json.loads(result_override.stdout)
    assert "meta" in data_compact
    assert "data" in data_compact


def test_cli_list_presets(tmp_path, monkeypatch):
    """测试 --list-presets 选项"""
    workspace = tmp_path / "project"
    workspace.mkdir()
    config_content = {
        "presets": {
            "default": {"extension": ["py"]},
            "frontend": {"extension": ["ts", "tsx"]},
        }
    }
    (workspace / "piconfig.json").write_text(
        json.dumps(config_content), encoding="utf-8"
    )
    monkeypatch.chdir(workspace)

    result = runner.invoke(app, ["--list-presets"])
    assert result.exit_code == 0
    assert "可用预设:" in result.stdout
    assert "default [extensions: py]" in result.stdout
    assert "frontend [extensions: ts, tsx]" in result.stdout