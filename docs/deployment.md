# Deployment Guide

This guide covers production deployment of the Nova Sonic WebRTC Workshop system, including security considerations, performance optimization, and monitoring setup.

## Table of Contents

1. [Production Environment Setup](#production-environment-setup)
2. [Security Configuration](#security-configuration)
3. [Performance Tuning](#performance-tuning)
4. [Monitoring and Logging](#monitoring-and-logging)
5. [Maintenance Guidelines](#maintenance-guidelines)
6. [Backup and Recovery](#backup-and-recovery)
7. [Scaling Considerations](#scaling-considerations)

## Production Environment Setup

### System Requirements

**Minimum Production Requirements:**
- CPU: 4 cores (8 recommended)
- RAM: 8GB (16GB recommended)
- Storage: 50GB SSD
- Network: 1Gbps connection
- OS: Ubuntu 20.04+ / CentOS 8+ / Amazon Linux 2

**Recommended Production Setup:**
- CPU: 8+ cores
- RAM: 32GB+
- Storage: 100GB+ NVMe SSD
- Network: 10Gbps connection
- Load balancer for high availability

### Pre-deployment Checklist

```bash
# System updates
sudo apt update && sudo apt upgrade -y

# Install required system packages
sudo apt install -y nginx certbot python3-certbot-nginx

# Configure firewall
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP
sudo ufw allow 443/tcp     # HTTPS
sudo ufw allow 8000/tcp    # WebRTC Server
sudo ufw allow 3000/tcp    # React Client (if needed)
sudo ufw enable

# Set system limits
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf
```

### Environment Configuration

Create production environment files:

**python-webrtc-server/.env.prod:**
```bash
# Server Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=false
LOG_LEVEL=INFO

# WebRTC Configuration
STUN_SERVER=stun:stun.l.google.com:19302
TURN_SERVER=turn:your-turn-server.com:3478
TURN_USERNAME=your_username
TURN_PASSWORD=your_password

# AWS Configuration (if using AWS services)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key

# Security
CORS_ORIGINS=https://your-domain.com
API_KEY=your_secure_api_key
JWT_SECRET=your_jwt_secret_key

# Performance
MAX_CONNECTIONS=1000
WORKER_PROCESSES=4
```

**react-webrtc-client/.env.prod:**
```bash
REACT_APP_API_URL=https://api.your-domain.com
REACT_APP_WS_URL=wss://api.your-domain.com
REACT_APP_ENVIRONMENT=production
GENERATE_SOURCEMAP=false
```

## Security Configuration

### SSL/TLS Setup

```bash
# Install SSL certificate using Let's Encrypt
sudo certbot --nginx -d your-domain.com -d api.your-domain.com

# Auto-renewal setup
sudo crontab -e
# Add: 0 12 * * * /usr/bin/certbot renew --quiet
```

### Nginx Configuration

Create `/etc/nginx/sites-available/nova-sonic-webrtc`:

```nginx
# Rate limiting
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=ws:10m rate=5r/s;

# Upstream servers
upstream webrtc_backend {
    least_conn;
    server 127.0.0.1:8000;
    # Add more servers for load balancing
    # server 127.0.0.1:8001;
}

# HTTPS redirect
server {
    listen 80;
    server_name your-domain.com api.your-domain.com;
    return 301 https://$server_name$request_uri;
}

# Main application server
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL configuration
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Serve React application
    root /var/www/nova-sonic-webrtc/build;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}

# API server
server {
    listen 443 ssl http2;
    server_name api.your-domain.com;
    
    # SSL configuration (same as above)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    # Security headers (same as above)
    
    # API endpoints
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        
        proxy_pass http://webrtc_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # WebSocket endpoints
    location /ws/ {
        limit_req zone=ws burst=10 nodelay;
        
        proxy_pass http://webrtc_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket specific timeouts
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
```

### Application Security

**Python Server Security:**
```python
# Add to your server configuration
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'
}

# Input validation
MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB
MAX_CONNECTIONS_PER_IP = 10
CONNECTION_TIMEOUT = 300  # 5 minutes

# Rate limiting per IP
RATE_LIMIT = {
    'requests_per_minute': 60,
    'websocket_connections_per_minute': 10
}
```

## Performance Tuning

### System-Level Optimization

```bash
# Kernel parameters for high-performance networking
echo 'net.core.rmem_max = 134217728' >> /etc/sysctl.conf
echo 'net.core.wmem_max = 134217728' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_rmem = 4096 65536 134217728' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_wmem = 4096 65536 134217728' >> /etc/sysctl.conf
echo 'net.core.netdev_max_backlog = 5000' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_congestion_control = bbr' >> /etc/sysctl.conf

# Apply changes
sudo sysctl -p
```

### Application Performance

**Python Server Optimization:**
```python
# WebRTC server configuration
WEBRTC_CONFIG = {
    'ice_servers': [
        {'urls': 'stun:stun.l.google.com:19302'},
        {
            'urls': 'turn:your-turn-server.com:3478',
            'username': 'your_username',
            'credential': 'your_password'
        }
    ],
    'bundle_policy': 'max-bundle',
    'rtcp_mux_policy': 'require',
    'ice_candidate_pool_size': 10
}

# Audio processing optimization
AUDIO_CONFIG = {
    'sample_rate': 16000,
    'channels': 1,
    'buffer_size': 1024,
    'enable_noise_suppression': True,
    'enable_echo_cancellation': True,
    'enable_auto_gain_control': True
}

# Connection pooling
CONNECTION_POOL = {
    'max_connections': 1000,
    'connection_timeout': 30,
    'keep_alive_timeout': 300,
    'max_idle_connections': 100
}
```

### Database Optimization (if applicable)

```sql
-- Connection pooling
SET max_connections = 200;
SET shared_buffers = '256MB';
SET effective_cache_size = '1GB';
SET work_mem = '4MB';
SET maintenance_work_mem = '64MB';

-- Logging optimization
SET log_min_duration_statement = 1000;  -- Log slow queries
SET log_checkpoints = on;
SET log_connections = on;
SET log_disconnections = on;
```

## Monitoring and Logging

### Application Monitoring

**Health Check Endpoint:**
```python
# Add to your Python server
@app.route('/health')
def health_check():
    return {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0',
        'connections': get_active_connections(),
        'memory_usage': get_memory_usage(),
        'cpu_usage': get_cpu_usage()
    }
```

### Logging Configuration

**Python Server Logging:**
```python
import logging
import logging.handlers

# Production logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            '/var/log/nova-sonic/webrtc-server.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)

# Structured logging for monitoring
import structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
```

### System Monitoring

**Prometheus Configuration:**
```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'nova-sonic-webrtc'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 5s
```

**Grafana Dashboard Metrics:**
- Active WebRTC connections
- Audio processing latency
- Memory and CPU usage
- Network throughput
- Error rates and response times
- Connection success/failure rates

### Log Aggregation

**Filebeat Configuration:**
```yaml
# filebeat.yml
filebeat.inputs:
- type: log
  enabled: true
  paths:
    - /var/log/nova-sonic/*.log
  fields:
    service: nova-sonic-webrtc
  fields_under_root: true

output.elasticsearch:
  hosts: ["localhost:9200"]
  index: "nova-sonic-logs-%{+yyyy.MM.dd}"

setup.template.settings:
  index.number_of_shards: 1
  index.codec: best_compression
```

## Maintenance Guidelines

### Regular Maintenance Tasks

**Daily:**
```bash
#!/bin/bash
# daily-maintenance.sh

# Check disk space
df -h | grep -E "(8[0-9]|9[0-9])%" && echo "WARNING: Disk space critical"

# Check memory usage
free -m | awk 'NR==2{printf "Memory Usage: %s/%sMB (%.2f%%)\n", $3,$2,$3*100/$2 }'

# Check active connections
netstat -an | grep :8000 | wc -l

# Rotate logs if needed
logrotate /etc/logrotate.d/nova-sonic

# Check SSL certificate expiry
openssl x509 -in /etc/letsencrypt/live/your-domain.com/cert.pem -noout -dates
```

**Weekly:**
```bash
#!/bin/bash
# weekly-maintenance.sh

# Update system packages
apt update && apt list --upgradable

# Analyze log files for errors
grep -i error /var/log/nova-sonic/*.log | tail -100

# Check performance metrics
iostat -x 1 5
vmstat 1 5

# Backup configuration files
tar -czf /backup/config-$(date +%Y%m%d).tar.gz /etc/nginx/ /var/www/nova-sonic-webrtc/.env*
```

**Monthly:**
```bash
#!/bin/bash
# monthly-maintenance.sh

# Full system update
apt update && apt upgrade -y

# Clean old log files
find /var/log/nova-sonic/ -name "*.log.*" -mtime +30 -delete

# Analyze performance trends
# Generate monthly performance report

# Security audit
lynis audit system --quick
```

### Performance Monitoring

**Key Performance Indicators (KPIs):**
- Connection establishment time < 2 seconds
- Audio latency < 150ms
- CPU usage < 70% average
- Memory usage < 80%
- Error rate < 1%
- Uptime > 99.9%

**Alerting Thresholds:**
```yaml
# alertmanager.yml
groups:
- name: nova-sonic-alerts
  rules:
  - alert: HighCPUUsage
    expr: cpu_usage > 80
    for: 5m
    annotations:
      summary: "High CPU usage detected"
      
  - alert: HighMemoryUsage
    expr: memory_usage > 85
    for: 5m
    annotations:
      summary: "High memory usage detected"
      
  - alert: ConnectionFailures
    expr: connection_failure_rate > 5
    for: 2m
    annotations:
      summary: "High connection failure rate"
```

## Backup and Recovery

### Backup Strategy

**Configuration Backup:**
```bash
#!/bin/bash
# backup-config.sh

BACKUP_DIR="/backup/nova-sonic"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup application code
tar -czf $BACKUP_DIR/app-$DATE.tar.gz /var/www/nova-sonic-webrtc/

# Backup configuration
tar -czf $BACKUP_DIR/config-$DATE.tar.gz /etc/nginx/ /etc/ssl/

# Backup logs (last 7 days)
find /var/log/nova-sonic/ -mtime -7 -type f -exec tar -czf $BACKUP_DIR/logs-$DATE.tar.gz {} +

# Clean old backups (keep 30 days)
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete
```

### Disaster Recovery

**Recovery Procedures:**

1. **System Recovery:**
```bash
# Restore from backup
cd /backup/nova-sonic
tar -xzf app-latest.tar.gz -C /
tar -xzf config-latest.tar.gz -C /

# Restart services
systemctl restart nginx
systemctl restart nova-sonic-webrtc
```

2. **Database Recovery (if applicable):**
```bash
# Restore database
pg_restore -d nova_sonic backup.sql

# Verify data integrity
psql -d nova_sonic -c "SELECT COUNT(*) FROM sessions;"
```

## Scaling Considerations

### Horizontal Scaling

**Load Balancer Configuration:**
```nginx
upstream webrtc_cluster {
    least_conn;
    server 10.0.1.10:8000 weight=3;
    server 10.0.1.11:8000 weight=3;
    server 10.0.1.12:8000 weight=2;
    
    # Health checks
    keepalive 32;
}
```

**Session Affinity:**
```nginx
# Sticky sessions for WebRTC
upstream webrtc_sticky {
    ip_hash;
    server 10.0.1.10:8000;
    server 10.0.1.11:8000;
    server 10.0.1.12:8000;
}
```

### Vertical Scaling

**Resource Scaling Guidelines:**
- **CPU:** Add 2 cores per 500 concurrent connections
- **Memory:** Add 4GB RAM per 1000 concurrent connections
- **Network:** Ensure 100Mbps per 100 concurrent connections
- **Storage:** Monitor log growth, typically 1GB per day per 1000 users

### Auto-scaling (Cloud Deployment)

**AWS Auto Scaling Configuration:**
```json
{
  "AutoScalingGroupName": "nova-sonic-webrtc-asg",
  "MinSize": 2,
  "MaxSize": 10,
  "DesiredCapacity": 3,
  "TargetGroupARNs": ["arn:aws:elasticloadbalancing:..."],
  "HealthCheckType": "ELB",
  "HealthCheckGracePeriod": 300
}
```

## Security Checklist

- [ ] SSL/TLS certificates installed and auto-renewing
- [ ] Firewall configured with minimal required ports
- [ ] Rate limiting implemented
- [ ] Input validation on all endpoints
- [ ] Security headers configured
- [ ] Regular security updates scheduled
- [ ] Access logs monitored
- [ ] Intrusion detection system configured
- [ ] Backup encryption enabled
- [ ] API keys rotated regularly

## Troubleshooting Production Issues

### Common Issues and Solutions

**High CPU Usage:**
```bash
# Identify CPU-intensive processes
top -p $(pgrep -d',' python)

# Check for memory leaks
valgrind --tool=memcheck --leak-check=full python webrtc_server.py
```

**Connection Issues:**
```bash
# Check network connectivity
netstat -tulpn | grep :8000

# Test WebRTC connectivity
curl -I https://api.your-domain.com/health

# Check SSL certificate
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

**Performance Degradation:**
```bash
# Monitor system resources
iostat -x 1 10
vmstat 1 10
sar -u 1 10

# Check application metrics
curl https://api.your-domain.com/metrics
```

For additional troubleshooting, refer to the [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) guide.

---

**Note:** This deployment guide assumes a Linux-based production environment. Adjust configurations as needed for your specific infrastructure and requirements.