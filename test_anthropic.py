import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://coder.holmesai.xyz/v1/messages"
headers = {
    "Content-Type": "application/json",
    "x-api-key": "sk-64svEXTmVSES5vEbaUmpZjLaWZBMgx1GUMYRFcYTYodN",
    "anthropic-version": "2023-06-01",
}
payload = {
    "model": "claude-sonnet-4-20250514",
    "messages": [
        {"role": "user", "content": "say hello"}
    ],
    "max_tokens": 50,
}

print(f"URL: {url}")
print(f"Model: {payload['model']}")

response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
print(f"Status: {response.status_code}")
print(f"Response: {response.text[:800]}")
