import json
import io
from pathlib import Path
from path_inspector.core import FileNode
from path_inspector.renderers import JSONRenderer, XMLRenderer, ShowRenderer, CompactJSONRenderer


def create_dummy_tree():
    """创建一个简单的内存中的树结构用于渲染测试"""
    # root/
    #   - file1.txt (content: "hello")
    #   - sub/
    #     - file2.log
    root = FileNode(name="root", path=Path("/root"), relative_path="root", is_dir=True)
    f1 = FileNode(
        name="file1.txt",
        path=Path("/root/file1.txt"),
        relative_path="root/file1.txt",
        is_dir=False,
        content="hello",
    )
    sub = FileNode(
        name="sub", path=Path("/root/sub"), relative_path="root/sub", is_dir=True
    )
    f2 = FileNode(
        name="file2.log",
        path=Path("/root/sub/file2.log"),
        relative_path="root/sub/file2.log",
        is_dir=False,
    )

    root.children = [f1, sub]
    sub.children = [f2]
    return [root]


def test_json_renderer_standard():
    nodes = create_dummy_tree()
    renderer = JSONRenderer()
    output = io.StringIO()

    renderer.render(
        nodes, 
        output, 
        absolute_path="/tmp/scan/root", 
        repository_root="/tmp"
    )
    result = output.getvalue()

    # 验证是否为有效 JSON
    data = json.loads(result)
    assert data["absolute_path"] == "/tmp/scan/root"
    assert data["repository_root"] == "/tmp"
    assert "results" in data
    assert len(data["results"]) == 1
    root_json = data["results"][0]

    # 标准模式下 name 应该被规范化为 '.'
    assert root_json["name"] == "."
    assert root_json["type"] == "dir"
    # 标准模式下 path 属性应该保留
    assert "path" in root_json 
    assert len(root_json["children"]) == 2

    # 检查文件内容是否包含
    f1_json = root_json["children"][0]
    assert f1_json["name"] == "file1.txt"
    assert f1_json["content"] == "hello"


def test_compact_json_renderer():
    nodes = create_dummy_tree()
    renderer = CompactJSONRenderer()
    output = io.StringIO()

    renderer.render(
        nodes, 
        output, 
        absolute_path="/tmp/scan/root", 
        repository_root="/tmp"
    )
    result = output.getvalue()

    # 验证是否为有效、紧凑的 JSON
    data = json.loads(result)
    assert data["meta"]["abs"] == "/tmp/scan/root"
    assert data["meta"]["repo"] == "/tmp"
    root_json_list = data["data"]
    assert len(root_json_list) == 1
    root_json = root_json_list[0]

    # 紧凑模式下 name 应该被规范化为 '.'
    assert root_json["n"] == "."
    # 紧凑模式不包含 type, path, metadata 属性
    assert "type" not in root_json
    assert "path" not in root_json
    
    # 检查文件内容是否包含 (key 'content')
    # 子节点应该使用 basename 作为 'n'
    f1_json = root_json["c"][0]
    assert f1_json["n"] == "file1.txt"
    assert f1_json["content"] == "hello"
    
    # 验证输出非常紧凑 (没有缩进空格)
    assert "\n" not in result
    assert " " not in result.strip()


def test_xml_renderer():
    nodes = create_dummy_tree()
    renderer = XMLRenderer()
    output = io.StringIO()

    renderer.render(
        nodes, 
        output, 
        absolute_path="/tmp/scan/root", 
        repository_root="/tmp"
    )
    result = output.getvalue()

    assert 'absolute_path="/tmp/scan/root"' in result
    assert 'repository_root="/tmp"' in result
    assert "<?xml" in result
    assert '<Directory name="root"' in result
    assert '<File name="file1.txt"' in result
    # 确保文件/目录节点没有冗余的 'path=' 属性
    assert '<File name="file1.txt" path="' not in result 
    assert '<Directory name="root" path="' not in result
    # Root(indent=1) -> File(indent=2, prefix=4 spaces) -> CDATA(prefix + 2 spaces = 6 spaces)
    assert "      <![CDATA[\nhello\n      ]]>" in result


def test_show_renderer():
    nodes = create_dummy_tree()
    renderer = ShowRenderer()
    output = io.StringIO()

    renderer.render(
        nodes, 
        output, 
        absolute_path="/tmp/scan/root",
        repository_root="/tmp"
    )
    result = output.getvalue()
    
    assert "Absolute Path: /tmp/scan/root (Repo Root: /tmp)" in result
    assert "文件: root/file1.txt" in result
    assert "--- 内容开始 ---" in result
    assert "hello" in result
    # file2 没有内容，Show 模式默认不显示没有内容的文件的块（除非有元数据，但这里是最简测试）
    assert "file2.log" not in result
