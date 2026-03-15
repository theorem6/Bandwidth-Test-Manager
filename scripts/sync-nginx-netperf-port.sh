#!/bin/bash
# Sync Nginx proxy_pass to the port netperf-web is actually using.
# Run on the server: sudo bash scripts/sync-nginx-netperf-port.sh
# Use after 502 errors or when the app was started on 8081 and Nginx still points to 8080 (or vice versa).

set -e

WEB_PORT="8080"
if [ -f /etc/systemd/system/netperf-web.service ]; then
  _p=$(grep -E 'Environment=PORT=' /etc/systemd/system/netperf-web.service 2>/dev/null | sed -n 's/.*PORT=\([0-9]*\).*/\1/p' | head -1)
  [ -n "$_p" ] && WEB_PORT="$_p"
fi

echo "netperf-web port from systemd: $WEB_PORT"

for f in /etc/nginx/sites-enabled/netperf-web /etc/nginx/sites-available/netperf-web /etc/nginx/snippets/netperf-proxy.conf /etc/nginx/snippets/netperf-path.conf; do
  if [ -f "$f" ]; then
    # Replace any 127.0.0.1:8080 or 127.0.0.1:8081 with the actual port
    sed -i "s/127\.0\.0\.1:8080/127.0.0.1:$WEB_PORT/g" "$f"
    sed -i "s/127\.0\.0\.1:8081/127.0.0.1:$WEB_PORT/g" "$f"
    echo "Updated $f -> port $WEB_PORT"
  fi
done

if command -v nginx &>/dev/null; then
  nginx -t && systemctl reload nginx && echo "Nginx reloaded. Proxy now points to port $WEB_PORT."
else
  echo "Nginx not found; configs updated only."
fi
