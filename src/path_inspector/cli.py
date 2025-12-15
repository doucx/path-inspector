import typer
import sys
import glob
from pathlib import Path
from typing import List, Optional
from typing_extensions import Annotated
from .core import Inspector
from .renderers import get_renderer
from .utils import setup_logging, logger, find_git_root

app = typer.Typer(
    help="一个强大的文件系统检查工具，支持多种格式输出 (XML, JSON, Show)。",
    add_completion=False,
)


def version_callback(value: bool):
    if value:
        from . import __version__

        typer.echo(f"path-inspector v{__version__}")
        raise typer.Exit()


@app.command()
def main(
    paths: Annotated[
        Optional[List[str]],
        typer.Argument(help="要检查的文件或目录路径，支持通配符。", show_default=False),
    ] = None,
    # --- 格式与输出 ---
    format: Annotated[
        str, typer.Option("-f", "--format", help="输出格式: xml (默认), json, compact, show。")
    ] = "xml",
    output: Annotated[
        Optional[Path],
        typer.Option("-o", "--output", help="将结果写入文件而不是标准输出。"),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="安静模式，仅显示错误信息。")
    ] = False,
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="显示版本信息。"
        ),
    ] = None,
    # --- 过滤 ---
    all: Annotated[
        bool, typer.Option("-a", "--all", help="包含隐藏文件和目录 (以 . 开头)。")
    ] = False,
    ignore: Annotated[
        Optional[List[str]],
        typer.Option("-i", "--ignore", help="忽略匹配该模式的文件/目录 (如 '*.log')。"),
    ] = None,
    ignore_dir: Annotated[
        Optional[List[str]],
        typer.Option("--ignore-dir", help="忽略指定名称的目录 (如 'node_modules')。"),
    ] = None,
    max_depth: Annotated[
        Optional[int], typer.Option("--max-depth", help="递归扫描的最大深度。")
    ] = None,
    no_gitignore: Annotated[
        bool, typer.Option("--no-gitignore", help="不自动读取 .gitignore 文件。")
    ] = False,
    # --- 内容提取 ---
    extension: Annotated[
        Optional[List[str]],
        typer.Option("-e", "--extension", help="提取指定扩展名文件的内容 (如 'py')。"),
    ] = None,
    read_all: Annotated[
        bool,
        typer.Option(
            "--read-all", help="读取所有通过过滤的文件的内容 (覆盖 -e 选项)。"
        ),
    ] = False,
    add_metadata: Annotated[
        bool, typer.Option("--add-metadata", help="包含文件大小和修改时间。")
    ] = False,
    head: Annotated[
        int, typer.Option("-n", "--head", help="仅读取文件的前 N 行。")
    ] = 0,
    tail: Annotated[
        int, typer.Option("-t", "--tail", help="仅读取文件的后 N 行 (与 --head 互斥)。")
    ] = 0,
):
    """
    Path Inspector - 文件系统遍历与导出工具

    示例:

      path-inspector . -e py --format json

      path-inspector src/ --ignore-dir __pycache__ -f xml

      path-inspector "*.log" --format show --tail 20
    """

    setup_logging(quiet)

    # 处理默认路径
    if paths is None:
        paths = ["."]

    # 参数验证
    if head > 0 and tail > 0:
        typer.secho(
            "错误: 不能同时指定 --head 和 --tail。", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    valid_formats = ["xml", "json", "compact", "show"]
    if format not in valid_formats:
        typer.secho(
            f"错误: 格式 '{format}' 无效。可用格式: {', '.join(valid_formats)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    # 路径解析 (处理通配符)
    resolved_paths = []
    for p_str in paths:
        # glob 在 Linux 上不自动展开 Argument，所以手动处理以防万一
        # 且支持 ** 递归
        matches = list(glob.glob(p_str, recursive=True))
        if not matches:
            # 如果 glob 没匹配到，可能是新建文件或纯文件名，直接加进去让 Inspector 报错或处理
            resolved_paths.append(Path(p_str))
        else:
            resolved_paths.extend([Path(m) for m in matches])

    if not resolved_paths:
        typer.secho("未找到匹配的路径。", fg=typer.colors.YELLOW, err=True)
        return

    # 初始化检查器
    inspector = Inspector(
        include_hidden=all,
        ignore_patterns=ignore,
        ignore_dirs=ignore_dir,
        max_depth=max_depth,
        no_gitignore=no_gitignore,
        extensions=extension,
        read_all=read_all,
        add_metadata=add_metadata,
        head=head,
        tail=tail,
    )

    # 执行扫描
    logger.info("开始扫描...")
    try:
        nodes = inspector.inspect(resolved_paths)
    except Exception as e:
        logger.error(f"扫描过程中发生错误: {e}")
        raise typer.Exit(1)

    # 渲染输出
    renderer = get_renderer(format)

    # 准备元数据
    # 统一使用 CWD 作为元数据的基准，以匹配 core.py 中的树构建逻辑。
    cwd = Path.cwd()
    absolute_path_meta = str(cwd.resolve())
    git_root = find_git_root(cwd)

    render_kwargs = {
        "absolute_path": absolute_path_meta,
        "repository_root": str(git_root) if git_root else None,
    }

    try:
        if output:
            with open(output, "w", encoding="utf-8") as f:
                renderer.render(nodes, f, **render_kwargs)
            if not quiet:
                typer.secho(f"结果已写入: {output}", fg=typer.colors.GREEN)
        else:
            renderer.render(nodes, sys.stdout, **render_kwargs)
    except Exception as e:
        logger.error(f"生成输出时发生错误: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
