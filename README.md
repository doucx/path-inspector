# Path Inspector

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.13+-green)
![License](https://img.shields.io/badge/license-MIT-purple)

**Path Inspector** 是一个强大的命令行文件系统检查与遍历工具。它旨在为开发者、代码审计人员和 AI 辅助开发提供一种统一、灵活的方式来扫描目录结构、提取文件内容并生成结构化的输出报告（XML, JSON 或纯文本）。

它特别适合用于：
- **LLM 上下文构建**：快速将整个代码库转换为 LLM 易于理解的 XML 或 JSON 格式。
- **代码审计**：快速概览项目结构，提取特定类型的文件内容。
- **文件系统分析**：统计文件大小、修改时间，并支持深度过滤。

## ✨ 核心特性

*   **多格式输出**: 支持 `xml` (默认, 适合 LLM), `json` (适合程序处理), 和 `show` (适合人类阅读) 三种模式。
*   **智能过滤**:
    *   支持标准的 Glob 通配符路径匹配。
    *   自动识别并遵循 `.gitignore` 规则（支持嵌套）。
    *   支持忽略特定目录（如 `node_modules`, `__pycache__`）。
    *   支持按文件扩展名提取内容。
*   **内容控制**:
    *   支持仅读取文件的前 N 行 (`--head`) 或后 N 行 (`--tail`)。
    *   自动检测并跳过二进制文件。
*   **元数据支持**: 可选包含文件大小和最后修改时间。

## 📦 安装

确保您的环境中有 Python 3.13+。

```bash
# 本地安装
pip install .

# 或者作为开发环境安装
pip install -e .
```

## 🚀 快速开始

### 基础扫描
扫描当前目录并生成 XML 输出（默认）：

```bash
path-inspector .
```

### 提取特定代码
扫描 `src` 目录，仅提取 `.py` 文件内容，并输出为 JSON 格式：

```bash
path-inspector src/ -e py --format json
```

### 生成 LLM 上下文
将项目核心代码转换为 XML 格式，排除测试目录，并保存到文件：

```bash
path-inspector . --ignore-dir tests -e py -e toml --output context.xml
```

### 快速预览
查看日志文件的最后 10 行：

```bash
path-inspector "*.log" --format show --tail 10
```

## 📖 详细用法

```text
Usage: path-inspector [OPTIONS] [PATHS]...

Arguments:
  [PATHS]...  要检查的文件或目录路径，支持通配符。

Options:
  -f, --format TEXT       输出格式: xml (默认), json, show。 [default: xml]
  -o, --output PATH       将结果写入文件而不是标准输出。
  -q, --quiet             安静模式，仅显示错误信息。
  --version               显示版本信息。

过滤选项:
  -a, --all               包含隐藏文件和目录 (以 . 开头)。
  -i, --ignore TEXT       忽略匹配该模式的文件/目录 (如 '*.log')。
  --ignore-dir TEXT       忽略指定名称的目录 (如 'node_modules')。
  --max-depth INTEGER     递归扫描的最大深度。
  --no-gitignore          不自动读取 .gitignore 文件。

内容提取选项:
  -e, --extension TEXT    提取指定扩展名文件的内容 (如 'py')。
  --read-all              读取所有通过过滤的文件的内容 (覆盖 -e 选项)。
  --add-metadata          包含文件大小和修改时间。
  -n, --head INTEGER      仅读取文件的前 N 行。
  -t, --tail INTEGER      仅读取文件的后 N 行 (与 --head 互斥)。
```

### 输出格式说明

#### XML (默认)
结构清晰，带有明确的层级和 CDATA 包裹，非常适合作为 Prompt 发送给 LLM。

```xml
<PathInspectorResults>
  <Directory name="src" path="src">
    <File name="main.py" path="src/main.py">
      <![CDATA[
import sys
...
      ]]>
    </File>
  </Directory>
</PathInspectorResults>
```

#### JSON
包含完整的结构信息，易于通过脚本进行二次处理。

```json
{
  "results": [
    {
      "name": "src",
      "type": "dir",
      "path": "src",
      "children": [
        {
          "name": "main.py",
          "type": "file",
          "path": "src/main.py",
          "content": "import sys\n..."
        }
      ]
    }
  ]
}
```

#### Show
适合在终端快速浏览文件内容。

```text
==========================================
文件: src/main.py
==========================================
--- 内容开始 ---
import sys
...
--- 内容结束 ---
```

## 🛠️ 开发指南

本项目使用 `hatchling` 作为构建后端，依赖 `typer` 处理命令行交互。

### 环境设置
```bash
# 安装依赖
pip install -r requirements.txt  # 如果有
# 或者直接安装项目及其依赖
pip install -e .
```

### 运行测试
项目包含完整的单元测试和集成测试，使用 `pytest` 运行：

```bash
pytest
```

## 📄 许可证

本项目采用 [MIT License](LICENSE) 授权。