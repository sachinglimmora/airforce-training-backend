import urllib.request, urllib.error
import json

data = json.dumps({'email': 'admin@aegis.internal', 'password': 'Aegis@Admin2026!'}).encode()
req = urllib.request.Request('http://localhost:8000/api/v1/auth/login', data=data, headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode())
