本仓库的错误处理采用「两层信封 + 领域异常」的架构，分别面向人类 REST API（/api/*）和 Agent Gateway（/api/agent/v1），并通过 flask-smorest 的 Blueprint 装饰器自动注入。

## 1. 人类 API 错误信封
- 成功体：HumanSuccessEnvelopeSchema（code=1, msg, data）
- 错误体：HumanErrorEnvelopeSchema（code=0, msg, data）
- 通过 app/openapi/blueprint.py 中的 HumanBlueprint.route() 在路由注册时自动为每个非 SSE 端点附加 @self.response(400, HumanErrorEnvelopeSchema) 与 @self.response(200, HumanSuccessEnvelopeSchema)，SSE 流式路径（/aiGenerate、/ai-optimize、/ai-generate）跳过信封包装。
- 辅助函数 app/openapi/helpers.py 提供 ok(...) 与 fail(msg, code, http_status) 快速返回标准信封。

## 2. Agent Gateway 错误信封
- 成功体：AgentSuccessEnvelopeSchema（code=0, message, data）
- 错误体：AgentErrorSchema（code, message, details, retriable）
- 由 app/routes/agent_v1/_helpers.py 的 envelope(...) 与 error(code, message, details, retriable, http) 构造，所有 agent 路由显式返回 (jsonify(...), status) 元组，避免被 Flask 再次包裹。
- Agent 侧 MCP 客户端（mcp_server/src/ChanQuant_mcp/security.py）对 SSE 事件做截断保护，并在 HTTP >=400 时将后端 JSON body 原样回传。

## 3. 领域异常类型
- app/data_sources/errors.py 定义数据源层异常：DataSourceError 基类、UnsupportedMarketError(market) 工厂无法识别市场类型时抛出并携带 market 属性。
- 其他模块广泛使用 Python 内置异常表达业务错误：ValueError 参数校验失败、NotImplementedError 抽象接口未实现、ImportError 可选依赖缺失时的降级。

## 4. 安全与输入校验错误
- app/routes/agent_v1/_security.py 集中定义敏感键白名单与指标代码大小上限（512 KiB），越界直接抛 ValueError；同时提供 redact_secrets() 递归脱敏工具，策略行返回前调用 redact_strategy_row() 屏蔽凭证字段。
- MCP 客户端与服务端保持常量同步（MAX_INDICATOR_CODE_BYTES、_SECRET_KEYS）。

## 5. 启动期与后台任务错误
- app/startup.py 中所有后台服务启动均用 try/except Exception 包裹并记录日志，确保单个组件失败不影响主进程；恢复运行策略时使用 traceback.format_exc() 输出堆栈。

## 6. 开发者约定
- 人类 API 路由：优先使用 ok(...) / fail(...) 返回信封；需要自定义 HTTP 状态码时通过 fail(msg, code, http_status)。
- Agent 路由：使用 _helpers.envelope(...) 与 _helpers.error(...)，注意返回值必须是 (response, status) 元组而非嵌套 tuple。
- 数据源层：自定义异常继承 DataSourceError，通用参数错误使用 ValueError。
- 禁止在路由中使用 raise HTTPException 或全局 @app.errorhandler——框架通过 smorest response 装饰器统一序列化错误体。
- 任何可能泄露密钥的响应必须经 redact_secrets / redact_strategy_row 处理后再返回。