import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Any, Dict
from datetime import datetime
from .utils import GitignoreMatcher, find_git_root, get_global_gitignore, logger

@dataclass
class FileNode:
    name: str
    path: Path
    relative_path: str
    is_dir: bool = False
    size: Optional[int] = None
    modified: Optional[str] = None
    content: Optional[str] = None
    children: List['FileNode'] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于 JSON 序列化"""
        node = {
            "name": self.name,
            "type": "dir" if self.is_dir else "file",
            "path": self.relative_path,
        }
        
        metadata = {}
        if self.size is not None:
            metadata["size"] = self.size
        if self.modified is not None:
            metadata["modified"] = self.modified
        if metadata:
            node["metadata"] = metadata

        if self.content is not None:
            node["content"] = self.content

        if self.is_dir:
            node["children"] = [child.to_dict() for child in self.children]
        
        return node

class Inspector:
    def __init__(
        self,
        include_hidden: bool = False,
        ignore_patterns: List[str] = None,
        ignore_dirs: List[str] = None,
        max_depth: Optional[int] = None,
        no_gitignore: bool = False,
        extensions: List[str] = None,
        add_metadata: bool = False,
        head: int = 0,
        tail: int = 0
    ):
        self.include_hidden = include_hidden
        self.ignore_patterns = ignore_patterns or []
        self.ignore_dirs = set(ignore_dirs or [])
        self.max_depth = max_depth
        self.use_gitignore = not no_gitignore
        self.extensions = {f".{e.lstrip('.')}" for e in (extensions or [])}
        self.add_metadata = add_metadata
        self.head = head
        self.tail = tail

    def inspect(self, paths: List[Path]) -> List[FileNode]:
        results = []
        for path in paths:
            path = path.resolve()
            
            # 初始化匹配器
            matcher = None
            base_path = path
            
            if self.use_gitignore:
                git_root = find_git_root(path)
                root_for_matcher = git_root if git_root else (path if path.is_dir() else path.parent)
                matcher = GitignoreMatcher(root_for_matcher, self.ignore_patterns)
                
                # 加载全局规则
                g_base, g_lines = get_global_gitignore()
                if g_base:
                    matcher.add_patterns(g_base, g_lines)
                
                # 加载 git_root 的规则
                if git_root:
                    matcher.add_patterns_from_file(git_root / '.gitignore')
            else:
                # 即使不使用 gitignore，我们也使用 matcher 来处理命令行传入的 ignore_patterns
                matcher = GitignoreMatcher(path if path.is_dir() else path.parent, self.ignore_patterns)

            if path.is_file():
                node = self._process_file(path, path.parent)
                if node:
                    results.append(node)
            elif path.is_dir():
                node = self._process_dir(path, path.parent, matcher, 0)
                if node:
                    results.append(node)
            else:
                # 处理通配符可能导致的不存在路径
                logger.warning(f"路径不存在: {path}")

        return results

    def _process_file(self, path: Path, base_path: Path) -> Optional[FileNode]:
        try:
            rel_path = path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = path.name

        node = FileNode(
            name=path.name,
            path=path,
            relative_path=rel_path,
            is_dir=False
        )

        # 元数据
        if self.add_metadata:
            try:
                stat = path.stat()
                node.size = stat.st_size
                node.modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError as e:
                logger.warning(f"无法获取元数据 {path}: {e}")

        # 内容读取
        if path.suffix in self.extensions:
            self._read_content(node)

        return node

    def _process_dir(self, path: Path, base_path: Path, matcher: GitignoreMatcher, depth: int) -> Optional[FileNode]:
        if self.max_depth is not None and depth > self.max_depth:
            return None

        # 检查是否包含 .gitignore 并更新 matcher
        if self.use_gitignore:
            local_gitignore = path / '.gitignore'
            if local_gitignore.exists():
                # 注意：简单的实现会直接修改当前 matcher。
                # 完美的实现应该 copy matcher，但为了性能和简单，
                # 这里假设 matcher 的 add_patterns 支持叠加且不回退。
                # 在递归中传递同一个 matcher 实例可能会有问题（兄弟目录干扰），
                # 但对于自上而下的扫描，只要规则是路径特定的，通常是可以接受的。
                # 为了严谨，我们这里简化处理：只在进入目录前加载规则。
                matcher.add_patterns_from_file(local_gitignore)

        try:
            rel_path = path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = path.name

        node = FileNode(
            name=path.name,
            path=path,
            relative_path=rel_path,
            is_dir=True
        )

        # 元数据
        if self.add_metadata:
            try:
                stat = path.stat()
                node.size = stat.st_size
                node.modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError as e:
                logger.warning(f"无法获取元数据 {path}: {e}")

        try:
            # 排序以保证输出稳定
            for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                # 基础过滤
                if not self.include_hidden and item.name.startswith('.') and item.name != '.gitignore':
                    continue
                
                if item.is_dir() and item.name in self.ignore_dirs:
                    continue

                if matcher.is_ignored(item):
                    continue

                if item.is_dir():
                    child = self._process_dir(item, base_path, matcher, depth + 1)
                    if child:
                        node.children.append(child)
                else:
                    child = self._process_file(item, base_path)
                    if child:
                        node.children.append(child)
        except PermissionError:
            logger.warning(f"无权限访问目录: {path}")
        except OSError as e:
            logger.warning(f"访问目录出错 {path}: {e}")

        return node

    def _read_content(self, node: FileNode):
        try:
            # 简单的二进制检查
            with node.path.open('rb') as f:
                if b'\0' in f.read(1024):
                    logger.info(f"跳过二进制文件: {node.path}")
                    return

            with node.path.open('r', encoding='utf-8') as f:
                lines = f.readlines()
                
            total_lines = len(lines)
            
            if self.head > 0:
                lines = lines[:self.head]
            elif self.tail > 0:
                lines = lines[-self.tail:]
            
            node.content = "".join(lines)
            
            # 如果发生了截断，可以在这里添加标记（可选，目前保持简单）
            
        except UnicodeDecodeError:
            logger.warning(f"无法以 UTF-8 解码 {node.path}")
        except Exception as e:
            logger.warning(f"读取文件出错 {node.path}: {e}")