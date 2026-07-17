import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === 测试阿里云百炼 (DashScope) API ===
url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer sk-2e51106991f94d6198714a8734004071",
}
payload = {
    "model": "qwen3.7-max-2026-05-20",
    "messages": [
        {"role": "user", "content": "你好，请用一句话介绍你自己。"}
    ],
    "max_tokens": 256,
}

print(f"请求地址: {url}")
print(f"模型: {payload['model']}")
print("---")

try:
    response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
    print(f"HTTP {response.status_code}")
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    print(f"回复: {text}")
    usage = data.get("usage", {})
    print(f"\nToken 用量: prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')}, total={usage.get('total_tokens')}")
    print("\n✅ 百炼 API Key 有效!")
except requests.exceptions.Timeout:
    print("❌ 请求超时 (30s)")
except requests.exceptions.HTTPError as e:
    print(f"❌ HTTP 错误: {e}")
    print(f"响应体: {e.response.text}")
except Exception as e:
    print(f"❌ 错误: {e}")