## 系统概览

ChanQuant 采用纯环境变量驱动的配置体系，所有运行时配置通过 .env 文件与操作系统环境变量注入，不依赖数据库或外部配置中心。配置加载分为三层：进程入口层、元类属性访问层、以及兼容 PHP 风格的嵌套字典层。

## 核心架构

### 1. 配置加载流程
- 进程入口 (run.py)：启动时优先加载 backend_api_python/.env，再回退到仓库根目录 .env，使用 python-dotenv 的 override=False 模式，确保 OS 环境变量优先级最高
- 懒加载机制 (config_loader.py)：load_addon_config() 在首次调用时扫描所有已知的 OPENROUTER_*、FINNHUB_* 等环境变量，将其映射为 openrouter.api_key、finnhub.api_key 等嵌套字典结构，并缓存结果
- 元类属性访问：每个配置模块定义一个 MetaXxxConfig 元类，通过 @property 装饰器实现延迟读取，支持从 .env 直接读取或从 load_addon_config() 返回的嵌套结构中获取

### 2. 配置分层组织
- app/config/settings.py：应用基础配置（端口、调试、日志、限流）
- app/config/api_keys.py：第三方 API 密钥统一管理
- app/config/database.py：Redis/缓存连接参数
- app/config/data_sources.py：数据源专用配置（Finnhub、CCXT、AkShare 等）

### 3. 配置优先级规则
OS 环境变量 > backend_api_python/.env > 仓库根 .env > 代码默认值
对于 API Key 类配置，还支持从 load_addon_config() 返回的嵌套结构读取，形成双重来源。

### 4. 运行时动态更新
Admin Settings 页面提供对 .env 文件的读写能力：read_env_file() / write_env_file() 保留注释和格式，reload_dotenv() 通过 load_dotenv(override=True) 热重载生效，前端通过 /api/settings/schema 获取配置项元数据，按 Basic/Advanced 分组展示。

### 5. 安全机制
- SECRET_KEY 强制校验：生产环境（DEBUG=false）下若使用默认密钥，自动随机生成并警告
- 敏感信息隔离：.env 文件被 .gitignore 排除，部署文档强调通过容器环境变量注入
- 内部 API Key：INTERNAL_API_KEY 用于服务间认证，未配置时记录警告日志

## 开发者规范
1. 新增配置项：在对应配置模块的元类中添加 @property，同时更新 env.example 和 load_addon_config() 的 mappings 列表
2. 类型转换：使用 _config_int / _config_float / _config_str 辅助函数，或在元类中显式 int() / float() 转换
3. 布尔值处理：统一使用 .lower() in ('true', '1', 'yes') 模式判断
4. 默认值策略：关键安全配置（如 SECRET_KEY）必须设置明确的安全默认值并在启动时校验
5. 配置验证：在 startup.py 的启动钩子中进行业务相关的配置一致性检查