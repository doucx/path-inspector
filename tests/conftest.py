import pytest


@pytest.fixture
def temp_workspace(tmp_path):
    """
    创建一个包含多种情况的临时文件系统环境：
    - 普通文件
    - 嵌套目录
    - 隐藏文件
    - .gitignore
    - 不同扩展名的文件
    """
    # 结构:
    # root/
    #   ├── .gitignore
    #   ├── main.py
    #   ├── README.md
    #   ├── .secret
    #   ├── src/
    #   │   ├── utils.py
    #   │   └── temp.log
    #   └── build/
    #       └── output.bin

    # 根目录文件
    (tmp_path / "main.py").write_text("import sys\nprint('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Project\nThis is a test project.\n", encoding="utf-8"
    )
    (tmp_path / ".secret").write_text("secret_key=123", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")

    # src 目录
    src = tmp_path / "src"
    src.mkdir()
    (src / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (src / "temp.log").write_text("error log content", encoding="utf-8")

    # build 目录 (应被 ignore)
    build = tmp_path / "build"
    build.mkdir()
    (build / "output.bin").write_bytes(b"\x00\x01\x02")

    return tmp_path
