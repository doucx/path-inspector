import pytest
from pathlib import Path
from path_inspector.core import Inspector, FileNode

def test_inspector_basic_traversal(temp_workspace):
    """测试基本的文件遍历"""
    inspector = Inspector(no_gitignore=True) # 暂时忽略 gitignore 以测试纯遍历
    results = inspector.inspect([temp_workspace])
    
    assert len(results) == 1
    root = results[0]
    assert root.is_dir
    
    # 检查直接子节点
    child_names = {child.name for child in root.children}
    assert "main.py" in child_names
    assert "src" in child_names
    # 默认不包含隐藏文件
    assert ".secret" not in child_names 

def test_inspector_gitignore(temp_workspace):
    """测试 gitignore 规则应用"""
    inspector = Inspector(no_gitignore=False)
    results = inspector.inspect([temp_workspace])
    root = results[0]
    
    # 辅助函数用于递归查找文件
    def find_file(node, name):
        if node.name == name: return node
        for child in node.children:
            found = find_file(child, name)
            if found: return found
        return None

    # build/ 应被忽略 (目录规则)
    assert find_file(root, "build") is None
    
    # src/temp.log 应被忽略 (后缀规则)
    src_node = find_file(root, "src")
    assert src_node is not None
    assert find_file(src_node, "temp.log") is None
    assert find_file(src_node, "utils.py") is not None

def test_inspector_content_reading(temp_workspace):
    """测试内容读取和扩展名过滤"""
    # 仅读取 .py 文件
    inspector = Inspector(extensions=["py"], no_gitignore=True)
    results = inspector.inspect([temp_workspace])
    root = results[0]
    
    def find_file(node, name):
        if node.name == name: return node
        for child in node.children:
            res = find_file(child, name)
            if res: return res
        return None

    main_py = find_file(root, "main.py")
    assert main_py.content is not None
    assert "print('hello')" in main_py.content
    
    readme = find_file(root, "README.md")
    assert readme.content is None  # 没在扩展名列表中

def test_head_tail_logic(tmp_path):
    """专门测试 Head/Tail 逻辑"""
    f = tmp_path / "long.txt"
    # 创建一个 10 行的文件
    content = "".join([f"line {i}\n" for i in range(1, 11)])
    f.write_text(content, encoding="utf-8")
    
    # 测试 Head 3
    inspector_head = Inspector(extensions=["txt"], head=3)
    node_head = inspector_head.inspect([f])[0]
    assert node_head.content == "line 1\nline 2\nline 3\n"
    
    # 测试 Tail 2
    inspector_tail = Inspector(extensions=["txt"], tail=2)
    node_tail = inspector_tail.inspect([f])[0]
    assert node_tail.content == "line 9\nline 10\n"