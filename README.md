# Cloudflare Logpush - Self-Hosted Log Receiver

A self-hosted, open-source solution for receiving Cloudflare Logpush logs via HTTP destination.

## Stack Components

| Component | Purpose | Port |
|-----------|---------|------|
| **Log Receiver** | HTTP endpoint for Cloudflare Logpush | 8088 |
| **Loki** | Log aggregation & storage | 3100 |
| **Grafana** | Visualization & dashboards | 3000 |

## Quick Start

### 1. Deploy via Portainer

**Option A: Stacks (Recommended)**
1. Go to **Stacks** → **Add Stack**
2. Name: `cloudflare-logpush`
3. **Build method**: Git Repository or upload files
4. Set environment variables:
   - `AUTH_TOKEN`: Your secret token for authentication
   - `GRAFANA_PASSWORD`: Admin password for Grafana
5. Click **Deploy the stack**

**Option B: Command Line**
```bash
cd cloudflare-logpush
cp .env.example .env
# Edit .env with your settings
docker-compose up -d
```

### 2. Configure Cloudflare Logpush

In the Cloudflare Dashboard:

1. Go to **Analytics & Logs** → **Logs** → **Logpush**
2. Click **Create a Logpush job**
3. Select **HTTP destination**
4. Configure the endpoint:
   ```
   https://your-server:8088/logs?header_Authorization=Bearer%20YOUR_AUTH_TOKEN
   ```
   
   Or without auth (not recommended for production):
   ```
   https://your-server:8088/logs
   ```

5. Select your dataset (e.g., `HTTP requests`)
6. Choose fields to include
7. Enable the job

### 3. Access Grafana Dashboard

1. Open `http://your-server:3000`
2. Login with `admin` / `<GRAFANA_PASSWORD>`
3. Navigate to **Dashboards** → **Cloudflare** → **Cloudflare Logs**

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Cloudflare    │     │  Log Receiver   │     │      Loki       │
│    Logpush      │────▶│   (Python)      │────▶│   (Storage)     │
│                 │     │   Port 8088     │     │   Port 3100     │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────┐
                                                │    Grafana      │
                                                │ (Visualization) │
                                                │   Port 3000     │
                                                └─────────────────┘
```

## Cloudflare Logpush Configuration Examples

### Via Cloudflare Dashboard

1. Navigate to your zone → **Analytics & Logs** → **Logs**
2. Select **Add Logpush job**
3. Choose **HTTP destination**
4. Enter destination URL:
   ```
   https://logs.yourdomain.com:8088/logs?header_Authorization=Bearer%20your-token
   ```

### Via Cloudflare API

```bash
# Set your variables
ZONE_ID="your-zone-id"
CF_API_TOKEN="your-cloudflare-api-token"
LOG_ENDPOINT="https://logs.yourdomain.com:8088/logs"
AUTH_TOKEN="your-auth-token"

# Create the job
curl "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/logpush/jobs" \
  --request POST \
  --header "Authorization: Bearer $CF_API_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "my-http-logpush",
    "destination_conf": "'"$LOG_ENDPOINT"'?header_Authorization=Bearer%20'"$AUTH_TOKEN"'",
    "dataset": "http_requests",
    "output_options": {
      "field_names": [
        "ClientIP",
        "ClientRequestHost", 
        "ClientRequestMethod",
        "ClientRequestURI",
        "EdgeEndTimestamp",
        "EdgeResponseBytes",
        "EdgeResponseStatus",
        "EdgeStartTimestamp",
        "RayID",
        "CacheCacheStatus",
        "ClientCountry",
        "ClientDeviceType",
        "SecurityLevel",
        "WAFAction"
      ],
      "timestamp_format": "rfc3339"
    },
    "enabled": true
  }'
```

## HTTPS Setup (Required for Cloudflare)

Cloudflare requires HTTPS endpoints. Options:

### Option 1: Cloudflare Tunnel (Recommended)
```bash
# Install cloudflared and create tunnel
cloudflared tunnel create logpush
cloudflared tunnel route dns logpush logs.yourdomain.com

# Run tunnel
cloudflared tunnel run --url http://localhost:8088 logpush
```

### Option 2: Reverse Proxy with SSL (nginx)
```nginx
server {
    listen 443 ssl;
    server_name logs.yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Option 3: Traefik (if using Portainer)
Add labels to the log-receiver service in docker-compose.yml.

## Testing the Setup

### Test the receiver directly
```bash
# Test health endpoint
curl http://localhost:8088/health

# Send a test log
curl -X POST http://localhost:8088/test

# Simulate Cloudflare log
curl -X POST http://localhost:8088/logs \
  -H "Content-Type: application/json" \
  -d '{"ClientIP":"1.2.3.4","ClientRequestHost":"example.com","ClientRequestMethod":"GET","ClientRequestURI":"/test","EdgeResponseStatus":200,"RayID":"abc123"}'
```

### Check Loki
```bash
# Query Loki directly
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode 'query={job="cloudflare"}'
```

## Grafana Queries (LogQL)

### Request rate
```
sum(rate({job="cloudflare"} [5m]))
```

### Filter by status code
```
{job="cloudflare"} | json | EdgeResponseStatus >= 400
```

### Top requested hosts
```
sum by (ClientRequestHost) (count_over_time({job="cloudflare"} | json [1h]))
```

### Cache hit ratio
```
sum(count_over_time({job="cloudflare"} | json | CacheCacheStatus="hit" [1h])) 
/ 
sum(count_over_time({job="cloudflare"} | json [1h]))
```

## Resource Requirements

| Component | CPU | Memory |
|-----------|-----|--------|
| Log Receiver | 0.5 core | 256MB |
| Loki | 0.5 core | 512MB |
| Grafana | 0.5 core | 256MB |
| **Total** | ~1.5 cores | ~1GB |

## Data Retention

Default retention is 30 days. Modify in `loki/config.yml`:
```yaml
table_manager:
  retention_deletes_enabled: true
  retention_period: 720h  # 30 days
```

## Troubleshooting

### Logs not appearing in Grafana
1. Check log receiver: `docker logs cf-log-receiver`
2. Check Loki: `docker logs loki`
3. Verify Cloudflare job is enabled in dashboard

### Connection refused
- Ensure ports 8088, 3100, 3000 are accessible
- Check firewall rules

### Validation failed in Cloudflare
- Endpoint must be HTTPS
- Must accept gzipped POST requests
- Must return 200 for validation test

