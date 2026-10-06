import json
from typing import Any, TextIO
from xml.sax.saxutils import escape

from .core import FileNode


class NodeVisitor:
    """抽象树节点访问者协议 (AST / Tree Visitor Pattern)"""

    def enter_directory(self, node: FileNode, depth: int, is_root: bool) -> bool:
        """进入目录节点。返回 True 继续访问子节点，返回 False 跳过。"""
        return True

    def leave_directory(self, node: FileNode, depth: int, is_root: bool) -> None:
        """离开目录节点。"""

    def visit_file(self, node: FileNode, depth: int, is_root: bool) -> None:
        """访问文件节点。"""


def walk_tree(
    node: FileNode,
    visitor: NodeVisitor,
    depth: int = 0,
    is_root: bool = False,
) -> None:
    """通用的树遍历调度器，统一驱动 Visitor 执行"""
    if node.is_dir:
        should_descend = visitor.enter_directory(node, depth, is_root)
        if should_descend:
            for child in node.children:
                walk_tree(child, visitor, depth=depth + 1, is_root=False)
        visitor.leave_directory(node, depth, is_root)
    else:
        visitor.visit_file(node, depth, is_root)


class Renderer:
    def render(self, nodes: list[FileNode], output: TextIO, **kwargs: Any):
        raise NotImplementedError


class JSONRenderer(Renderer):
    def render(self, nodes: list[FileNode], output: TextIO, **kwargs: Any):
        data: dict[str, Any] = {
            "absolute_path": kwargs.get("absolute_path"),
            "repository_root": kwargs.get("repository_root"),
            "results": [node.to_dict(is_root=True) for node in nodes],
        }
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write("\n")


class CompactJSONRenderer(Renderer):
    def render(self, nodes: list[FileNode], output: TextIO, **kwargs: Any):
        data = {
            "meta": {
                "abs": kwargs.get("absolute_path"),
                "repo": kwargs.get("repository_root"),
            },
            "data": [node.to_dict(compact=True, is_root=True) for node in nodes],
        }
        json.dump(data, output, separators=(",", ":"), ensure_ascii=False)


class XMLVisitor(NodeVisitor):
    """XML 格式树生成访问者"""

    def __init__(self, output: TextIO, base_indent: int = 1):
        self.output = output
        self.base_indent = base_indent

    def enter_directory(self, node: FileNode, depth: int, is_root: bool) -> bool:
        indent = self.base_indent + depth
        prefix = "  " * indent
        display_name = node.relative_path if is_root else node.name
        attrs = f'name="{escape(display_name)}"'

        if node.size is not None:
            attrs += f' size="{node.size}"'
        if node.modified is not None:
            attrs += f' modified="{node.modified}"'

        self.output.write(f"{prefix}<Directory {attrs}>\n")
        return True

    def leave_directory(self, node: FileNode, depth: int, is_root: bool) -> None:
        indent = self.base_indent + depth
        prefix = "  " * indent
        self.output.write(f"{prefix}</Directory>\n")

    def visit_file(self, node: FileNode, depth: int, is_root: bool) -> None:
        indent = self.base_indent + depth
        prefix = "  " * indent
        display_name = node.relative_path if is_root else node.name
        attrs = f'name="{escape(display_name)}"'

        if node.size is not None:
            attrs += f' size="{node.size}"'
        if node.modified is not None:
            attrs += f' modified="{node.modified}"'

        if node.content is not None:
            self.output.write(f"{prefix}<File {attrs}>\n")
            self.output.write(f"{prefix}  <![CDATA[\n")
            self.output.write(node.content)
            if not node.content.endswith("\n"):
                self.output.write("\n")
            self.output.write(f"{prefix}  ]]>\n")
            self.output.write(f"{prefix}</File>\n")
        else:
            self.output.write(f"{prefix}<File {attrs} />\n")


class XMLRenderer(Renderer):
    def render(self, nodes: list[FileNode], output: TextIO, **kwargs: Any):
        output.write('<?xml version="1.0" encoding="UTF-8"?>\n')

        attrs = ""
        if kwargs.get("absolute_path"):
            attrs += f' absolute_path="{escape(kwargs["absolute_path"])}"'
        if kwargs.get("repository_root"):
            attrs += f' repository_root="{escape(kwargs["repository_root"])}"'

        output.write(f"<PathInspectorResults{attrs}>\n")

        visitor = XMLVisitor(output, base_indent=1)
        for node in nodes:
            walk_tree(node, visitor, depth=0, is_root=True)

        output.write("</PathInspectorResults>\n")


class ShowVisitor(NodeVisitor):
    """人类可读 Show 格式打印访问者"""

    def __init__(self, output: TextIO):
        self.output = output

    def enter_directory(self, node: FileNode, depth: int, is_root: bool) -> bool:
        return True

    def visit_file(self, node: FileNode, depth: int, is_root: bool) -> None:
        if node.content is None:
            return

        separator = "=" * 42
        self.output.write(f"{separator}\n")
        self.output.write(f"文件: {node.relative_path}\n")
        self.output.write(f"{separator}\n")

        if node.size is not None:
            self.output.write(f"大小: {node.size} bytes\n")
        if node.modified is not None:
            self.output.write(f"修改时间: {node.modified}\n")

        self.output.write("\n--- 内容开始 ---\n")
        self.output.write(node.content)
        if not node.content.endswith("\n"):
            self.output.write("\n")
        self.output.write("--- 内容结束 ---\n\n")


class ShowRenderer(Renderer):
    def render(self, nodes: list[FileNode], output: TextIO, **kwargs: Any):
        header = f"Absolute Path: {kwargs.get('absolute_path')}"
        if kwargs.get("repository_root"):
            header += f" (Repo Root: {kwargs.get('repository_root')})"

        output.write(f"{header}\n")
        output.write("-" * len(header) + "\n\n")

        visitor = ShowVisitor(output)
        for node in nodes:
            walk_tree(node, visitor, depth=0, is_root=True)


def get_renderer(format_name: str) -> Renderer:
    if format_name == "json":
        return JSONRenderer()
    elif format_name == "compact":
        return CompactJSONRenderer()
    elif format_name == "show":
        return ShowRenderer()
    else:
        return XMLRenderer()
