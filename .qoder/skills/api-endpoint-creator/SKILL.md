---
name: api-endpoint-creator
description: >-
  为 ChanQuant 后端新增 REST API 端点。使用 flask-smorest 蓝图模式，
  包含 Schema 定义、权限检查、OpenAPI 文档自动生成。
  Trigger: '新接口', '新增API', 'add endpoint', 'new route', 'new API',
  '添加路由', '新增路由', 'REST API'
---

# 新增 API 端点 (API Endpoint Creator)

## 适用场景

需要添加新的 REST API 端点时使用，包括：
- 人类用户 API（`/api/...`，JWT 认证）
- Agent Gateway API（`/api/agent/v1/...`，Token 认证）

## 架构

```
app/routes/
├── __init__.py          ← register_routes() 注册蓝图
├── ai_chat.py           ← AI 聊天路由（参考）
├── strategies.py        ← 策略管理路由（参考）
├── market.py            ← 行情路由（参考）
└── agent_v1/            ← Agent Gateway（独立蓝图）
    ├── __init__.py
    ├── indicators.py
    └── ...

app/openapi/
├── schemas/             ← flask-smorest Schema 定义
│   └── ...
└── fields/              ← 可复用的 marshmallow 字段
```

## 执行步骤

### Step 1: 确定端点归属

| 场景 | 路由前缀 | 认证方式 | 放哪 |
|------|---------|---------|------|
| 人类用户功能 | `/api/` | JWT | `app/routes/` |
| AI Agent 调用 | `/api/agent/v1/` | Token | `app/routes/agent_v1/` |

### Step 2: 定义 Schema

```python
# app/openapi/schemas/my_feature.py

from marshmallow import Schema, fields, validate


class MyFeatureQuerySchema(Schema):
    """请求参数 Schema"""
    symbol = fields.Str(required=True, description="交易对，如 BTC/USDT")
    timeframe = fields.Str(
        required=False,
        validate=validate.OneOf(["1m", "5m", "15m", "1H", "4H", "1D"]),
        load_default="1H"
    )
    limit = fields.Int(required=False, load_default=100, validate=validate.Range(min=1, max=1000))


class MyFeatureResponseSchema(Schema):
    """响应 Schema"""
    success = fields.Bool()
    data = fields.List(fields.Dict())
    message = fields.Str()
```

### Step 3: 创建路由蓝图

```python
# app/routes/my_feature.py

from flask import Blueprint, jsonify
from flask.views import MethodView
from flask_smorest import abort
from app.openapi.schemas.my_feature import MyFeatureQuerySchema, MyFeatureResponseSchema
from app.utils.auth import token_required

bp = Blueprint("my_feature", __name__, url_prefix="/api/my-feature")


@bp.route("/")
class MyFeatureView(MethodView):
    decorators = [token_required]

    @bp.arguments(MyFeatureQuerySchema, location="query")
    @bp.response(200, MyFeatureResponseSchema)
    @bp.doc(description="获取我的功能数据")
    def get(self, args, **kwargs):
        """获取数据"""
        # 调用 service 层
        from app.services.my_feature_service import get_data
        result = get_data(args["symbol"], args["timeframe"], args["limit"])
        return {"success": True, "data": result}
```

### Step 4: 注册蓝图

在 `app/routes/__init__.py` 的 `register_routes()` 中添加：

```python
from app.routes.my_feature import bp as my_feature_bp
api.register_blueprint(my_feature_bp)
```

### Step 5: 编写测试

```python
# tests/test_my_feature.py

def test_get_my_feature_success(client, app):
    """验证正常请求返回 200"""
    with app.app_context():
        # 先登录获取 JWT token
        login_resp = client.post("/api/auth/login", json={
            "username": "testadmin", "password": "testpass123"
        })
        token = login_resp.get_json()["token"]

        resp = client.get(
            "/api/my-feature/?symbol=BTC/USDT&timeframe=1H&limit=10",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
```

## 关键规范

### 统一响应格式

```python
# 成功响应
{
    "success": True,
    "data": [...],       # 或 {} 或 null
    "message": "操作成功"  # 可选
}

# 失败响应（用 flask_smorest.abort）
abort(400, message="参数错误：symbol 不能为空")
abort(404, message="策略不存在")
abort(500, message="内部错误")
```

### 认证方式

```python
# 人类用户 API（JWT）
from app.utils.auth import token_required
decorators = [token_required]

# Agent Gateway（Token）
from app.utils.agent_auth import agent_required
decorators = [agent_required(scope="R")]  # R=读, W=写, B=回测
```

## 关键文件

| 文件 | 用途 |
|------|------|
| `app/routes/__init__.py` | 蓝图注册入口 |
| `app/routes/strategies.py` | 完整的 CRUD 路由范例 |
| `app/openapi/schemas/` | Schema 定义目录 |
| `app/utils/auth.py` | JWT 认证 |
| `app/utils/agent_auth.py` | Agent Token 认证 |

## 注意事项

- **必须**在 service 层实现业务逻辑，路由层只做参数解析和响应组装
- **必须**用 flask-smorest Schema，不要用手动 `request.args.get()`
- **不要**在路由中直接操作数据库，通过 service 调用
- 新增 Agent Gateway 端点时，检查是否需要额外的 scope（如 T=交易 默认拒绝）
- 响应中的 `data` 字段统一使用 camelCase 键名（前端兼容）
