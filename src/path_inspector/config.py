import json
from pathlib import Path
from typing import Any

from .utils import find_git_root, logger

CONFIG_FILE_NAME = "piconfig.json"


def find_config_file(custom_path: Path | None = None) -> Path | None:
    """按优先级查找配置文件: 显式指定 > CWD > Git Root > 用户全局目录"""
    if custom_path:
        if custom_path.is_file():
            return custom_path.resolve()
        logger.warning(f"指定的配置文件不存在: {custom_path}")
        return None

    # 1. 当前工作目录
    cwd_config = Path.cwd() / CONFIG_FILE_NAME
    if cwd_config.is_file():
        return cwd_config.resolve()

    # 2. Git 根目录
    git_root = find_git_root(Path.cwd())
    if git_root:
        git_config = git_root / CONFIG_FILE_NAME
        if git_config.is_file():
            return git_config.resolve()

    # 3. 用户全局配置
    global_config_1 = Path.home() / ".config" / "path-inspector" / CONFIG_FILE_NAME
    if global_config_1.is_file():
        return global_config_1.resolve()

    global_config_2 = Path.home() / f".{CONFIG_FILE_NAME}"
    if global_config_2.is_file():
        return global_config_2.resolve()

    return None


def get_all_presets(config_path: Path | None = None) -> dict[str, Any]:
    """获取配置文件中定义的所有预设"""
    target_config = find_config_file(config_path)
    if not target_config:
        return {}

    try:
        with open(target_config, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("presets", {})
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"读取配置文件 {target_config} 失败: {e}")
        return {}


def load_preset(
    config_path: Path | None = None, preset_name: str | None = None
) -> dict[str, Any]:
    """从配置文件中读取指定预设或 default 预设的参数字典"""
    target_config = find_config_file(config_path)
    if not target_config:
        if preset_name:
            logger.error(f"未找到配置文件，无法加载预设 '{preset_name}'")
        return {}

    presets = get_all_presets(target_config)
    selected_name = preset_name or "default"

    if selected_name not in presets:
        if preset_name:
            available = ", ".join(presets.keys()) if presets else "无"
            logger.error(
                f"预设 '{preset_name}' 不存在于 {target_config} 中。可用预设: {available}"
            )
        return {}

    logger.info(f"成功从 {target_config.name} 加载预设: [{selected_name}]")
    return presets[selected_name]
