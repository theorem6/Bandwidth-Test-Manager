#!/usr/bin/env python3
"""Insert /netperf/ location blocks into netperf-web nginx config."""
import sys
path = "/etc/nginx/sites-available/netperf-web"
insert = r"""
    location /netperf/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Prefix /netperf;
    }
    location = /netperf {
        return 301 $scheme://$host/netperf/;
    }
"""
with open(path) as f:
    content = f.read()
if "location /netperf/" in content:
    print("Already patched")
    sys.exit(0)
# Insert before "    location / {"
old = "    location / {\n        proxy_pass http://127.0.0.1:8080;"
if old not in content:
    print("Config format unexpected")
    sys.exit(1)
new = insert + "\n    location / {\n        proxy_pass http://127.0.0.1:8080;"
content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
print("Patched")
