import json
import sys
from xml.sax.saxutils import escape
from typing import List, TextIO
from .core import FileNode

class Renderer:
    def render(self, nodes: List[FileNode], output: TextIO):
        raise NotImplementedError

class JSONRenderer(Renderer):
    def render(self, nodes: List[FileNode], output: TextIO):
        data = {
            "results": [node.to_dict() for node in nodes]
        }
        # 使用 ensure_ascii=False 支持中文文件名
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write('\n')

class XMLRenderer(Renderer):
    def render(self, nodes: List[FileNode], output: TextIO):
        output.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        output.write('<PathInspectorResults>\n')
        for node in nodes:
            self._render_node(node, output, indent=1)
        output.write('</PathInspectorResults>\n')

    def _render_node(self, node: FileNode, output: TextIO, indent: int):
        prefix = '  ' * indent
        attrs = f'name="{escape(node.name)}" path="{escape(node.relative_path)}"'
        
        if node.size is not None:
            attrs += f' size="{node.size}"'
        if node.modified is not None:
            attrs += f' modified="{node.modified}"'

        if node.is_dir:
            output.write(f'{prefix}<Directory {attrs}>\n')
            for child in node.children:
                self._render_node(child, output, indent + 1)
            output.write(f'{prefix}</Directory>\n')
        else:
            if node.content is not None:
                output.write(f'{prefix}<File {attrs}>\n')
                output.write(f'{prefix}  <![CDATA[\n')
                output.write(node.content)
                # 确保 CDATA 闭合前有换行
                if not node.content.endswith('\n'):
                    output.write('\n')
                output.write(f'{prefix}  ]]>\n')
                output.write(f'{prefix}</File>\n')
            else:
                output.write(f'{prefix}<File {attrs} />\n')

class ShowRenderer(Renderer):
    def render(self, nodes: List[FileNode], output: TextIO):
        for node in nodes:
            self._process_node(node, output)
            
    def _process_node(self, node: FileNode, output: TextIO):
        if not node.is_dir and node.content is not None:
            self._print_file(node, output)
        
        # 即使是 Show 模式，如果用户对目录使用了 Show，我们也应该递归查找其中的内容
        # 因为 Show 模式本质上是"展示文件内容"
        if node.is_dir:
            for child in node.children:
                self._process_node(child, output)

    def _print_file(self, node: FileNode, output: TextIO):
        separator = "=" * 42
        output.write(f"{separator}\n")
        output.write(f"文件: {node.relative_path}\n")
        output.write(f"{separator}\n")
        
        if node.size is not None:
            output.write(f"大小: {node.size} bytes\n")
        if node.modified is not None:
            output.write(f"修改时间: {node.modified}\n")
            
        output.write(f"\n--- 内容开始 ---\n")
        output.write(node.content)
        if not node.content.endswith('\n'):
            output.write('\n')
        output.write(f"--- 内容结束 ---\n\n")

def get_renderer(format_name: str) -> Renderer:
    if format_name == 'json':
        return JSONRenderer()
    elif format_name == 'show':
        return ShowRenderer()
    else:
        return XMLRenderer()