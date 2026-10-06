from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .utils import GitignoreMatcher, find_git_root, get_global_gitignore, logger


@dataclass
class FileNode:
    name: str
    path: Path
    relative_path: str
    is_dir: bool = False
    size: int | None = None
    modified: str | None = None
    content: str | None = None
    children: list["FileNode"] = field(default_factory=list)

    def to_dict(self, compact: bool = False, is_root: bool = False) -> dict[str, Any]:
        """转换为字典格式，用于 JSON 序列化"""
        if is_root:
            display_name = "." if self.is_dir else (self.relative_path or self.name)
        else:
            display_name = self.name

        if compact:
            node: dict[str, Any] = {"n": display_name}
            if self.is_dir:
                node["c"] = [
                    child.to_dict(compact=True, is_root=False)
                    for child in self.children
                ]
            if self.content is not None:
                node["content"] = self.content
            return node

        node: dict[str, Any] = {
            "name": display_name,
            "type": "dir" if self.is_dir else "file",
            "path": self.relative_path,
        }

        metadata: dict[str, Any] = {}
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


class PathTreeBuilder:
    """
    标准路径前缀树构建器 (Canonical Path Trie Builder)
    统一处理离散路径与子树挂载，保证层级稳定与子节点无损归并。
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.root = FileNode(name=".", path=base_path, relative_path=".", is_dir=True)

    def _get_or_create_dir(self, target_dir: Path) -> FileNode:
        """根据路径前缀逐级查找或创建中间目录节点"""
        if target_dir == self.base_path or self.base_path not in target_dir.parents:
            return self.root

        try:
            rel_parts = target_dir.relative_to(self.base_path).parts
        except ValueError:
            return self.root

        curr = self.root
        accum = self.base_path
        for part in rel_parts:
            accum = accum / part
            existing = next(
                (c for c in curr.children if c.name == part and c.is_dir), None
            )
            if existing is None:
                rel_str = accum.relative_to(self.base_path).as_posix()
                new_node = FileNode(
                    name=part, path=accum, relative_path=rel_str, is_dir=True
                )
                curr.children.append(new_node)
                curr = new_node
            else:
                curr = existing
        return curr

    def add_file(self, file_node: FileNode) -> None:
        """挂载单个文件节点"""
        parent = self._get_or_create_dir(file_node.path.parent)
        if not any(c.path == file_node.path for c in parent.children):
            parent.children.append(file_node)

    def add_dir(self, dir_node: FileNode) -> None:
        """挂载目录子树，同路径子树进行并集归并"""
        parent = self._get_or_create_dir(dir_node.path.parent)
        existing = next((c for c in parent.children if c.path == dir_node.path), None)
        if existing is not None:
            existing_paths = {c.path for c in existing.children}
            for child in dir_node.children:
                if child.path not in existing_paths:
                    existing.children.append(child)
        else:
            parent.children.append(dir_node)

    def build(self) -> list[FileNode]:
        """递归排序并返回顶层节点列表"""
        self._sort_recursive(self.root)
        return self.root.children

    def _sort_recursive(self, node: FileNode) -> None:
        if not node.is_dir:
            return
        node.children.sort(key=lambda p: (not p.is_dir, p.name.lower()))
        for child in node.children:
            self._sort_recursive(child)


class TraversalFilter:
    """遍历过滤规格集 (Specification Pattern)"""

    def __init__(
        self,
        include_hidden: bool,
        ignore_dirs: set[str],
        max_depth: int | None,
        matcher: GitignoreMatcher | None,
    ):
        self.include_hidden = include_hidden
        self.ignore_dirs = ignore_dirs
        self.max_depth = max_depth
        self.matcher = matcher

    def should_skip_dir(self, path: Path, depth: int) -> bool:
        if self.max_depth is not None and depth > self.max_depth:
            return True
        return bool(self.matcher and self.matcher.is_ignored(path))

    def should_skip_child_entry(self, item: Path) -> bool:
        if (
            not self.include_hidden
            and item.name.startswith(".")
            and item.name != ".gitignore"
        ):
            return True
        if item.is_dir() and item.name in self.ignore_dirs:
            return True
        return bool(self.matcher and self.matcher.is_ignored(item))


class Inspector:
    def __init__(
        self,
        include_hidden: bool = False,
        ignore_patterns: list[str] | None = None,
        ignore_dirs: list[str] | None = None,
        max_depth: int | None = None,
        no_gitignore: bool = False,
        extensions: list[str] | None = None,
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
        if self.read_all:
            return True
        return path.suffix in self.extensions

    def _create_matcher(self, root_target: Path) -> GitignoreMatcher:
        if self.use_gitignore:
            git_root = find_git_root(root_target)
            root_for_matcher = (
                git_root
                if git_root
                else (root_target if root_target.is_dir() else root_target.parent)
            )
            matcher = GitignoreMatcher(root_for_matcher, self.ignore_patterns)

            g_base, g_lines = get_global_gitignore()
            if g_base:
                matcher.add_patterns(g_base, g_lines)

            if git_root:
                matcher.add_patterns_from_file(git_root / ".gitignore")
            return matcher

        return GitignoreMatcher(
            root_target if root_target.is_dir() else root_target.parent,
            self.ignore_patterns,
        )

    def inspect(self, paths: list[Path]) -> list[FileNode]:
        run_base_path = Path.cwd()
        builder = PathTreeBuilder(base_path=run_base_path)

        for raw_path in paths:
            path = raw_path.resolve()
            if not path.exists():
                logger.warning(f"路径不存在: {path}")
                continue

            matcher = self._create_matcher(path)
            filter_spec = TraversalFilter(
                include_hidden=self.include_hidden,
                ignore_dirs=self.ignore_dirs,
                max_depth=self.max_depth,
                matcher=matcher,
            )

            if path.is_file():
                if matcher.is_ignored(path):
                    continue
                file_node = self._process_file(path, run_base_path)
                if file_node:
                    builder.add_file(file_node)

            elif path.is_dir():
                dir_tree_node = self._process_dir(path, run_base_path, filter_spec, 0)
                if dir_tree_node:
                    builder.add_dir(dir_tree_node)

        return builder.build()

    def _process_file(self, path: Path, base_path: Path) -> FileNode | None:
        try:
            rel_path = path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = path.name

        node = FileNode(name=path.name, path=path, relative_path=rel_path, is_dir=False)

        if self.add_metadata:
            try:
                stat = path.stat()
                node.size = stat.st_size
                node.modified = datetime.fromtimestamp(
                    stat.st_mtime, tz=UTC
                ).isoformat()
            except OSError as e:
                logger.warning(f"无法获取元数据 {path}: {e}")

        if self._should_read_content(path):
            self._read_content(node)

        return node

    def _process_dir(
        self,
        path: Path,
        base_path: Path,
        filter_spec: TraversalFilter,
        depth: int,
    ) -> FileNode | None:
        if filter_spec.should_skip_dir(path, depth):
            return None

        if self.use_gitignore and filter_spec.matcher:
            local_gitignore = path / ".gitignore"
            if local_gitignore.exists():
                filter_spec.matcher.add_patterns_from_file(local_gitignore)

        try:
            rel_path = path.relative_to(base_path).as_posix()
        except ValueError:
            rel_path = path.name

        node = FileNode(name=path.name, path=path, relative_path=rel_path, is_dir=True)

        if self.add_metadata:
            try:
                stat = path.stat()
                node.size = stat.st_size
                node.modified = datetime.fromtimestamp(
                    stat.st_mtime, tz=UTC
                ).isoformat()
            except OSError as e:
                logger.warning(f"无法获取元数据 {path}: {e}")

        try:
            for item in path.iterdir():
                if filter_spec.should_skip_child_entry(item):
                    continue

                if item.is_dir():
                    child = self._process_dir(item, base_path, filter_spec, depth + 1)
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

        node.children.sort(key=lambda p: (not p.is_dir, p.name.lower()))
        return node

    def _read_content(self, node: FileNode):
        try:
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
        except OSError as e:
            logger.warning(f"读取文件出错 {node.path}: {e}")
