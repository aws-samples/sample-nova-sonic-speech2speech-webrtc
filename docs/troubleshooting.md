# Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the Nova Sonic WebRTC Workshop system.

## Quick Diagnosis

### System Health Check
```bash
# Check if services are running
ps aux | grep -E "(python|node)" | grep -v grep

# Check port availability
netstat -tulpn | grep -E "(3000|8765)"

# Check system resources
free -h
df -h
```

## Common Issues and Solutions

### 1. Server Startup Issues

#### Python WebRTC Server Won't Start

**Symptoms:**
- Server exits immediately after startup
- Port binding errors
- Import errors

**Solutions:**

**Port Already in Use:**
```bash
# Find process using port 3000
lsof -i :3000
# Kill the process
kill -9 <PID>
# Or use different port
export WEBRTC_SERVER_PORT=8081
```

**Missing Dependencies:**
```bash
# Reinstall requirements
cd python-webrtc-server
pip install -r requirements.txt --force-reinstall

# For conda users
conda install --file requirements.txt
```

**Environment Variables Missing:**
```bash
# Copy and configure environment file
cp .env.template .env
# Edit .env with your settings
nano .env
```

#### React Client Build/Start Failures

**Symptoms:**
- npm start fails
- Build errors
- Module not found errors

**Solutions:**

**Node Modules Issues:**
```bash
cd react-webrtc-client
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm cache clean --force
npm install
```

**Version Compatibility:**
```bash
# Check Node.js version (requires 14+)
node --version
# Update if needed
nvm install 16
nvm use 16
```

**Memory Issues:**
```bash
# Increase Node.js memory limit
export NODE_OPTIONS="--max-old-space-size=4096"
npm start
```

### 2. WebRTC Connection Issues

#### No Audio/Video Stream

**Symptoms:**
- Connection established but no media
- One-way audio only
- Intermittent audio drops

**Diagnosis Steps:**
```bash
# Check browser console for errors
# Look for these common messages:
# - "getUserMedia failed"
# - "ICE connection failed"
# - "DTLS handshake failed"
```

**Solutions:**

**Browser Permissions:**
1. Ensure microphone/camera permissions are granted
2. Check browser security settings
3. Use HTTPS for production (required for getUserMedia)

**Firewall/Network Issues:**
```bash
# Test STUN server connectivity
curl -v stun:stun.l.google.com:19302

# Check if UDP ports are blocked
# WebRTC typically uses UDP ports 1024-65535
```

**ICE Configuration:**
```javascript
// Add more STUN servers in WebRTC configuration
const iceServers = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
  { urls: 'stun:stun2.l.google.com:19302' }
];
```

#### Connection Timeout

**Symptoms:**
- WebSocket connection fails
- Long connection establishment time
- Frequent disconnections

**Solutions:**

**WebSocket Issues:**
```bash
# WebRTC uses direct peer-to-peer connections, no WebSocket server needed

# Check server logs for connection errors
tail -f python-webrtc-server/logs/server.log
```

**Network Latency:**
```bash
# Test network latency to server
ping your-server-ip
traceroute your-server-ip
```

### 3. Audio Quality Issues

#### Poor Audio Quality

**Symptoms:**
- Choppy or distorted audio
- Echo or feedback
- Low volume levels

**Solutions:**

**Sample Rate Mismatch:**
```python
# Ensure consistent sample rates
AUDIO_SAMPLE_RATE = 48000  # Use 48kHz for best quality
AUDIO_CHANNELS = 1         # Mono for speech
```

**Buffer Size Optimization:**
```python
# Adjust buffer sizes in AudioProcessor
BUFFER_SIZE = 1024  # Smaller for lower latency
FRAME_DURATION = 20  # 20ms frames
```

**Echo Cancellation:**
```javascript
// Enable echo cancellation in browser
const constraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  }
};
```

#### Audio Delay/Latency

**Symptoms:**
- Noticeable delay in conversation
- Audio out of sync

**Solutions:**

**Reduce Processing Latency:**
```python
# Optimize audio processing pipeline
# Use smaller buffer sizes
# Minimize processing steps
# Use hardware acceleration when available
```

**Network Optimization:**
```bash
# Check network conditions
iperf3 -c your-server-ip
# Optimize TCP settings
echo 'net.core.rmem_max = 16777216' >> /etc/sysctl.conf
```

### 4. Performance Issues

#### High CPU Usage

**Symptoms:**
- System becomes slow
- Audio stuttering
- High fan noise

**Diagnosis:**
```bash
# Monitor CPU usage
top -p $(pgrep -f "python.*webrtc")
htop

# Profile Python application
python -m cProfile -o profile.stats webrtc_server.py
```

**Solutions:**

**Optimize Audio Processing:**
```python
# Use numpy for efficient audio processing
import numpy as np

# Vectorized operations instead of loops
audio_data = np.frombuffer(raw_audio, dtype=np.int16)
processed = np.multiply(audio_data, gain_factor)
```

**Reduce Processing Load:**
```python
# Skip unnecessary processing
if not audio_active:
    continue

# Use threading for I/O operations
import threading
threading.Thread(target=process_audio, daemon=True).start()
```

#### Memory Leaks

**Symptoms:**
- Gradually increasing memory usage
- System becomes unresponsive
- Out of memory errors

**Diagnosis:**
```bash
# Monitor memory usage over time
watch -n 1 'ps aux | grep python | grep webrtc'

# Use memory profiler
pip install memory-profiler
python -m memory_profiler webrtc_server.py
```

**Solutions:**

**Proper Resource Cleanup:**
```python
# Always close resources
try:
    # WebRTC operations
    pass
finally:
    if peer_connection:
        peer_connection.close()
    if audio_track:
        audio_track.stop()
```

**Limit Buffer Sizes:**
```python
# Implement circular buffers
from collections import deque
audio_buffer = deque(maxlen=1000)  # Limit buffer size
```

## Log Analysis Guidelines

### Python Server Logs

**Log Locations:**
- Console output: Real-time debugging
- Application logs: `logs/webrtc_server.log`
- Error logs: `logs/error.log`

**Key Log Patterns:**

**Connection Events:**
```
INFO: New WebRTC connection from 192.168.1.100
INFO: ICE connection state: connected
WARNING: ICE connection state: disconnected
ERROR: Failed to establish peer connection
```

**Audio Processing:**
```
DEBUG: Processing audio frame: 1024 samples
INFO: Audio track added to peer connection
WARNING: Audio buffer overflow, dropping frames
ERROR: Audio codec negotiation failed
```

**Performance Metrics:**
```
INFO: Processing latency: 15ms
WARNING: High CPU usage: 85%
ERROR: Memory usage exceeded threshold: 512MB
```

### React Client Logs

**Browser Console Logs:**

**WebRTC Events:**
```javascript
// Connection state changes
console.log('ICE connection state:', event.target.iceConnectionState);

// Media stream events
console.log('Local stream obtained:', stream);
console.log('Remote stream received:', event.streams[0]);
```

**Error Patterns:**
```javascript
// Common error messages to look for:
"NotAllowedError: Permission denied"
"NotFoundError: No audio input device found"
"OverconstrainedError: Audio constraints not satisfied"
"NetworkError: WebSocket connection failed"
```

### Log Analysis Tools

**Real-time Monitoring:**
```bash
# Follow logs in real-time
tail -f logs/webrtc_server.log | grep ERROR

# Filter specific events
grep "connection" logs/webrtc_server.log | tail -20

# Count error occurrences
grep -c "ERROR" logs/webrtc_server.log
```

**Log Parsing Script:**
```python
#!/usr/bin/env python3
import re
from collections import Counter

def analyze_logs(log_file):
    errors = Counter()
    with open(log_file, 'r') as f:
        for line in f:
            if 'ERROR' in line:
                # Extract error type
                match = re.search(r'ERROR: (.+?):', line)
                if match:
                    errors[match.group(1)] += 1
    
    print("Top errors:")
    for error, count in errors.most_common(5):
        print(f"  {error}: {count}")

# Usage: python analyze_logs.py logs/webrtc_server.log
```

## Debugging Tips

### Enable Debug Mode

**Python Server:**
```bash
# Set debug environment variable
export DEBUG=1
export LOG_LEVEL=DEBUG

# Run with verbose logging
python webrtc_server.py --debug --verbose
```

**React Client:**
```bash
# Enable React debug mode
export REACT_APP_DEBUG=true
npm start
```

### WebRTC Debug Information

**Browser DevTools:**
1. Open Chrome DevTools (F12)
2. Go to `chrome://webrtc-internals/`
3. Monitor connection statistics
4. Check ICE candidates and DTLS handshake

**Capture Network Traffic:**
```bash
# Use tcpdump to capture WebRTC traffic (captures all WebRTC traffic)
sudo tcpdump -i any -w webrtc_capture.pcap

# Analyze with Wireshark
wireshark webrtc_capture.pcap
```

### Performance Profiling

**Python Profiling:**
```python
import cProfile
import pstats

# Profile specific function
cProfile.run('process_audio_stream()', 'audio_profile.stats')

# Analyze results
stats = pstats.Stats('audio_profile.stats')
stats.sort_stats('cumulative').print_stats(10)
```

**JavaScript Profiling:**
```javascript
// Browser performance monitoring
console.time('audio-processing');
// ... audio processing code ...
console.timeEnd('audio-processing');

// Memory usage tracking
console.log('Memory usage:', performance.memory);
```

## Performance Optimization

### System-Level Optimizations

**Linux System Tuning:**
```bash
# Increase file descriptor limits
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf

# Optimize network settings
echo 'net.core.rmem_max = 16777216' >> /etc/sysctl.conf
echo 'net.core.wmem_max = 16777216' >> /etc/sysctl.conf
sysctl -p
```

**Process Priority:**
```bash
# Run with higher priority
nice -n -10 python webrtc_server.py

# Set real-time scheduling for audio processing
chrt -f 50 python webrtc_server.py
```

### Application-Level Optimizations

**Audio Processing:**
```python
# Use efficient audio libraries
import soundfile as sf  # Faster than wave
import numpy as np      # Vectorized operations

# Optimize buffer management
class CircularBuffer:
    def __init__(self, size):
        self.buffer = np.zeros(size, dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0
    
    def write(self, data):
        # Efficient circular buffer implementation
        pass
```

**WebRTC Configuration:**
```javascript
// Optimize WebRTC settings
const rtcConfig = {
  iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
  iceCandidatePoolSize: 10,
  bundlePolicy: 'max-bundle',
  rtcpMuxPolicy: 'require'
};
```

**Connection Pooling:**
```python
# Reuse connections when possible
class ConnectionPool:
    def __init__(self, max_connections=10):
        self.pool = []
        self.max_connections = max_connections
    
    def get_connection(self):
        # Return existing or create new connection
        pass
```

### Monitoring and Alerting

**Health Check Endpoint:**
```python
@app.route('/health')
def health_check():
    return {
        'status': 'healthy',
        'connections': len(active_connections),
        'cpu_usage': psutil.cpu_percent(),
        'memory_usage': psutil.virtual_memory().percent
    }
```

**Performance Metrics:**
```python
import time
import psutil

class PerformanceMonitor:
    def __init__(self):
        self.metrics = {}
    
    def record_latency(self, operation, duration):
        if operation not in self.metrics:
            self.metrics[operation] = []
        self.metrics[operation].append(duration)
    
    def get_average_latency(self, operation):
        if operation in self.metrics:
            return sum(self.metrics[operation]) / len(self.metrics[operation])
        return 0
```

## Getting Help

### Community Resources
- GitHub Issues: Report bugs and feature requests
- Documentation: Check the latest documentation
- Stack Overflow: Search for WebRTC-related questions

### Professional Support
- Contact system administrators for infrastructure issues
- Consult WebRTC experts for complex audio/video problems
- Consider professional monitoring solutions for production deployments

### Useful Commands Summary

```bash
# Quick system check
./scripts/check-system-health.sh

# Restart all services
./scripts/restart-services.sh

# View recent logs
./scripts/show-recent-logs.sh

# Performance report
./scripts/generate-performance-report.sh
```

Remember: When reporting issues, always include:
1. System information (OS, versions)
2. Relevant log excerpts
3. Steps to reproduce the problem
4. Expected vs actual behavior