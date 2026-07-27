## 1. 使用的系统与框架
- 标准库 `logging`，配合 `logging.handlers.RotatingFileHandler` 实现按大小轮转的文件输出。
- 未引入第三方结构化日志框架（如 loguru、structlog），所有模块统一通过应用内封装获取 logger。

## 2. 核心文件与入口
- `backend_api_python/app/utils/logger.py`：全局日志配置中心，提供 `setup_logger()` 和 `get_logger(name)`。
- `backend_api_python/app/__init__.py`：在 Flask app 创建流程中调用 `setup_logger()`，确保路由注册前日志已就绪。
- `backend_api_python/app/startup.py`：后台任务启动钩子，大量使用 `logger.info/warning/error` 记录关键生命周期事件。
- `backend_api_python/logs/`：默认日志输出目录，包含 `app.log` 及轮转后的历史文件。

## 3. 架构与约定
- **集中初始化**：`setup_logger()` 负责一次性完成以下工作：
  - 从环境变量 `LOG_LEVEL` 读取根日志级别（默认 `INFO`）；
  - 设置统一格式 `%(asctime)s - %(name)s - %(levelname)s - %(message)s`；
  - 将 `werkzeug`、`app.routes.kline` 等子树 logger 降级为 `WARNING`，减少噪音；
  - 对 `app.services.usdt_payment_service`、`app.routes.billing` 显式设为 `INFO`；
  - 创建 `logs/app.log` 的 `RotatingFileHandler`（单文件最大 10MB，保留 5 份）。
- **统一获取器**：各模块通过 `from app.utils.logger import get_logger` 并以 `__name__` 作为 logger 名称，形成以包路径为层级的命名空间（如 `app.data_providers.crypto`、`app.services.trading_executor`）。
- **结构化字段**：当前仅使用字符串模板拼接消息体，未采用 JSON 结构化字段；错误堆栈通过 `exc_info=True` 附加。
- **多进程/线程安全**：`RotatingFileHandler` 由 root logger 持有，多个 worker 线程共享同一文件句柄；未启用并发写入保护或独立文件 per-worker。

## 4. 开发者应遵循的规则
- **获取方式**：始终使用 `from app.utils.logger import get_logger` 并通过 `logger = get_logger(__name__)` 获取 logger，不要直接 `import logging; logging.getLogger(__name__)`（仓库中仍有少数旧写法，建议逐步替换）。
- **日志级别选择**：
  - `debug`：用于调试级中间状态、缓存命中/失效细节；
  - `info`：业务关键路径（策略恢复、USDT 支付启动、数据源拉取结果计数等）；
  - `warning`：可恢复异常或降级行为；
  - `error`：不可恢复错误或需要人工介入的问题，并附带 `exc_info=True`。
- **避免高频 debug**：kline、werkzeug 等子系统已被强制降级至 WARNING，若需临时提升请修改 `setup_logger` 中的对应子树级别。
- **不打印敏感信息**：当前无脱敏逻辑，请勿在日志中输出密钥、用户凭证或完整请求体。
- **日志位置**：生产环境日志位于容器内 `/app/logs/app.log`，可通过挂载卷持久化；开发环境位于项目根 `backend_api_python/logs/`。
- **未来扩展点**：如需结构化日志或外部 sink（ELK、Sentry），可在 `setup_logger()` 中追加自定义 Handler，保持现有 `get_logger` 接口不变。