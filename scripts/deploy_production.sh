#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# AskforWrite AI Company OS — Production Server Setup Script
# ══════════════════════════════════════════════════════════════════════
# Run on your Ubuntu/Debian production server:
#   curl -sSL <raw-github-url>/scripts/deploy_production.sh | bash
# ══════════════════════════════════════════════════════════════════════

set -euo pipefail

DOMAIN="${1:-api.askforwrite.in}"
APP_PORT="${2:-8000}"
REPO_URL="https://github.com/VipulChobisa-AIOps/askforwrite-ai-company-os.git"
INSTALL_DIR="/opt/askforwrite-company-os"

echo "══════════════════════════════════════════════════════════════"
echo "  AskforWrite AI Company OS — Production Deployment"
echo "  Domain: $DOMAIN"
echo "══════════════════════════════════════════════════════════════"

# ── Step 1: System Dependencies ─────────────────────────────────────
echo ""
echo "── Step 1: Installing system dependencies ──"
sudo apt-get update -y
sudo apt-get install -y \
    docker.io docker-compose-plugin \
    nginx certbot python3-certbot-nginx \
    git curl ufw

# ── Step 2: Firewall ────────────────────────────────────────────────
echo ""
echo "── Step 2: Configuring firewall ──"
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
echo "  [OK] Firewall: SSH + HTTP + HTTPS allowed"

# ── Step 3: Clone Repository ────────────────────────────────────────
echo ""
echo "── Step 3: Cloning repository ──"
if [ -d "$INSTALL_DIR" ]; then
    echo "  [INFO] Directory exists, pulling latest..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    sudo chown -R $USER:$USER "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo "  [OK] Repository ready at $INSTALL_DIR"

# ── Step 4: Environment Configuration ───────────────────────────────
echo ""
echo "── Step 4: Setting up environment ──"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.production.example" "$INSTALL_DIR/.env"
    echo "  [WARN] Created .env from template — FILL IN ALL REQUIRED VALUES!"
    echo "  [WARN] Edit: sudo nano $INSTALL_DIR/.env"
    echo ""
    echo "  REQUIRED secrets to fill in:"
    echo "    - POSTGRES_PASSWORD"
    echo "    - DATABASE_URL (update password)"
    echo "    - MANAGER_API_KEY"
    echo "    - OWNER_API_KEY"
    echo "    - RAZORPAY_KEY_ID & RAZORPAY_KEY_SECRET"
    echo "    - PAYPAL_CLIENT_ID & PAYPAL_CLIENT_SECRET"
    echo "    - SMTP_USERNAME & SMTP_PASSWORD"
    echo "    - GOOGLE_API_KEY"
    echo ""
    read -p "  Press Enter after editing .env to continue..."
else
    echo "  [OK] .env already exists"
fi

# ── Step 5: Nginx Reverse Proxy ─────────────────────────────────────
echo ""
echo "── Step 5: Configuring Nginx reverse proxy ──"
sudo tee /etc/nginx/sites-available/company-os > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Webhook endpoints need larger payload support
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket support (for live console if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check (no auth required)
    location /health {
        proxy_pass http://127.0.0.1:$APP_PORT/health;
        proxy_set_header Host \$host;
        access_log off;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/company-os /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
echo "  [OK] Nginx configured for $DOMAIN"

# ── Step 6: SSL Certificate ─────────────────────────────────────────
echo ""
echo "── Step 6: Obtaining SSL certificate ──"
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@askforwrite.in
echo "  [OK] HTTPS enabled for $DOMAIN"

# ── Step 7: Start Docker Compose ────────────────────────────────────
echo ""
echo "── Step 7: Starting Docker Compose ──"
cd "$INSTALL_DIR"
sudo docker compose -f docker-compose.prod.yml up -d --build
echo "  [OK] Docker containers starting..."

# Wait for health check
echo "  [INFO] Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:$APP_PORT/health" > /dev/null 2>&1; then
        echo "  [OK] Health check passed!"
        break
    fi
    sleep 2
done

# ── Step 8: Verify ──────────────────────────────────────────────────
echo ""
echo "── Step 8: Verification ──"
echo ""

HEALTH=$(curl -sf "https://$DOMAIN/health" 2>/dev/null || echo "FAILED")
echo "  Health: $HEALTH"

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  ✅ DEPLOYMENT COMPLETE"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "  API:     https://$DOMAIN"
echo "  Swagger: https://$DOMAIN/docs"
echo "  Health:  https://$DOMAIN/health"
echo ""
echo "  NEXT STEPS:"
echo "  1. Register webhook URLs in payment provider dashboards:"
echo "     Razorpay: https://$DOMAIN/v1/webhooks/razorpay"
echo "     PayPal:   https://$DOMAIN/v1/webhooks/paypal"
echo ""
echo "  2. Verify capabilities:"
echo "     curl -H 'X-API-Key: <MANAGER_KEY>' https://$DOMAIN/v1/capabilities"
echo ""
echo "  3. Auto-renew SSL (certbot timer should be active):"
echo "     sudo systemctl status certbot.timer"
echo ""
