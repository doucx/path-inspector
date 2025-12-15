from typer.testing import CliRunner
from path_inspector.cli import app

runner = CliRunner()


def test_cli_help():
    """测试帮助信息是否正常显示"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "输出格式: xml (默认), json, show" in result.stdout


def test_cli_full_flow_json(temp_workspace):
    """
    集成测试：JSON 模式
    场景：扫描目录，提取 py 文件内容，忽略 log 文件（通过 gitignore），并包含元数据
    """
    result = runner.invoke(
        app,
        [
            str(temp_workspace),
            "--format",
            "json",
            "-e",
            "py",  # 提取 py 内容
            "--add-metadata",  # 添加元数据
            # 默认会自动使用目录下的 .gitignore
        ],
    )

    assert result.exit_code == 0

    # 验证输出
    import json

    data = json.loads(result.stdout)
    root = data["results"][0]

    # 验证 .gitignore 生效 (build 目录不在结果中)
    def has_node(nodes, name):
        for n in nodes:
            if n["name"] == name:
                return True
            if "children" in n and has_node(n["children"], name):
                return True
        return False

    assert not has_node([root], "build")
    assert has_node([root], "src")

    # 验证内容提取
    def get_content(nodes, name):
        for n in nodes:
            if n["name"] == name:
                return n.get("content")
            if "children" in n:
                res = get_content(n["children"], name)
                if res:
                    return res
        return None

    main_content = get_content([root], "main.py")
    assert main_content is not None
    assert "print('hello')" in main_content

    # 验证元数据存在
    assert "metadata" in root


def test_cli_show_mode_tail(temp_workspace):
    """
    集成测试：Show 模式 + Tail
    场景：查看 src 目录下 py 文件的最后一行
    """
    src_dir = temp_workspace / "src"

    result = runner.invoke(
        app, [str(src_dir), "--format", "show", "-e", "py", "--tail", "1"]
    )

    assert result.exit_code == 0
    assert (
        "文件: src/utils.py" in result.stdout
    )  # 这里的路径显示取决于 Inspector 计算的相对路径
    # utils.py 内容是 "def add(a, b):\n    return a + b\n"
    # tail 1 应该是 "    return a + b\n"
    assert "return a + b" in result.stdout
    assert "def add" not in result.stdout  # 第一行不应该出现


def test_cli_error_handling():
    """测试错误输入处理"""
    # 互斥参数
    result = runner.invoke(app, [".", "--head", "5", "--tail", "5"])
    assert result.exit_code == 1
    assert "不能同时指定" in result.stderr

    # 无效格式
    result = runner.invoke(app, [".", "--format", "yaml"])
    assert result.exit_code == 1
    assert "无效" in result.stderr
