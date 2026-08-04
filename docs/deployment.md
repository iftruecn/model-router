# Deployment Guide

Production deployment options for Model Router.

---

## Quick Start (Docker Compose)

One command:

```bash
docker compose up -d
```

Then visit:
- API: http://localhost:6060/docs
- Dashboard: http://localhost:6060/dashboard
- Health: http://localhost:6060/health

### Configuration

Mount your `config.yaml` into the container:

```yaml
# docker-compose.yml
services:
  model-router:
    image: model-router:latest
    ports:
      - "6060:6060"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/data
    environment:
      - MODEL_ROUTER_DATA_DIR=/data
    restart: unless-stopped
```

---

## Nginx Reverse Proxy

Terminate TLS and route traffic:

```nginx
upstream model_router {
    server 127.0.0.1:6060;
}

server {
    listen 443 ssl http2;
    server_name router.example.com;

    ssl_certificate     /etc/letsencrypt/live/router.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/router.example.com/privkey.pem;

    location / {
        proxy_pass http://model_router;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support (streaming)
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}

server {
    listen 80;
    server_name router.example.com;
    return 301 https://$host$request_uri;
}
```

---

## systemd Service

```ini
# /etc/systemd/system/model-router.service
[Unit]
Description=Model Router — MOA Middleware
After=network.target

[Service]
Type=simple
User=modelrouter
WorkingDirectory=/opt/model-router
ExecStart=/opt/model-router/venv/bin/model-router serve
Restart=on-failure
RestartSec=5
Environment=MODEL_ROUTER_HOST=127.0.0.1
Environment=MODEL_ROUTER_PORT=6060
Environment=MODEL_ROUTER_DATA_DIR=/opt/model-router/data
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/model-router/data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now model-router
```

---

## Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: model-router
spec:
  replicas: 1
  selector:
    matchLabels:
      app: model-router
  template:
    metadata:
      labels:
        app: model-router
    spec:
      containers:
        - name: model-router
          image: model-router:latest
          ports:
            - containerPort: 6060
          env:
            - name: MODEL_ROUTER_DATA_DIR
              value: /data
          livenessProbe:
            httpGet:
              path: /health
              port: 6060
            initialDelaySeconds: 10
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: model-router
spec:
  selector:
    app: model-router
  ports:
    - port: 6060
      targetPort: 6060
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_ROUTER_HOST` | `127.0.0.1` | Bind host (`0.0.0.0` in containers) |
| `MODEL_ROUTER_PORT` | `6060` | Bind port |
| `MODEL_ROUTER_DATA_DIR` | `data` | Persistent data directory |
| `MODEL_ROUTER_MASTER_KEY` | — | Master API key for auth |
| `MODEL_ROUTER_AUTH_DISABLED` | — | Set `1` to disable auth |

---

## Health Check

```bash
curl http://localhost:6060/health
```

---

## Security Checklist

- [ ] Set `MODEL_ROUTER_MASTER_KEY` for API authentication
- [ ] Use HTTPS (nginx/caddy/traefik TLS termination)
- [ ] Restrict `/admin/*` endpoints to internal network
- [ ] Mount `config.yaml` as read-only
- [ ] Use non-root user in container
- [ ] Enable `ProtectSystem=strict` in systemd
- [ ] Regular backups of `data/` directory
