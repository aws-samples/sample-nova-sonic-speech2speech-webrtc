/**
 * PerformanceOptimizer - Implements WebRTC performance optimizations
 * Handles audio codec optimization, connection tuning, and resource management
 */

import PerformanceMonitor from './PerformanceMonitor.js';
import ConnectionPool from './ConnectionPool.js';

class PerformanceOptimizer {
    constructor() {
        this.performanceMonitor = new PerformanceMonitor();
        this.connectionPool = new ConnectionPool();
        
        // Optimization settings
        this.optimizations = {
            audioCodecPreference: ['PCMU', 'PCMA', 'opus'],
            audioBitrate: 64000, // 64 kbps
            audioSampleRate: 16000, // 16 kHz for Nova Sonic
            enableEchoCancellation: true,
            enableNoiseSuppression: true,
            enableAutoGainControl: false, // Disabled to prevent severe clipping
            
            // Connection optimizations
            iceTransportPolicy: 'all',
            bundlePolicy: 'max-bundle',
            rtcpMuxPolicy: 'require',
            
            // Buffer optimizations
            audioBufferSize: 4096,
            maxBufferSize: 8192,
            
            // Performance thresholds
            latencyThreshold: 150, // ms
            jitterThreshold: 30,   // ms
            packetLossThreshold: 3, // %
            
            // Resource limits
            maxConcurrentConnections: 3,
            memoryThreshold: 200 * 1024 * 1024, // 200MB
            cpuThreshold: 70 // %
        };
        
        // Adaptive optimization state
        this.adaptiveState = {
            currentCodec: 'PCMU',
            currentBitrate: 64000,
            currentBufferSize: 4096,
            optimizationLevel: 'balanced', // 'performance', 'balanced', 'quality'
            lastOptimization: Date.now()
        };
        
        // Performance history for adaptive optimization
        this.performanceHistory = [];
        this.maxHistorySize = 100;
        
        // Callbacks
        this.onOptimizationApplied = null;
        this.onPerformanceImproved = null;
        this.onPerformanceDegraded = null;
        
        this.isOptimizing = false;
    }

    /**
     * Initialize performance optimization
     * @param {Object} options - Optimization options
     */
    async initialize(options = {}) {
        console.log('[PerformanceOptimizer] Initializing performance optimization');
        
        // Update optimization settings
        this.optimizations = { ...this.optimizations, ...options };
        
        // Start connection pool
        this.connectionPool.start();
        
        // Set up connection pool callbacks
        this.connectionPool.onResourceThresholdExceeded = (violation) => {
            this.handleResourceViolation(violation);
        };
        
        console.log('[PerformanceOptimizer] Performance optimization initialized');
    }

    /**
     * Optimize WebRTC peer connection configuration
     * @param {Object} baseConfig - Base peer connection configuration
     * @returns {Object} Optimized configuration
     */
    optimizePeerConnectionConfig(baseConfig = {}) {
        const optimizedConfig = {
            ...baseConfig,
            iceTransportPolicy: this.optimizations.iceTransportPolicy,
            bundlePolicy: this.optimizations.bundlePolicy,
            rtcpMuxPolicy: this.optimizations.rtcpMuxPolicy
        };
        
        // Optimize ICE servers if provided
        if (optimizedConfig.iceServers) {
            optimizedConfig.iceServers = this.optimizeIceServers(optimizedConfig.iceServers);
        }
        
        console.log('[PerformanceOptimizer] Optimized peer connection config:', optimizedConfig);
        return optimizedConfig;
    }

    /**
     * Optimize ICE servers configuration
     * @param {Array} iceServers - Original ICE servers
     * @returns {Array} Optimized ICE servers
     */
    optimizeIceServers(iceServers) {
        // Prioritize STUN servers and optimize TURN server usage
        const optimized = [...iceServers];
        
        // Sort to prioritize STUN servers (lower latency)
        optimized.sort((a, b) => {
            const aIsStun = a.urls.some(url => url.startsWith('stun:'));
            const bIsStun = b.urls.some(url => url.startsWith('stun:'));
            
            if (aIsStun && !bIsStun) return -1;
            if (!aIsStun && bIsStun) return 1;
            return 0;
        });
        
        return optimized;
    }

    /**
     * Optimize audio constraints for getUserMedia
     * @param {Object} baseConstraints - Base audio constraints
     * @returns {Object} Optimized audio constraints
     */
    optimizeAudioConstraints(baseConstraints = {}) {
        const optimized = {
            ...baseConstraints,
            echoCancellation: this.optimizations.enableEchoCancellation,
            noiseSuppression: this.optimizations.enableNoiseSuppression,
            autoGainControl: this.optimizations.enableAutoGainControl,
            sampleRate: this.optimizations.audioSampleRate,
            channelCount: 1, // Mono for Nova Sonic
            
            // Advanced constraints for better performance
            googEchoCancellation: this.optimizations.enableEchoCancellation,
            googNoiseSuppression: this.optimizations.enableNoiseSuppression,
            googAutoGainControl: this.optimizations.enableAutoGainControl,
            googHighpassFilter: true,
            googTypingNoiseDetection: true,
            googAudioMirroring: false
        };
        
        // Adaptive buffer size based on performance
        if (this.adaptiveState.currentBufferSize !== this.optimizations.audioBufferSize) {
            optimized.bufferSize = this.adaptiveState.currentBufferSize;
        }
        
        console.log('[PerformanceOptimizer] Optimized audio constraints:', optimized);
        return optimized;
    }

    /**
     * Apply codec preferences to peer connection
     * @param {RTCPeerConnection} peerConnection - Peer connection
     */
    applyCodecOptimizations(peerConnection) {
        try {
            const transceivers = peerConnection.getTransceivers();
            
            for (const transceiver of transceivers) {
                if (transceiver.receiver && transceiver.receiver.track && transceiver.receiver.track.kind === 'audio') {
                    const capabilities = RTCRtpReceiver.getCapabilities('audio');
                    
                    if (capabilities && capabilities.codecs) {
                        // Sort codecs by preference
                        const sortedCodecs = this.sortCodecsByPreference(capabilities.codecs);
                        
                        // Apply codec preferences
                        transceiver.setCodecPreferences(sortedCodecs);
                        
                        console.log('[PerformanceOptimizer] Applied codec preferences:', 
                                  sortedCodecs.map(c => c.mimeType));
                    }
                }
            }
        } catch (error) {
            console.warn('[PerformanceOptimizer] Could not apply codec optimizations:', error);
        }
    }

    /**
     * Sort codecs by performance preference
     * @param {Array} codecs - Available codecs
     * @returns {Array} Sorted codecs
     */
    sortCodecsByPreference(codecs) {
        const preferenceOrder = this.optimizations.audioCodecPreference;
        
        return codecs.sort((a, b) => {
            const aIndex = preferenceOrder.findIndex(pref => 
                a.mimeType.toLowerCase().includes(pref.toLowerCase()));
            const bIndex = preferenceOrder.findIndex(pref => 
                b.mimeType.toLowerCase().includes(pref.toLowerCase()));
            
            // Prefer codecs in our preference list
            if (aIndex !== -1 && bIndex === -1) return -1;
            if (aIndex === -1 && bIndex !== -1) return 1;
            if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex;
            
            // For codecs not in preference list, prefer lower complexity
            return a.clockRate - b.clockRate;
        });
    }

    /**
     * Start adaptive performance optimization
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    startAdaptiveOptimization(webrtcManager) {
        if (this.isOptimizing) {
            console.warn('[PerformanceOptimizer] Adaptive optimization already running');
            return;
        }

        console.log('[PerformanceOptimizer] Starting adaptive performance optimization');
        this.isOptimizing = true;
        
        // Start performance monitoring
        this.performanceMonitor.startMonitoring(webrtcManager.peerConnection, {
            interval: 2000 // Monitor every 2 seconds for adaptive optimization
        });
        
        // Set up performance monitoring callbacks
        this.performanceMonitor.onMetricsUpdate = (metrics) => {
            this.analyzePerformanceAndOptimize(metrics, webrtcManager);
        };
        
        this.performanceMonitor.onThresholdExceeded = (violations) => {
            this.handlePerformanceViolations(violations, webrtcManager);
        };
        
        // Set baseline after initial connection
        setTimeout(() => {
            this.performanceMonitor.setBaseline();
        }, 5000);
    }

    /**
     * Stop adaptive performance optimization
     */
    stopAdaptiveOptimization() {
        if (!this.isOptimizing) {
            return;
        }

        console.log('[PerformanceOptimizer] Stopping adaptive performance optimization');
        this.isOptimizing = false;
        
        this.performanceMonitor.stopMonitoring();
    }

    /**
     * Analyze performance metrics and apply optimizations
     * @param {Object} metrics - Performance metrics
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    analyzePerformanceAndOptimize(metrics, webrtcManager) {
        // Store performance history
        this.performanceHistory.push({
            timestamp: Date.now(),
            metrics: metrics.current,
            optimizationLevel: this.adaptiveState.optimizationLevel
        });
        
        // Limit history size
        if (this.performanceHistory.length > this.maxHistorySize) {
            this.performanceHistory.shift();
        }
        
        // Analyze trends and apply optimizations
        const shouldOptimize = this.shouldApplyOptimization(metrics);
        
        if (shouldOptimize) {
            this.applyAdaptiveOptimizations(metrics, webrtcManager);
        }
    }

    /**
     * Determine if optimization should be applied
     * @param {Object} metrics - Performance metrics
     * @returns {boolean} Whether to apply optimization
     */
    shouldApplyOptimization(metrics) {
        const current = metrics.current;
        const timeSinceLastOptimization = Date.now() - this.adaptiveState.lastOptimization;
        
        // Don't optimize too frequently
        if (timeSinceLastOptimization < 10000) { // 10 seconds
            return false;
        }
        
        // Check if performance is degrading
        const isPerformancePoor = (
            current.audioLatency > this.optimizations.latencyThreshold ||
            current.audioJitter > this.optimizations.jitterThreshold ||
            current.packetLossPercentage > this.optimizations.packetLossThreshold ||
            current.cpuUsage > this.optimizations.cpuThreshold
        );
        
        return isPerformancePoor;
    }

    /**
     * Apply adaptive optimizations based on performance
     * @param {Object} metrics - Performance metrics
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    async applyAdaptiveOptimizations(metrics, webrtcManager) {
        const current = metrics.current;
        let optimizationsApplied = [];
        
        console.log('[PerformanceOptimizer] Applying adaptive optimizations based on metrics:', current);
        
        // Optimize based on latency
        if (current.audioLatency > this.optimizations.latencyThreshold) {
            await this.optimizeForLatency(webrtcManager);
            optimizationsApplied.push('latency');
        }
        
        // Optimize based on jitter
        if (current.audioJitter > this.optimizations.jitterThreshold) {
            await this.optimizeForJitter(webrtcManager);
            optimizationsApplied.push('jitter');
        }
        
        // Optimize based on packet loss
        if (current.packetLossPercentage > this.optimizations.packetLossThreshold) {
            await this.optimizeForPacketLoss(webrtcManager);
            optimizationsApplied.push('packet_loss');
        }
        
        // Optimize based on CPU usage
        if (current.cpuUsage > this.optimizations.cpuThreshold) {
            await this.optimizeForCpuUsage(webrtcManager);
            optimizationsApplied.push('cpu');
        }
        
        // Update optimization state
        this.adaptiveState.lastOptimization = Date.now();
        
        // Notify callback
        if (optimizationsApplied.length > 0 && this.onOptimizationApplied) {
            this.onOptimizationApplied({
                optimizations: optimizationsApplied,
                metrics: current,
                timestamp: Date.now()
            });
        }
    }

    /**
     * Optimize for high latency
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    async optimizeForLatency(webrtcManager) {
        console.log('[PerformanceOptimizer] Optimizing for latency');
        
        // Reduce buffer size for lower latency
        if (this.adaptiveState.currentBufferSize > 2048) {
            this.adaptiveState.currentBufferSize = Math.max(2048, this.adaptiveState.currentBufferSize / 2);
            
            // Apply to audio stream handler if available
            if (webrtcManager.audioStreamHandler && webrtcManager.audioStreamHandler.setBufferSize) {
                webrtcManager.audioStreamHandler.setBufferSize(this.adaptiveState.currentBufferSize);
            }
        }
        
        // Switch to lower latency codec if available
        if (this.adaptiveState.currentCodec !== 'PCMU') {
            this.adaptiveState.currentCodec = 'PCMU';
            // Note: Codec switching during active connection is complex and may require renegotiation
        }
        
        this.adaptiveState.optimizationLevel = 'performance';
    }

    /**
     * Optimize for high jitter
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    async optimizeForJitter(webrtcManager) {
        console.log('[PerformanceOptimizer] Optimizing for jitter');
        
        // Increase buffer size to smooth out jitter
        if (this.adaptiveState.currentBufferSize < this.optimizations.maxBufferSize) {
            this.adaptiveState.currentBufferSize = Math.min(
                this.optimizations.maxBufferSize, 
                this.adaptiveState.currentBufferSize * 1.5
            );
            
            // Apply to audio stream handler if available
            if (webrtcManager.audioStreamHandler && webrtcManager.audioStreamHandler.setBufferSize) {
                webrtcManager.audioStreamHandler.setBufferSize(this.adaptiveState.currentBufferSize);
            }
        }
        
        this.adaptiveState.optimizationLevel = 'quality';
    }

    /**
     * Optimize for packet loss
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    async optimizeForPacketLoss(webrtcManager) {
        console.log('[PerformanceOptimizer] Optimizing for packet loss');
        
        // Reduce bitrate to improve reliability
        if (this.adaptiveState.currentBitrate > 32000) {
            this.adaptiveState.currentBitrate = Math.max(32000, this.adaptiveState.currentBitrate * 0.8);
        }
        
        // Switch to more robust codec
        if (this.adaptiveState.currentCodec === 'PCMU') {
            this.adaptiveState.currentCodec = 'PCMA'; // More robust for poor network conditions
        }
        
        this.adaptiveState.optimizationLevel = 'balanced';
    }

    /**
     * Optimize for high CPU usage
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    async optimizeForCpuUsage(webrtcManager) {
        console.log('[PerformanceOptimizer] Optimizing for CPU usage');
        
        // Reduce processing complexity
        this.adaptiveState.currentBufferSize = Math.max(2048, this.adaptiveState.currentBufferSize);
        
        // Disable some audio processing features if possible
        if (webrtcManager.audioStreamHandler) {
            // This would require modifications to AudioStreamHandler to support dynamic configuration
            console.log('[PerformanceOptimizer] Consider reducing audio processing complexity');
        }
        
        this.adaptiveState.optimizationLevel = 'performance';
    }

    /**
     * Handle performance violations
     * @param {Array} violations - Performance violations
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    handlePerformanceViolations(violations, webrtcManager) {
        console.warn('[PerformanceOptimizer] Performance violations detected:', violations);
        
        // Apply immediate optimizations for critical violations
        for (const violation of violations) {
            if (violation.severity === 'error') {
                switch (violation.metric) {
                    case 'packetLoss':
                        this.optimizeForPacketLoss(webrtcManager);
                        break;
                    case 'audioLatency':
                        this.optimizeForLatency(webrtcManager);
                        break;
                }
            }
        }
        
        // Notify callback
        if (this.onPerformanceDegraded) {
            this.onPerformanceDegraded(violations);
        }
    }

    /**
     * Handle resource violations from connection pool
     * @param {Object} violation - Resource violation
     */
    handleResourceViolation(violation) {
        console.warn('[PerformanceOptimizer] Resource violation detected:', violation);
        
        switch (violation.type) {
            case 'memory':
                // Force garbage collection if available
                if (window.gc) {
                    window.gc();
                }
                
                // Reduce connection pool size
                this.connectionPool.configure({
                    maxConnections: Math.max(1, this.connectionPool.maxConnections - 1)
                });
                break;
                
            case 'queue':
                // Increase connection timeout to reduce queue pressure
                this.connectionPool.configure({
                    connectionTimeout: this.connectionPool.connectionTimeout * 1.5
                });
                break;
        }
    }

    /**
     * Get optimization report
     * @returns {Object} Optimization report
     */
    getOptimizationReport() {
        const performanceReport = this.performanceMonitor.getPerformanceReport();
        const poolStats = this.connectionPool.getStatistics();
        
        return {
            performance: performanceReport,
            connectionPool: poolStats,
            adaptiveState: { ...this.adaptiveState },
            optimizations: { ...this.optimizations },
            performanceHistory: this.performanceHistory.slice(-10), // Last 10 entries
            isOptimizing: this.isOptimizing
        };
    }

    /**
     * Export optimization data
     * @returns {Object} Exportable optimization data
     */
    exportOptimizationData() {
        return {
            report: this.getOptimizationReport(),
            fullHistory: this.performanceHistory,
            exportTime: new Date().toISOString()
        };
    }

    /**
     * Clean up optimization resources
     */
    async cleanup() {
        console.log('[PerformanceOptimizer] Cleaning up optimization resources');
        
        this.stopAdaptiveOptimization();
        await this.connectionPool.stop();
        
        this.performanceHistory.length = 0;
    }
}

export default PerformanceOptimizer;