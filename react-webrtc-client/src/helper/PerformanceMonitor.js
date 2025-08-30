/**
 * PerformanceMonitor - Monitors WebRTC performance and resource usage
 * Tracks audio latency, connection quality, and resource consumption
 */

class PerformanceMonitor {
    constructor() {
        this.isMonitoring = false;
        this.monitoringInterval = null;
        this.metricsHistory = [];
        this.maxHistorySize = 1000; // Keep last 1000 measurements
        
        // Performance metrics
        this.metrics = {
            // Audio metrics
            audioLatency: 0,
            audioPacketsLost: 0,
            audioJitter: 0,
            audioLevel: 0,
            
            // Connection metrics
            connectionState: 'disconnected',
            iceConnectionState: 'new',
            bytesReceived: 0,
            bytesSent: 0,
            packetsReceived: 0,
            packetsSent: 0,
            
            // Resource metrics
            cpuUsage: 0,
            memoryUsage: 0,
            
            // Timing metrics
            connectionTime: 0,
            firstAudioTime: 0,
            
            // Error metrics
            connectionErrors: 0,
            audioErrors: 0,
            dataChannelErrors: 0
        };
        
        // Baseline measurements for comparison
        this.baseline = null;
        
        // Performance thresholds
        this.thresholds = {
            audioLatency: 200, // ms
            audioJitter: 50,   // ms
            packetLoss: 5,     // %
            cpuUsage: 80,      // %
            memoryUsage: 500   // MB
        };
        
        // Callbacks
        this.onMetricsUpdate = null;
        this.onThresholdExceeded = null;
        
        // Connection timing
        this.connectionStartTime = null;
        this.firstAudioReceived = false;
        this.firstAudioTime = null;
    }

    /**
     * Start performance monitoring
     * @param {RTCPeerConnection} peerConnection - WebRTC peer connection
     * @param {Object} options - Monitoring options
     */
    startMonitoring(peerConnection, options = {}) {
        if (this.isMonitoring) {
            console.warn('[PerformanceMonitor] Already monitoring');
            return;
        }

        this.peerConnection = peerConnection;
        this.isMonitoring = true;
        this.connectionStartTime = Date.now();
        
        const interval = options.interval || 1000; // Default 1 second
        
        console.log(`[PerformanceMonitor] Starting performance monitoring with interval ${interval}ms`);
        
        this.monitoringInterval = setInterval(() => {
            this.collectMetrics();
        }, interval);
        
        console.log(`[PerformanceMonitor] Monitoring interval created: ${this.monitoringInterval}`);
        
        // Set up connection state monitoring
        this.setupConnectionMonitoring();
    }

    /**
     * Stop performance monitoring
     */
    stopMonitoring() {
        if (!this.isMonitoring) {
            console.log('[PerformanceMonitor] Already stopped, ignoring stopMonitoring call');
            return;
        }

        console.log('[PerformanceMonitor] Stopping performance monitoring');
        
        this.isMonitoring = false;
        
        if (this.monitoringInterval) {
            console.log('[PerformanceMonitor] Clearing monitoring interval');
            clearInterval(this.monitoringInterval);
            this.monitoringInterval = null;
        } else {
            console.log('[PerformanceMonitor] No monitoring interval to clear');
        }
        
        this.peerConnection = null;
        console.log('[PerformanceMonitor] Performance monitoring stopped successfully');
    }

    /**
     * Set up connection state monitoring
     */
    setupConnectionMonitoring() {
        if (!this.peerConnection) return;

        // Monitor connection state changes
        const originalOnConnectionStateChange = this.peerConnection.onconnectionstatechange;
        this.peerConnection.onconnectionstatechange = () => {
            this.metrics.connectionState = this.peerConnection.connectionState;
            
            if (this.peerConnection.connectionState === 'connected' && this.connectionStartTime) {
                this.metrics.connectionTime = Date.now() - this.connectionStartTime;
            }
            
            if (originalOnConnectionStateChange) {
                originalOnConnectionStateChange();
            }
        };

        // Monitor ICE connection state
        const originalOnIceConnectionStateChange = this.peerConnection.oniceconnectionstatechange;
        this.peerConnection.oniceconnectionstatechange = () => {
            this.metrics.iceConnectionState = this.peerConnection.iceConnectionState;
            
            if (originalOnIceConnectionStateChange) {
                originalOnIceConnectionStateChange();
            }
        };
    }

    /**
     * Collect performance metrics
     */
    async collectMetrics() {
        if (!this.peerConnection || !this.isMonitoring) {
            return;
        }

        try {
            // Get WebRTC statistics
            const stats = await this.peerConnection.getStats();
            this.processWebRTCStats(stats);
            
            // Get system resource usage
            await this.collectResourceMetrics();
            
            // Calculate derived metrics
            this.calculateDerivedMetrics();
            
            // Store metrics in history
            this.storeMetrics();
            
            // Check thresholds
            this.checkThresholds();
            
            // Notify listeners
            if (this.onMetricsUpdate) {
                this.onMetricsUpdate(this.getMetricsSummary());
            }
            
        } catch (error) {
            console.error('[PerformanceMonitor] Error collecting metrics:', error);
        }
    }

    /**
     * Process WebRTC statistics
     * @param {RTCStatsReport} stats - WebRTC stats report
     */
    processWebRTCStats(stats) {
        let audioInboundStats = null;
        let audioOutboundStats = null;
        let candidatePairStats = null;

        // Find relevant stats
        stats.forEach(stat => {
            if (stat.type === 'inbound-rtp' && stat.kind === 'audio') {
                audioInboundStats = stat;
            } else if (stat.type === 'outbound-rtp' && stat.kind === 'audio') {
                audioOutboundStats = stat;
            } else if (stat.type === 'candidate-pair' && stat.state === 'succeeded') {
                candidatePairStats = stat;
            }
        });

        // Process audio inbound stats
        if (audioInboundStats) {
            this.metrics.packetsReceived = audioInboundStats.packetsReceived || 0;
            this.metrics.bytesReceived = audioInboundStats.bytesReceived || 0;
            this.metrics.audioPacketsLost = audioInboundStats.packetsLost || 0;
            this.metrics.audioJitter = (audioInboundStats.jitter || 0) * 1000; // Convert to ms
            
            // Track first audio received
            if (!this.firstAudioReceived && this.metrics.packetsReceived > 0) {
                this.firstAudioReceived = true;
                this.firstAudioTime = Date.now();
                if (this.connectionStartTime) {
                    this.metrics.firstAudioTime = this.firstAudioTime - this.connectionStartTime;
                }
            }
        }

        // Process audio outbound stats
        if (audioOutboundStats) {
            this.metrics.packetsSent = audioOutboundStats.packetsSent || 0;
            this.metrics.bytesSent = audioOutboundStats.bytesSent || 0;
        }

        // Process candidate pair stats for RTT
        if (candidatePairStats) {
            this.metrics.audioLatency = candidatePairStats.currentRoundTripTime * 1000 || 0; // Convert to ms
        }
    }

    /**
     * Collect system resource metrics
     */
    async collectResourceMetrics() {
        try {
            // Memory usage (if available)
            if (performance.memory) {
                this.metrics.memoryUsage = Math.round(performance.memory.usedJSHeapSize / 1024 / 1024); // MB
            }

            // CPU usage estimation (simplified)
            // Note: Actual CPU usage is not directly available in browsers
            // This is a rough estimation based on timing
            const startTime = performance.now();
            await new Promise(resolve => setTimeout(resolve, 0));
            const endTime = performance.now();
            
            // Very rough CPU usage estimation
            const timingDelta = endTime - startTime;
            this.metrics.cpuUsage = Math.min(100, Math.max(0, timingDelta * 10));
            
        } catch (error) {
            console.error('[PerformanceMonitor] Error collecting resource metrics:', error);
        }
    }

    /**
     * Calculate derived metrics
     */
    calculateDerivedMetrics() {
        // Calculate packet loss percentage
        const totalPackets = this.metrics.packetsReceived + this.metrics.audioPacketsLost;
        if (totalPackets > 0) {
            this.metrics.packetLossPercentage = (this.metrics.audioPacketsLost / totalPackets) * 100;
        } else {
            this.metrics.packetLossPercentage = 0;
        }
        
        // Add timestamp
        this.metrics.timestamp = Date.now();
    }

    /**
     * Store metrics in history
     */
    storeMetrics() {
        const metricsSnapshot = { ...this.metrics };
        this.metricsHistory.push(metricsSnapshot);
        
        // Limit history size
        if (this.metricsHistory.length > this.maxHistorySize) {
            this.metricsHistory.shift();
        }
    }

    /**
     * Check performance thresholds
     */
    checkThresholds() {
        const violations = [];
        
        if (this.metrics.audioLatency > this.thresholds.audioLatency) {
            violations.push({
                metric: 'audioLatency',
                value: this.metrics.audioLatency,
                threshold: this.thresholds.audioLatency,
                severity: 'warning'
            });
        }
        
        if (this.metrics.audioJitter > this.thresholds.audioJitter) {
            violations.push({
                metric: 'audioJitter',
                value: this.metrics.audioJitter,
                threshold: this.thresholds.audioJitter,
                severity: 'warning'
            });
        }
        
        if (this.metrics.packetLossPercentage > this.thresholds.packetLoss) {
            violations.push({
                metric: 'packetLoss',
                value: this.metrics.packetLossPercentage,
                threshold: this.thresholds.packetLoss,
                severity: 'error'
            });
        }
        
        if (this.metrics.cpuUsage > this.thresholds.cpuUsage) {
            violations.push({
                metric: 'cpuUsage',
                value: this.metrics.cpuUsage,
                threshold: this.thresholds.cpuUsage,
                severity: 'warning'
            });
        }
        
        if (this.metrics.memoryUsage > this.thresholds.memoryUsage) {
            violations.push({
                metric: 'memoryUsage',
                value: this.metrics.memoryUsage,
                threshold: this.thresholds.memoryUsage,
                severity: 'warning'
            });
        }
        
        if (violations.length > 0 && this.onThresholdExceeded) {
            this.onThresholdExceeded(violations);
        }
    }

    /**
     * Set baseline measurements for comparison
     */
    setBaseline() {
        this.baseline = { ...this.metrics };
        console.log('[PerformanceMonitor] Baseline set:', this.baseline);
    }

    /**
     * Compare current metrics with baseline
     * @returns {Object} Comparison results
     */
    compareWithBaseline() {
        if (!this.baseline) {
            return null;
        }

        const comparison = {};
        
        Object.keys(this.metrics).forEach(key => {
            if (typeof this.metrics[key] === 'number' && typeof this.baseline[key] === 'number') {
                const current = this.metrics[key];
                const baseline = this.baseline[key];
                const difference = current - baseline;
                const percentChange = baseline !== 0 ? (difference / baseline) * 100 : 0;
                
                comparison[key] = {
                    current,
                    baseline,
                    difference,
                    percentChange: Math.round(percentChange * 100) / 100
                };
            }
        });
        
        return comparison;
    }

    /**
     * Get metrics summary
     * @returns {Object} Metrics summary
     */
    getMetricsSummary() {
        return {
            current: { ...this.metrics },
            baseline: this.baseline ? { ...this.baseline } : null,
            comparison: this.compareWithBaseline(),
            history: this.metricsHistory.slice(-10), // Last 10 measurements
            isMonitoring: this.isMonitoring
        };
    }

    /**
     * Get performance report
     * @returns {Object} Detailed performance report
     */
    getPerformanceReport() {
        const summary = this.getMetricsSummary();
        
        // Calculate averages over last 30 seconds
        const recentMetrics = this.metricsHistory.filter(
            m => Date.now() - m.timestamp < 30000
        );
        
        const averages = {};
        if (recentMetrics.length > 0) {
            Object.keys(this.metrics).forEach(key => {
                if (typeof this.metrics[key] === 'number') {
                    const values = recentMetrics.map(m => m[key]).filter(v => typeof v === 'number');
                    if (values.length > 0) {
                        averages[key] = values.reduce((sum, val) => sum + val, 0) / values.length;
                    }
                }
            });
        }
        
        return {
            ...summary,
            averages,
            recommendations: this.getRecommendations(),
            healthScore: this.calculateHealthScore()
        };
    }

    /**
     * Calculate overall health score (0-100)
     * @returns {number} Health score
     */
    calculateHealthScore() {
        let score = 100;
        
        // Deduct points for threshold violations
        if (this.metrics.audioLatency > this.thresholds.audioLatency) {
            score -= 20;
        }
        
        if (this.metrics.packetLossPercentage > this.thresholds.packetLoss) {
            score -= 30;
        }
        
        if (this.metrics.audioJitter > this.thresholds.audioJitter) {
            score -= 15;
        }
        
        if (this.metrics.cpuUsage > this.thresholds.cpuUsage) {
            score -= 10;
        }
        
        if (this.metrics.memoryUsage > this.thresholds.memoryUsage) {
            score -= 10;
        }
        
        // Connection state penalties
        if (this.metrics.connectionState !== 'connected') {
            score -= 50;
        }
        
        return Math.max(0, Math.min(100, score));
    }

    /**
     * Get performance recommendations
     * @returns {Array} Array of recommendation objects
     */
    getRecommendations() {
        const recommendations = [];
        
        if (this.metrics.audioLatency > this.thresholds.audioLatency) {
            recommendations.push({
                type: 'latency',
                severity: 'warning',
                message: 'High audio latency detected. Consider checking network conditions.',
                action: 'Check network connection and consider using a wired connection.'
            });
        }
        
        if (this.metrics.packetLossPercentage > this.thresholds.packetLoss) {
            recommendations.push({
                type: 'packet_loss',
                severity: 'error',
                message: 'Significant packet loss detected. Audio quality may be affected.',
                action: 'Check network stability and bandwidth availability.'
            });
        }
        
        if (this.metrics.audioJitter > this.thresholds.audioJitter) {
            recommendations.push({
                type: 'jitter',
                severity: 'warning',
                message: 'High audio jitter detected. May cause audio quality issues.',
                action: 'Ensure stable network connection and close bandwidth-intensive applications.'
            });
        }
        
        if (this.metrics.cpuUsage > this.thresholds.cpuUsage) {
            recommendations.push({
                type: 'cpu',
                severity: 'warning',
                message: 'High CPU usage detected. May affect performance.',
                action: 'Close unnecessary applications and browser tabs.'
            });
        }
        
        if (this.metrics.memoryUsage > this.thresholds.memoryUsage) {
            recommendations.push({
                type: 'memory',
                severity: 'warning',
                message: 'High memory usage detected.',
                action: 'Close unnecessary browser tabs and applications.'
            });
        }
        
        return recommendations;
    }

    /**
     * Export metrics data for analysis
     * @returns {Object} Exportable metrics data
     */
    exportMetrics() {
        return {
            summary: this.getMetricsSummary(),
            fullHistory: this.metricsHistory,
            thresholds: this.thresholds,
            exportTime: new Date().toISOString()
        };
    }

    /**
     * Set custom thresholds
     * @param {Object} newThresholds - New threshold values
     */
    setThresholds(newThresholds) {
        this.thresholds = { ...this.thresholds, ...newThresholds };
        console.log('[PerformanceMonitor] Updated thresholds:', this.thresholds);
    }

    /**
     * Record audio level for monitoring
     * @param {number} level - Audio level (0-100)
     */
    recordAudioLevel(level) {
        this.metrics.audioLevel = level;
    }

    /**
     * Record error for tracking
     * @param {string} errorType - Type of error
     */
    recordError(errorType) {
        switch (errorType) {
            case 'connection':
                this.metrics.connectionErrors++;
                break;
            case 'audio':
                this.metrics.audioErrors++;
                break;
            case 'datachannel':
                this.metrics.dataChannelErrors++;
                break;
            default:
                console.warn(`Unknown error type: ${errorType}`);
                break;
        }
    }
}

export default PerformanceMonitor;