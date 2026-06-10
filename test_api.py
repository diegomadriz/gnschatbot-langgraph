import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("GNS_API_BASE_URL")
user = os.getenv("GNS_API_USER")
password = os.getenv("GNS_API_PASSWORD")

url = f"{base_url}/tickets/"

response = requests.get(
    url,
    auth=HTTPBasicAuth(user, password),
    timeout=15
)

print("HTTP Status:", response.status_code)

if response.status_code == 200:
    data = response.json()
    print("Tickets recibidos:", len(data))
    print("Primer ticket:")
    print(data[0])
else:
    print(response.text)
