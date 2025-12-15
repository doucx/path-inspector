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
    children: List["FileNode"] = field(default_factory=list)

    def to_dict(self, compact: bool = False, is_root: bool = False) -> Dict[str, Any]:
        """转换为字典格式，用于 JSON 序列化"""
        
        # 决定显示的名称：根节点统一使用 '.'，因为它表示其绝对路径已在元数据中给出。
        display_name = "." if is_root else self.name
        
        if compact:
            # 紧凑模式: n (name), c (children), content (可选)
            node = {"n": display_name}
            
            if self.is_dir:
                node["c"] = [
                    child.to_dict(compact=True, is_root=False) for child in self.children
                ]
            
            if self.content is not None:
                node["content"] = self.content
                
            return node


        # 标准模式 (json)
        node = {
            "name": display_name, # 标准模式也使用规范化的名称
            "type": "dir" if self.is_dir else "file",
            "path": self.relative_path, # 标准模式保留 path
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
        read_all: bool = False,
        add_metadata: bool = False,
        head: int = 0,
        tail: int = 0,
    ):
        self.include_hidden = include_hidden
        self.ignore_patterns = ignore_patterns or []
        self.ignore_dirs = set(ignore_dirs or [])
        self.max_depth = max_depth
        self.use_gitignore = not no_gitignore
        self.extensions = {f".{e.lstrip('.')}" for e in (extensions or [])}
        self.read_all = read_all
        self.add_metadata = add_metadata
        self.head = head
        self.tail = tail

    def _should_read_content(self, path: Path) -> bool:
        """
        决策是否应该读取文件内容。
        优先级框架:
        1. read_all (强制读取所有)
        2. extensions (扩展名白名单)
        """
        if self.read_all:
            return True
        return path.suffix in self.extensions

    def _sort_children_recursive(self, node: FileNode):
        """递归排序子节点以确保输出稳定"""
        if not node.is_dir:
            return
        node.children.sort(key=lambda p: (not p.is_dir, p.name.lower()))
        for child in node.children:
            self._sort_children_recursive(child)

    def _ensure_dir_exists(
        self,
        dir_path: Path,
        base_path: Path,
        cache: Dict[Path, FileNode],
    ) -> FileNode:
        """递归地确保从 base_path 到 dir_path 的所有目录节点都已创建并存在于缓存中"""
        if dir_path in cache:
            return cache[dir_path]

        # 如果路径已经低于我们的基准路径，说明有问题或到达了根，使用基准路径的节点
        if base_path not in dir_path.parents and base_path != dir_path:
             # This happens for paths outside the CWD, we anchor them at root.
             return cache[base_path]
        
        # 递归地确保父节点存在
        parent_path = dir_path.parent
        parent_node = self._ensure_dir_exists(parent_path, base_path, cache)

        # 创建当前目录的节点
        try:
            rel_path = dir_path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = dir_path.name
            
        new_dir_node = FileNode(
            name=dir_path.name, path=dir_path, relative_path=rel_path, is_dir=True
        )
        cache[dir_path] = new_dir_node

        # 将新节点附加到父节点的 children 列表中
        parent_node.children.append(new_dir_node)
        return new_dir_node

    def inspect(self, paths: List[Path]) -> List[FileNode]:
        run_base_path = Path.cwd()
        dir_nodes_cache: Dict[Path, FileNode] = {}

        # 虚拟根节点，它的 children 将是最终结果
        # 它的路径是 CWD，但相对路径是 '.'
        root_node = FileNode(name=".", path=run_base_path, relative_path=".", is_dir=True)
        dir_nodes_cache[run_base_path] = root_node

        for path in paths:
            path = path.resolve()
            if not path.exists():
                logger.warning(f"路径不存在: {path}")
                continue

            matcher = None
            if self.use_gitignore:
                git_root = find_git_root(path)
                root_for_matcher = (
                    git_root if git_root else (path if path.is_dir() else path.parent)
                )
                matcher = GitignoreMatcher(root_for_matcher, self.ignore_patterns)

                # 加载全局规则
                g_base, g_lines = get_global_gitignore()
                if g_base:
                    matcher.add_patterns(g_base, g_lines)

                # 加载 git_root 的规则
                if git_root:
                    matcher.add_patterns_from_file(git_root / ".gitignore")
            else:
                # 即使不使用 gitignore，我们也使用 matcher 来处理命令行传入的 ignore_patterns
                matcher = GitignoreMatcher(
                    path if path.is_dir() else path.parent, self.ignore_patterns
                )

            if path.is_file():
                if matcher.is_ignored(path):
                    continue
                parent_node = self._ensure_dir_exists(path.parent, run_base_path, dir_nodes_cache)
                file_node = self._process_file(path, run_base_path)
                if file_node and not any(c.path == file_node.path for c in parent_node.children):
                    parent_node.children.append(file_node)

            elif path.is_dir():
                dir_tree_node = self._process_dir(path, run_base_path, matcher, 0)
                if dir_tree_node:
                    parent_node = self._ensure_dir_exists(path.parent, run_base_path, dir_nodes_cache)
                    
                    # 合并逻辑：如果目录节点已存在，则合并 children，否则直接添加
                    existing_node = next((c for c in parent_node.children if c.path == path), None)
                    if existing_node:
                        # 简单的合并：添加新节点中不存在的子节点
                        existing_children_paths = {c.path for c in existing_node.children}
                        for new_child in dir_tree_node.children:
                            if new_child.path not in existing_children_paths:
                                existing_node.children.append(new_child)
                    else:
                        parent_node.children.append(dir_tree_node)

        self._sort_children_recursive(root_node)
        return root_node.children

    def _process_file(self, path: Path, base_path: Path) -> Optional[FileNode]:
        try:
            rel_path = path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = path.name

        node = FileNode(name=path.name, path=path, relative_path=rel_path, is_dir=False)

        # 元数据
        if self.add_metadata:
            try:
                stat = path.stat()
                node.size = stat.st_size
                node.modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError as e:
                logger.warning(f"无法获取元数据 {path}: {e}")

        # 内容读取
        if self._should_read_content(path):
            self._read_content(node)

        return node

    def _process_dir(
        self, path: Path, base_path: Path, matcher: GitignoreMatcher, depth: int
    ) -> Optional[FileNode]:
        if self.max_depth is not None and depth > self.max_depth:
            return None

        if matcher.is_ignored(path):
            return None

        if self.use_gitignore:
            local_gitignore = path / ".gitignore"
            if local_gitignore.exists():
                matcher.add_patterns_from_file(local_gitignore)

        try:
            rel_path = path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = path.name

        node = FileNode(name=path.name, path=path, relative_path=rel_path, is_dir=True)

        if self.add_metadata:
            try:
                stat = path.stat()
                node.size = stat.st_size
                node.modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError as e:
                logger.warning(f"无法获取元数据 {path}: {e}")

        try:
            for item in path.iterdir():
                if (
                    not self.include_hidden
                    and item.name.startswith(".")
                    and item.name != ".gitignore"
                ):
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
            with node.path.open("rb") as f:
                if b"\0" in f.read(1024):
                    logger.info(f"跳过二进制文件: {node.path}")
                    return

            with node.path.open("r", encoding="utf-8") as f:
                lines = f.readlines()

            if self.head > 0:
                lines = lines[: self.head]
            elif self.tail > 0:
                lines = lines[-self.tail :]

            node.content = "".join(lines)

        except UnicodeDecodeError:
            logger.warning(f"无法以 UTF-8 解码 {node.path}")
        except Exception as e:
            logger.warning(f"读取文件出错 {node.path}: {e}")