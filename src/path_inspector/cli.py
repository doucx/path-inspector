import glob
import os
import sys
import tempfile
from dataclasses import dataclass
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


@dataclass(frozen=True)
class InspectorOptions:
    """
    规范化检查选项 (Parse, Don't Validate)
    在边界将 CLI 原始参数与预设合并为强类型的领域配置。
    """

    format: str
    all: bool
    ignore: list[str] | None
    ignore_dir: list[str] | None
    max_depth: int | None
    no_gitignore: bool
    extension: list[str] | None
    read_all: bool
    add_metadata: bool
    head: int
    tail: int
    paths: list[str]

    @classmethod
    def resolve(
        cls,
        ctx: typer.Context,
        preset_data: dict[str, Any],
        cli_values: dict[str, Any],
    ) -> "InspectorOptions":
        def is_cli_explicit(key: str) -> bool:
            kebab = key.replace("_", "-")
            for c in (ctx, getattr(ctx, "parent", None)):
                if c is not None:
                    src = c.get_parameter_source(key) or c.get_parameter_source(kebab)
                    if src == click.core.ParameterSource.COMMANDLINE:
                        return True
            return False

        def resolve_list(name: str, cli_val: list[str] | None) -> list[str] | None:
            preset_raw = preset_data.get(name)
            preset_list: list[str] = []
            if preset_raw:
                preset_list = (
                    [preset_raw] if isinstance(preset_raw, str) else list(preset_raw)
                )

            if cli_val is not None:
                if preset_list:
                    merged = list(cli_val)
                    for item in preset_list:
                        if item not in merged:
                            merged.append(item)
                    return merged
                return cli_val
            return preset_list if preset_list else None

        def resolve_scalar(name: str, cli_val: Any, default_val: Any) -> Any:
            if is_cli_explicit(name):
                return cli_val
            if name in preset_data and cli_val == default_val:
                return preset_data[name]
            return cli_val

        # 解析路径共存
        preset_paths_raw = preset_data.get("paths") or preset_data.get("files")
        preset_paths: list[str] = []
        if preset_paths_raw:
            preset_paths = (
                [preset_paths_raw]
                if isinstance(preset_paths_raw, str)
                else list(preset_paths_raw)
            )

        raw_cli_paths = cli_values.get("paths")
        if raw_cli_paths is None:
            final_paths = preset_paths if preset_paths else ["."]
        else:
            if preset_paths:
                combined = list(raw_cli_paths)
                for p in preset_paths:
                    if p not in combined:
                        combined.append(p)
                final_paths = combined
            else:
                final_paths = raw_cli_paths

        return cls(
            format=resolve_scalar("format", cli_values["format"], "xml"),
            all=resolve_scalar("all", cli_values["all"], False),
            ignore=resolve_list("ignore", cli_values["ignore"]),
            ignore_dir=resolve_list("ignore_dir", cli_values["ignore_dir"]),
            max_depth=resolve_scalar("max_depth", cli_values["max_depth"], None),
            no_gitignore=resolve_scalar(
                "no_gitignore", cli_values["no_gitignore"], False
            ),
            extension=resolve_list("extension", cli_values["extension"]),
            read_all=resolve_scalar("read_all", cli_values["read_all"], False),
            add_metadata=resolve_scalar(
                "add_metadata", cli_values["add_metadata"], False
            ),
            head=resolve_scalar("head", cli_values["head"], 0),
            tail=resolve_scalar("tail", cli_values["tail"], 0),
            paths=final_paths,
        )


def _atomic_write(output_path: Path, render_fn) -> None:
    """原子替换写入 (Atomic Replace via Temp File)"""
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_file_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            delete=False,
            prefix=f".{output_path.name}.tmp-",
        ) as f:
            temp_file_name = f.name
            render_fn(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file_name, output_path)
    except Exception:
        if temp_file_name and os.path.exists(temp_file_name):
            try:
                os.remove(temp_file_name)
            except OSError:
                pass
        raise


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

    preset_kwargs = load_preset(config_file, preset)
    cli_values = {
        "paths": paths,
        "format": format,
        "all": all,
        "ignore": ignore,
        "ignore_dir": ignore_dir,
        "max_depth": max_depth,
        "no_gitignore": no_gitignore,
        "extension": extension,
        "read_all": read_all,
        "add_metadata": add_metadata,
        "head": head,
        "tail": tail,
    }

    options = InspectorOptions.resolve(ctx, preset_kwargs, cli_values)

    # 参数校验
    if options.head > 0 and options.tail > 0:
        typer.secho(
            "错误: 不能同时指定 --head 和 --tail。", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    valid_formats = ["xml", "json", "compact", "show"]
    if options.format not in valid_formats:
        typer.secho(
            f"错误: 格式 '{options.format}' 无效。可用格式: {', '.join(valid_formats)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    # 路径通配符解析
    resolved_paths: list[Path] = []
    for p_str in options.paths:
        matches = list(glob.glob(p_str, recursive=True))
        if not matches:
            resolved_paths.append(Path(p_str))
        else:
            resolved_paths.extend([Path(m) for m in matches])

    if not resolved_paths:
        typer.secho("未找到匹配的路径。", fg=typer.colors.YELLOW, err=True)
        return

    inspector = Inspector(
        include_hidden=options.all,
        ignore_patterns=options.ignore,
        ignore_dirs=options.ignore_dir,
        max_depth=options.max_depth,
        no_gitignore=options.no_gitignore,
        extensions=options.extension,
        read_all=options.read_all,
        add_metadata=options.add_metadata,
        head=options.head,
        tail=options.tail,
    )

    logger.info("开始扫描...")
    try:
        nodes = inspector.inspect(resolved_paths)
    except (OSError, ValueError) as e:
        logger.error(f"扫描过程中发生错误: {e}")
        raise typer.Exit(1)

    renderer = get_renderer(options.format)
    cwd = Path.cwd()
    render_kwargs = {
        "absolute_path": str(cwd.resolve()),
        "repository_root": str(find_git_root(cwd)) if find_git_root(cwd) else None,
    }

    try:
        if output:
            _atomic_write(output, lambda f: renderer.render(nodes, f, **render_kwargs))
            if not quiet:
                typer.secho(f"结果已写入: {output}", fg=typer.colors.GREEN)
        else:
            renderer.render(nodes, sys.stdout, **render_kwargs)
    except (OSError, UnicodeEncodeError) as e:
        logger.error(f"生成输出时发生错误: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
