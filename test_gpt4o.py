import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://coder.holmesai.xyz/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer sk-64svEXTmVSES5vEbaUmpZjLaWZBMgx1GUMYRFcYTYodN",
}
payload = {
    "model": "gpt-4o",
    "messages": [
        {"role": "user", "content": "say hello in one sentence"}
    ],
    "max_tokens": 50,
}

print(f"URL: {url}")
print(f"Model: {payload['model']}")

response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
print(f"Status: {response.status_code}")
print(f"Response: {response.text[:500]}")
