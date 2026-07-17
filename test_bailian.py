import requests
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer sk-2e51106991f94d6198714a8734004071",
}
payload = {
    "model": "qwen-max",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 50,
}

print("URL:", url)
print("Model:", payload["model"])

response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
print("Status:", response.status_code)
print("Response:", response.text)
