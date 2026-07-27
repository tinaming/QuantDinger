## 1. 使用的系统与工具
- **后端 API（Flask）**：使用 `pip` + `requirements.txt` 声明运行时依赖；通过 Dockerfile 中的 `BUILD_REGION=cn|global` 参数在阿里云 PyPI 镜像与官方源之间自动回退。
- **MCP Server（Agent Gateway）**：使用 PEP 621 风格的 `pyproject.toml` 发布为独立包 `ChanQuant-mcp`，支持 `pip install -e .`、`pipx`、`uvx` 三种安装方式，并通过 `[project.scripts]` 暴露 CLI 入口。
- **平台差异**：Windows 专属依赖（MetaTrader5）拆分到 `requirements-windows.txt`，由文档引导单独安装。
- **未使用**：无 `poetry.lock`/`Pipfile.lock`/`uv.lock` 等锁定文件，也未配置私有 PyPI 索引或 `--index-url`/`PIP_INDEX_URL`。

## 2. 关键文件
- `backend_api_python/requirements.txt` — 后端主依赖清单（Flask、ccxt、yfinance、akshare、litellm、flask-smorest、psycopg2-binary、redis、gunicorn 等），包含安全版本上限注释。
- `backend_api_python/requirements-windows.txt` — Windows 平台可选依赖（MetaTrader5）。
- `backend_api_python/Dockerfile` — 构建期按 `BUILD_REGION` 切换 PyPI 源并安装 requirements。
- `mcp_server/pyproject.toml` — MCP 包的元数据、依赖、可选 dev 依赖与可执行脚本定义。
- `mcp_server/Dockerfile` — 基于 `python:3.12-slim-bookworm` 的轻量镜像，配合 `uvx ChanQuant-mcp` 运行。

## 3. 架构与约定
- **分层依赖**：核心运行时集中在 `requirements.txt`；平台相关（MT5）与搜索增强（Tavily/SerpAPI）以“已注释”形式保留，按需启用，避免非必需依赖污染生产环境。
- **版本策略**：对存在已知漏洞的包显式标注 GHSA 编号与最低修复版本（如 Flask/Werkzeug、PyJWT），并对部分库设置上限区间（`litellm>=1.80,<1.87`、`flask-smorest>=0.44.0,<0.48`、`marshmallow>=3.24.1,<5`）防止破坏性升级。
- **多源回退**：Docker 构建时优先尝试阿里云镜像，失败则回退官方 PyPI，兼顾国内网络与海外 CI 的可复现性。
- **发布形态**：MCP 子项目作为独立 PyPI 包分发，客户端通过 `uvx ChanQuant-mcp` 零配置拉取，无需本地源码。

## 4. 开发者应遵循的规则
- 新增依赖一律写入对应位置的清单文件（后端 → `requirements.txt`，MCP → `pyproject.toml` 的 `dependencies`），不要直接 `pip install` 后不提交清单。
- 若依赖仅适用于 Windows（如 MetaTrader5），放入 `requirements-windows.txt` 并在 README/文档中说明安装步骤。
- 涉及安全修复的依赖需同步更新版本号并在注释中记录 GHSA 编号，便于审计。
- 如需引入新的可选功能依赖，保持“默认注释、按需启用”的模式，避免增大基础镜像体积。
- 当前仓库未生成 lock 文件，建议在团队内统一采用 `pip-tools`/`uv` 的锁定方案或在 CI 中固定解析结果，以保证构建可复现。