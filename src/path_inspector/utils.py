import logging
import fnmatch
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional


# 配置日志
def setup_logging(quiet: bool = False):
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level, format="%(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )


logger = logging.getLogger("path-inspector")


class GitignoreMatcher:
    """
    处理 .gitignore 规则的匹配器。
    支持层级规则应用和全局 gitignore。
    """

    def __init__(self, root_path: Path, additional_patterns: List[str] = None):
        self.root_path = root_path
        # 存储格式: (base_path, [(pattern, is_negated)])
        self.patterns: List[Tuple[Path, List[Tuple[str, bool]]]] = []

        if additional_patterns:
            self.add_patterns(self.root_path, additional_patterns)

    def add_patterns_from_file(self, gitignore_path: Path):
        """加载并解析 .gitignore 文件"""
        if not gitignore_path.is_file():
            return

        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.add_patterns(gitignore_path.parent, lines)
        except OSError as e:
            logger.debug(f"无法读取 .gitignore {gitignore_path}: {e}")

    def add_patterns(self, base_path: Path, lines: List[str]):
        """解析规则行"""
        parsed = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            is_negated = line.startswith("!")
            if is_negated:
                line = line[1:]

            # 处理目录标记
            if line.endswith("/"):
                line = line.rstrip("/")

            parsed.append((line, is_negated))

        if parsed:
            self.patterns.append((base_path, parsed))

    def is_ignored(self, path: Path) -> bool:
        """检查路径是否被忽略"""
        # 转换为相对于 root 的路径进行初步检查
        try:
            path.relative_to(self.root_path)
        except ValueError:
            # 路径不在 root 下，不适用规则
            return False

        is_ignored_flag = False

        for base_path, patterns in self.patterns:
            try:
                rel_to_base = path.relative_to(base_path).as_posix()
            except ValueError:
                continue  # 规则不适用于此路径

            path_name = path.name

            for pattern, is_negated in patterns:
                matched = False

                # 处理 ** (简化版)
                pat = pattern.replace("**", "*")

                # 1. 匹配文件名 (name match) - 适用于没有斜杠的模式
                if "/" not in pat:
                    if fnmatch.fnmatch(path_name, pat):
                        matched = True

                # 2. 匹配路径 (path match)
                # 如果模式以 / 开头，则它是相对于 .gitignore 位置的锚定路径
                if not matched:
                    check_path = rel_to_base
                    if pat.startswith("/"):
                        pat = pat[1:]

                    if fnmatch.fnmatch(check_path, pat):
                        matched = True

                if matched:
                    is_ignored_flag = not is_negated

        return is_ignored_flag


def find_git_root(start_path: Path) -> Optional[Path]:
    """向上查找 .git 目录"""
    current = start_path.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists():
            return parent
    return None


def get_global_gitignore() -> Tuple[Optional[Path], List[str]]:
    """获取全局 gitignore 配置"""
    try:
        res = subprocess.run(
            ["git", "config", "--get", "core.excludesfile"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            path = Path(res.stdout.strip()).expanduser().resolve()
            if path.is_file():
                return path.parent, path.read_text(encoding="utf-8").splitlines()
    except Exception:
        pass
    return None, []
