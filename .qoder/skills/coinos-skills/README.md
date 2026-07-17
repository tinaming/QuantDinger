# CoinOS Skills for Qoder

基于 [AiCoin Open API v3](https://www.aicoin.com/opendata) 的加密货币 AI 技能集，已适配为 Qoder 原生插件。

## 包含技能

| 技能 | 用途 |
|------|------|
| `aicoin-market` | 加密行情数据：价格、K线、资金费率、多空比、持仓量、清算、新闻、空投、国库持仓等 |
| `aicoin-account` | 交易所账户管理：余额、持仓、订单历史、注册、API key 配置 |
| `aicoin-trading` | CEX 交易所下单：Binance/OKX/Bybit/Bitget 现货+合约，含止盈止损 |
| `aicoin-freqtrade` | Freqtrade 策略创建、回测、Hyperopt、部署、实时控制 |
| `aicoin-hyperliquid` | Hyperliquid 鲸鱼追踪、聪明钱分析、链上永续合约数据 |
| `aicoin-onchain` | 链上 DEX 操作：OKX Web3 swap、钱包余额、gas 估算、代币发现 |

## 环境配置

### AiCoin Open API（行情数据）

可选，不填则使用内置免费 key（有速率限制）：

```
AICOIN_ACCESS_KEY_ID=your-key-id
AICOIN_ACCESS_SECRET=your-secret
```

获取地址：https://www.aicoin.com/opendata

### 交易所 API（交易功能）

按需配置对应交易所的 key：

```
OKX_API_KEY=xxx
OKX_API_SECRET=xxx
OKX_PASSWORD=passphrase

BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
```

### OKX Web3 API（链上功能）

免费申请：https://web3.okx.com/onchain-os/dev-portal

```
OKX_WEB3_API_KEY=xxx
OKX_WEB3_SECRET_KEY=xxx
OKX_WEB3_PASSPHRASE=xxx
```

## 来源

- **原始仓库**: https://github.com/aicoincom/coinos-skills
- **许可证**: MIT
- **版本**: 2.0.0
