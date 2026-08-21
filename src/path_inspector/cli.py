import glob
import sys
from pathlib import Path
from typing import Annotated, Any

import click
import typer

from .config import find_config_file, get_all_presets, load_preset
from .core import Inspector
from .renderers import get_renderer
from .utils import find_git_root, logger, setup_logging

app = typer.Typer(
    help="一个强大的文件系统检查工具，支持多种格式输出 (XML, JSON, Show)。",
    add_completion=False,
)


def version_callback(value: bool):
    if value:
        from . import __version__

        typer.echo(f"path-inspector v{__version__}")
        raise typer.Exit()


def list_presets_callback(value: bool):
    if value:
        cfg_file = find_config_file()
        if not cfg_file:
            typer.secho("未找到任何 piconfig.json 配置文件。", fg=typer.colors.YELLOW)
            raise typer.Exit()

        presets = get_all_presets(cfg_file)
        if not presets:
            typer.echo(f"配置文件 {cfg_file} 中未定义任何预设。")
            raise typer.Exit()

        typer.secho(f"配置文件: {cfg_file}", fg=typer.colors.CYAN)
        typer.echo("可用预设:")
        for name, conf in presets.items():
            info_parts = []
            exts = conf.get("extension", [])
            if exts:
                info_parts.append(f"extensions: {', '.join(exts)}")
            paths = conf.get("paths") or conf.get("files")
            if paths:
                p_count = len(paths) if isinstance(paths, list) else 1
                info_parts.append(f"{p_count} 个预设路径")
            info_str = f" [{'; '.join(info_parts)}]" if info_parts else ""
            typer.echo(f"  - {name}{info_str}")
        raise typer.Exit()


@app.command()
def main(
    ctx: typer.Context,
    paths: Annotated[
        list[str] | None,
        typer.Argument(help="要检查的文件或目录路径，支持通配符。", show_default=False),
    ] = None,
    # --- 配置文件与预设 ---
    preset: Annotated[
        str | None,
        typer.Option(
            "-x",
            "--preset",
            help="使用 piconfig.json 中定义的预设配置 (如 'web', 'default')。",
        ),
    ] = None,
    config_file: Annotated[
        Path | None,
        typer.Option("-c", "--config", help="显式指定 piconfig.json 配置文件路径。"),
    ] = None,
    list_presets: Annotated[
        bool | None,
        typer.Option(
            "--list-presets",
            callback=list_presets_callback,
            is_eager=True,
            help="列出当前可用的所有预设并退出。",
        ),
    ] = None,
    # --- 格式与输出 ---
    format: Annotated[
        str,
        typer.Option(
            "-f", "--format", help="输出格式: xml (默认), json, compact, show。"
        ),
    ] = "xml",
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="将结果写入文件而不是标准输出。"),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="安静模式，仅显示错误信息。")
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="显示版本信息。"
        ),
    ] = None,
    # --- 过滤 ---
    all: Annotated[
        bool, typer.Option("-a", "--all", help="包含隐藏文件和目录 (以 . 开头)。")
    ] = False,
    ignore: Annotated[
        list[str] | None,
        typer.Option("-i", "--ignore", help="忽略匹配该模式的文件/目录 (如 '*.log')。"),
    ] = None,
    ignore_dir: Annotated[
        list[str] | None,
        typer.Option("--ignore-dir", help="忽略指定名称的目录 (如 'node_modules')。"),
    ] = None,
    max_depth: Annotated[
        int | None, typer.Option("--max-depth", help="递归扫描的最大深度。")
    ] = None,
    no_gitignore: Annotated[
        bool, typer.Option("--no-gitignore", help="不自动读取 .gitignore 文件。")
    ] = False,
    # --- 内容提取 ---
    extension: Annotated[
        list[str] | None,
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
    """
    setup_logging(quiet)

    # 加载配置文件与预设
    preset_kwargs = load_preset(config_file, preset)

    # 命令行显式指定参数优先于预设参数
    def get_param(name: str, cli_value: Any) -> Any:
        source = ctx.get_parameter_source(name)
        if source != click.core.ParameterSource.COMMANDLINE and name in preset_kwargs:
            val = preset_kwargs[name]
            # 兼容单个字符串传入 list 类型的配置
            if name in ("extension", "ignore", "ignore_dir") and isinstance(val, str):
                return [val]
            return val
        return cli_value

    format = get_param("format", format)
    all = get_param("all", all)
    ignore = get_param("ignore", ignore)
    ignore_dir = get_param("ignore_dir", ignore_dir)
    max_depth = get_param("max_depth", max_depth)
    no_gitignore = get_param("no_gitignore", no_gitignore)
    extension = get_param("extension", extension)
    read_all = get_param("read_all", read_all)
    add_metadata = get_param("add_metadata", add_metadata)
    head = get_param("head", head)
    tail = get_param("tail", tail)

    # 处理路径：若命令行未指定，优先使用预设中配置的 paths 或 files
    if paths is None:
        preset_paths = preset_kwargs.get("paths") or preset_kwargs.get("files")
        if preset_paths:
            if isinstance(preset_paths, str):
                paths = [preset_paths]
            elif isinstance(preset_paths, list):
                paths = preset_paths
        else:
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
        matches = list(glob.glob(p_str, recursive=True))
        if not matches:
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
    except (OSError, ValueError) as e:
        logger.error(f"扫描过程中发生错误: {e}")
        raise typer.Exit(1)

    # 渲染输出
    renderer = get_renderer(format)

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
    except (OSError, UnicodeEncodeError) as e:
        logger.error(f"生成输出时发生错误: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
