#!/bin/bash
# Enable HTTPS for Netperf Web UI using the server's existing certificate.
# Run on the server as root. Uses nginx as reverse proxy; Flask stays on 127.0.0.1:8080.
# Certificate and URL can be set in the web UI (Settings) and stored in /etc/netperf/config.json.
# Usage: sudo ./setup-https.sh [domain]
# Example: sudo ./setup-https.sh hyperionsolutionsgroup.com

set -e

DOMAIN="${1:-}"
CONFIG_JSON="${NETPERF_CONFIG:-/etc/netperf/config.json}"
NGINX_CONF="/etc/nginx/sites-available/netperf-web"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo $0 [domain]"
  exit 1
fi

# Read cert paths and optional domain from config (set in web UI)
SSL_CERT=""
SSL_KEY=""
if [ -f "$CONFIG_JSON" ]; then
  _read_json() {
    local key="$1"
    if command -v jq >/dev/null 2>&1; then
      jq -r ".${key} // \"\"" "$CONFIG_JSON" 2>/dev/null
    else
      python3 -c "import json; d=json.load(open('$CONFIG_JSON')); print(d.get('$key', '') or '')" 2>/dev/null
    fi
  }
  SSL_CERT="$(_read_json ssl_cert_path)"
  SSL_KEY="$(_read_json ssl_key_path)"
  if [ -z "$DOMAIN" ]; then
    SITE_URL="$(_read_json site_url)"
    if [ -n "$SITE_URL" ] && [ "$SITE_URL" != "null" ]; then
      DOMAIN="$(echo "$SITE_URL" | sed -n 's|^https\?://\([^/:]*\).*|\1|p')"
    fi
  fi
fi

# Fallback: detect cert by domain or common paths
if [ -z "$SSL_CERT" ] || [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
  SSL_CERT=""
  SSL_KEY=""
  if [ -n "$DOMAIN" ] && [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    SSL_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    SSL_KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
  fi
fi
if [ -z "$SSL_CERT" ] && [ -f /etc/letsencrypt/live/*/fullchain.pem ]; then
  SSL_CERT="$(ls /etc/letsencrypt/live/*/fullchain.pem 2>/dev/null | head -1)"
  SSL_KEY="$(ls /etc/letsencrypt/live/*/privkey.pem 2>/dev/null | head -1)"
fi
if [ -z "$SSL_CERT" ] && [ -f /etc/ssl/certs/ssl-cert-snakeoil.pem ]; then
  SSL_CERT="/etc/ssl/certs/ssl-cert-snakeoil.pem"
  SSL_KEY="/etc/ssl/private/ssl-cert-snakeoil.key"
fi
if [ -z "$SSL_CERT" ] || [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
  echo "No certificate found. Set site_url and ssl_cert_path/ssl_key_path in the web UI (Settings), or run: sudo $0 DOMAIN"
  echo "  e.g. /etc/letsencrypt/live/DOMAIN/fullchain.pem and privkey.pem"
  exit 1
fi

echo "Using certificate: $SSL_CERT"

# Use port netperf-web is actually listening on (default 8080)
WEB_PORT="8080"
if [ -f /etc/systemd/system/netperf-web.service ]; then
  _p=$(grep -E 'Environment=PORT=' /etc/systemd/system/netperf-web.service 2>/dev/null | sed -n 's/.*PORT=\([0-9]*\).*/\1/p' | head -1)
  [ -n "$_p" ] && WEB_PORT="$_p"
fi
echo "Proxying to netperf-web on port $WEB_PORT"

apt-get install -y nginx 2>/dev/null || true

SERVER_NAME="_"
[ -n "$DOMAIN" ] && SERVER_NAME="$DOMAIN"

cat > "$NGINX_CONF" << EOF
server {
    listen 80;
    listen [::]:80;
    server_name $SERVER_NAME;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $SERVER_NAME;

    ssl_certificate     $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;

    client_max_body_size 1M;

    location /netperf/ {
        proxy_pass http://127.0.0.1:${WEB_PORT}/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Prefix /netperf;
    }
    location = /netperf {
        return 301 \$scheme://\$host/netperf/;
    }
    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Install snippets for inclusion in an existing server block
mkdir -p /etc/nginx/snippets
cat > /etc/nginx/snippets/netperf-proxy.conf << SNIP
location / {
    proxy_pass http://127.0.0.1:${WEB_PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
SNIP
cat > /etc/nginx/snippets/netperf-path.conf << SNIP
location = /netperf {
    return 301 \$scheme://\$host/netperf/;
}
location /netperf/ {
    proxy_pass http://127.0.0.1:${WEB_PORT}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Prefix /netperf;
}
SNIP

# If a server for this domain already exists, our new server block will be ignored (nginx warning).
# Use the snippet in the existing server block instead.
if nginx -t 2>&1 | grep -q "conflicting server name"; then
  echo "A server block for this domain already exists. Add inside that server { } block:"
  echo "  include /etc/nginx/snippets/netperf-proxy.conf;"
  echo "Then: sudo nginx -t && sudo systemctl reload nginx"
  rm -f /etc/nginx/sites-enabled/netperf-web
else
  ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/netperf-web 2>/dev/null || true
fi

nginx -t
systemctl reload nginx

echo "HTTPS ready. Ensure firewall allows 443. Access via https://<this-host>/"
