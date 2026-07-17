## 1. 构建系统概览

ChanQuant 采用 Docker 容器化 + GitHub Actions CI/CD 的构建体系，覆盖后端 API（Flask）、MCP Agent Gateway、前端 SPA 三种产物。核心思路是：本地开发通过 docker-compose.yml 一键拉起全栈；CI 基于 tag 触发多架构镜像构建并推送到 GHCR；零仓库部署通过 docker-compose.ghcr.yml 直接拉取预编译镜像。

## 2. 关键文件与职责

- 后端镜像：backend_api_python/Dockerfile + gunicorn_config.py + docker-entrypoint.sh
- MCP 服务器镜像：mcp_server/Dockerfile + pyproject.toml（setuptools 打包）
- 编排定义：docker-compose.yml（源码构建模式）、docker-compose.build.yml（前端本地覆盖）、docker-compose.ghcr.yml（GHCR 预构建镜像模式）
- 依赖声明：backend_api_python/requirements.txt、mcp_server/pyproject.toml
- 版本脚本：scripts/bump_version.py、scripts/check_version.py
- CI 流水线：.github/workflows/basic-ci.yml、docker-publish.yml、openapi-ci.yml

## 3. 架构与约定

### 3.1 多环境镜像构建

后端 Dockerfile 通过 BUILD_REGION 参数切换 apt/PyPI 源：
- global（默认）：直接使用官方 Debian/PyPI，适合海外 runner
- cn：优先 Aliyun 镜像，失败回退官方，适配中国大陆网络

镜像注入 APP_VERSION 和 GIT_TAG 作为运行时元数据写入 /app/BUILD_VERSION 与 /app/BUILD_GIT_TAG。

### 3.2 双入口编排策略

| 场景 | Compose 文件 | 行为 |
|------|-------------|------|
| 本地开发 | docker-compose.yml | 从源码构建 backend，从 GHCR 拉取 frontend |
| 前端热迭代 | -f docker-compose.yml -f docker-compose.build.yml | 覆盖 frontend build context 为本地 ./ChanQuant-Vue |
| 零仓库部署 | docker-compose.ghcr.yml | 全部拉取 GHCR 预构建镜像，仅挂载 backend.env |

所有 compose 文件通过 .env 变量统一控制 IMAGE_PREFIX、IMAGE_TAG、端口映射等。

### 3.3 运行期安全启动

docker-entrypoint.sh 在容器启动时：
- 若缺少 /app/.env 则从 env.example 复制
- 若 SECRET_KEY 为空或等于默认值，自动生成随机密钥并写回宿主挂载点
- 校验密钥长度 >= 32 字节，否则发出警告

### 3.4 WSGI 并发模型

Gunicorn 使用 gthread worker_class（单进程多线程），默认 1 worker x 4 threads，可通过环境变量 GUNICORN_WORKERS、GUNICORN_THREADS 调整。preload_app=False 确保后台线程在 fork 后的 worker 中正确初始化。

### 3.5 MCP 包发布

MCP 服务器使用标准 setuptools 打包，pyproject.toml 定义 ChanQuant-mcp 控制台脚本入口，支持 pip install . 安装并通过 CLI 启动。

## 4. CI/CD 流水线

### Basic CI（每次 push/PR）
- Python 语法检查（compileall）+ 核心模块导入验证
- 三个 compose 文件语法校验（含合并 override）
- 版本一致性检查（scripts/check_version.py）
- 乱码检测（scripts/check_mojibake.py）

### OpenAPI CI（变更 openapi 相关路径时触发）
- 导出当前代码的 OpenAPI spec 并与 docs/api/openapi.yaml 对比，防止文档漂移
- Spectral 规则集校验人类可读 API 与 Agent API
- oasdiff 阻断破坏性变更

### Docker Publish（v* tag 推送或手动触发）
- QEMU + buildx 构建 linux/amd64 + linux/arm64 多架构镜像
- 标签策略：vX.Y.Z、X.Y、latest（仅 v* tag）、短 SHA
- 自动创建 GitHub Release 并附带镜像拉取命令

## 5. 开发者应遵循的规则

1. 依赖更新：修改 requirements.txt 后需确认无 Windows-only 包泄漏到 CI（CI 会 grep 过滤 MetaTrader5）
2. OpenAPI 契约：新增/修改路由后必须运行 python scripts/export_openapi.py 同步 docs/api/openapi.yaml，否则 CI 失败
3. 版本管理：发布前执行 python scripts/bump_version.py X.Y.Z 同步根目录与后端 VERSION 文件
4. Compose 配置：新增服务或环境变量需同时更新 docker-compose.yml 与 docker-compose.ghcr.yml，保持两者语义一致
5. 镜像构建区域：在海外 runner 上构建务必保持 BUILD_REGION=global，避免 Aliyun 镜像回退带来的超时
6. SECRET_KEY：生产部署必须提供非默认的 SECRET_KEY，entrypoint 不会阻止启动但会发出警告