/**
 * ConnectionPool - Manages WebRTC connection pooling and resource optimization
 * Implements connection reuse, resource management, and performance optimization
 */

class ConnectionPool {
    constructor(options = {}) {
        this.maxConnections = options.maxConnections || 5;
        this.connectionTimeout = options.connectionTimeout || 30000; // 30 seconds
        this.idleTimeout = options.idleTimeout || 300000; // 5 minutes
        this.retryAttempts = options.retryAttempts || 3;
        
        // Connection pool
        this.activeConnections = new Map();
        this.idleConnections = new Map();
        this.connectionQueue = [];
        
        // Resource tracking
        this.resourceUsage = {
            totalConnections: 0,
            activeConnections: 0,
            idleConnections: 0,
            queuedRequests: 0,
            memoryUsage: 0
        };
        
        // Cleanup intervals
        this.cleanupInterval = null;
        this.monitoringInterval = null;
        
        // Event callbacks
        this.onConnectionCreated = null;
        this.onConnectionDestroyed = null;
        this.onResourceThresholdExceeded = null;
        
        // Resource thresholds
        this.thresholds = {
            maxMemoryUsage: 100 * 1024 * 1024, // 100MB
            maxIdleTime: this.idleTimeout,
            maxQueueSize: 10
        };
        
        this.isRunning = false;
    }

    /**
     * Start the connection pool
     */
    start() {
        if (this.isRunning) {
            console.warn('[ConnectionPool] Already running');
            return;
        }

        console.log('[ConnectionPool] Starting connection pool');
        this.isRunning = true;
        
        // Start cleanup interval
        this.cleanupInterval = setInterval(() => {
            this.cleanupIdleConnections();
        }, 60000); // Cleanup every minute
        
        // Start resource monitoring
        this.monitoringInterval = setInterval(() => {
            this.monitorResources();
        }, 5000); // Monitor every 5 seconds
    }

    /**
     * Stop the connection pool
     */
    async stop() {
        if (!this.isRunning) {
            return;
        }

        console.log('[ConnectionPool] Stopping connection pool');
        this.isRunning = false;
        
        // Clear intervals
        if (this.cleanupInterval) {
            clearInterval(this.cleanupInterval);
            this.cleanupInterval = null;
        }
        
        if (this.monitoringInterval) {
            clearInterval(this.monitoringInterval);
            this.monitoringInterval = null;
        }
        
        // Close all connections
        await this.closeAllConnections();
    }

    /**
     * Get or create a WebRTC connection
     * @param {string} channelName - KVS channel name
     * @param {Object} config - Connection configuration
     * @returns {Promise<Object>} Connection object
     */
    async getConnection(channelName, config) {
        const connectionKey = this.generateConnectionKey(channelName, config);
        
        // Check for existing idle connection
        if (this.idleConnections.has(connectionKey)) {
            const connection = this.idleConnections.get(connectionKey);
            
            // Move to active connections
            this.idleConnections.delete(connectionKey);
            this.activeConnections.set(connectionKey, {
                ...connection,
                lastUsed: Date.now(),
                isActive: true
            });
            
            console.log(`[ConnectionPool] Reusing idle connection: ${connectionKey}`);
            return connection.webrtcManager;
        }
        
        // Check if we can create a new connection
        if (this.activeConnections.size >= this.maxConnections) {
            // Queue the request
            return new Promise((resolve, reject) => {
                const queueItem = {
                    channelName,
                    config,
                    resolve,
                    reject,
                    timestamp: Date.now()
                };
                
                this.connectionQueue.push(queueItem);
                this.updateResourceUsage();
                
                // Set timeout for queued request
                setTimeout(() => {
                    const index = this.connectionQueue.indexOf(queueItem);
                    if (index !== -1) {
                        this.connectionQueue.splice(index, 1);
                        reject(new Error('Connection request timeout'));
                    }
                }, this.connectionTimeout);
            });
        }
        
        // Create new connection
        return await this.createConnection(channelName, config);
    }

    /**
     * Release a connection back to the pool
     * @param {string} channelName - KVS channel name
     * @param {Object} config - Connection configuration
     * @param {Object} webrtcManager - WebRTC manager instance
     */
    releaseConnection(channelName, config, webrtcManager) {
        const connectionKey = this.generateConnectionKey(channelName, config);
        
        if (this.activeConnections.has(connectionKey)) {
            const connection = this.activeConnections.get(connectionKey);
            
            // Move to idle connections
            this.activeConnections.delete(connectionKey);
            this.idleConnections.set(connectionKey, {
                ...connection,
                lastUsed: Date.now(),
                isActive: false
            });
            
            console.log(`[ConnectionPool] Released connection to idle pool: ${connectionKey}`);
            
            // Process queued requests
            this.processQueue();
            
            this.updateResourceUsage();
        }
    }

    /**
     * Create a new WebRTC connection
     * @param {string} channelName - KVS channel name
     * @param {Object} config - Connection configuration
     * @returns {Promise<Object>} WebRTC manager instance
     */
    async createConnection(channelName, config) {
        const connectionKey = this.generateConnectionKey(channelName, config);
        
        try {
            console.log(`[ConnectionPool] Creating new connection: ${connectionKey}`);
            
            // Import WebRTCManager dynamically to avoid circular dependencies
            const { default: WebRTCManager } = await import('./WebRTCManager.js');
            
            const webrtcManager = new WebRTCManager();
            
            // Set up connection monitoring
            this.setupConnectionMonitoring(webrtcManager, connectionKey);
            
            // Connect
            await webrtcManager.connect(config);
            
            // Store in active connections
            const connectionInfo = {
                webrtcManager,
                channelName,
                config,
                connectionKey,
                createdAt: Date.now(),
                lastUsed: Date.now(),
                isActive: true,
                usageCount: 1
            };
            
            this.activeConnections.set(connectionKey, connectionInfo);
            this.updateResourceUsage();
            
            // Notify callback
            if (this.onConnectionCreated) {
                this.onConnectionCreated(connectionInfo);
            }
            
            console.log(`[ConnectionPool] Connection created successfully: ${connectionKey}`);
            return webrtcManager;
            
        } catch (error) {
            console.error(`[ConnectionPool] Error creating connection ${connectionKey}:`, error);
            throw error;
        }
    }

    /**
     * Set up connection monitoring
     * @param {Object} webrtcManager - WebRTC manager instance
     * @param {string} connectionKey - Connection key
     */
    setupConnectionMonitoring(webrtcManager, connectionKey) {
        // Monitor connection state changes
        const originalOnConnectionStateChange = webrtcManager.onConnectionStateChange;
        webrtcManager.onConnectionStateChange = (state) => {
            if (state === 'disconnected' || state === 'failed' || state === 'closed') {
                this.handleConnectionFailure(connectionKey);
            }
            
            if (originalOnConnectionStateChange) {
                originalOnConnectionStateChange(state);
            }
        };
        
        // Monitor errors
        const originalOnError = webrtcManager.onError;
        webrtcManager.onError = (error) => {
            console.error(`[ConnectionPool] Connection error for ${connectionKey}:`, error);
            this.handleConnectionFailure(connectionKey);
            
            if (originalOnError) {
                originalOnError(error);
            }
        };
    }

    /**
     * Handle connection failure
     * @param {string} connectionKey - Connection key
     */
    handleConnectionFailure(connectionKey) {
        console.log(`[ConnectionPool] Handling connection failure: ${connectionKey}`);
        
        // Remove from active connections
        if (this.activeConnections.has(connectionKey)) {
            const connection = this.activeConnections.get(connectionKey);
            this.activeConnections.delete(connectionKey);
            
            // Clean up WebRTC manager
            if (connection.webrtcManager && connection.webrtcManager.cleanup) {
                connection.webrtcManager.cleanup();
            }
            
            // Notify callback
            if (this.onConnectionDestroyed) {
                this.onConnectionDestroyed(connection);
            }
        }
        
        // Remove from idle connections
        if (this.idleConnections.has(connectionKey)) {
            const connection = this.idleConnections.get(connectionKey);
            this.idleConnections.delete(connectionKey);
            
            // Clean up WebRTC manager
            if (connection.webrtcManager && connection.webrtcManager.cleanup) {
                connection.webrtcManager.cleanup();
            }
        }
        
        this.updateResourceUsage();
    }

    /**
     * Process queued connection requests
     */
    async processQueue() {
        while (this.connectionQueue.length > 0 && this.activeConnections.size < this.maxConnections) {
            const queueItem = this.connectionQueue.shift();
            
            try {
                const webrtcManager = await this.createConnection(queueItem.channelName, queueItem.config);
                queueItem.resolve(webrtcManager);
            } catch (error) {
                queueItem.reject(error);
            }
        }
        
        this.updateResourceUsage();
    }

    /**
     * Clean up idle connections
     */
    cleanupIdleConnections() {
        const now = Date.now();
        const connectionsToRemove = [];
        
        for (const [key, connection] of this.idleConnections.entries()) {
            const idleTime = now - connection.lastUsed;
            
            if (idleTime > this.idleTimeout) {
                connectionsToRemove.push(key);
            }
        }
        
        for (const key of connectionsToRemove) {
            const connection = this.idleConnections.get(key);
            this.idleConnections.delete(key);
            
            console.log(`[ConnectionPool] Cleaned up idle connection: ${key}`);
            
            // Clean up WebRTC manager
            if (connection.webrtcManager && connection.webrtcManager.cleanup) {
                connection.webrtcManager.cleanup();
            }
            
            // Notify callback
            if (this.onConnectionDestroyed) {
                this.onConnectionDestroyed(connection);
            }
        }
        
        if (connectionsToRemove.length > 0) {
            this.updateResourceUsage();
        }
    }

    /**
     * Monitor resource usage
     */
    monitorResources() {
        this.updateResourceUsage();
        
        // Check memory usage
        if (performance.memory && performance.memory.usedJSHeapSize > this.thresholds.maxMemoryUsage) {
            console.warn('[ConnectionPool] High memory usage detected');
            
            if (this.onResourceThresholdExceeded) {
                this.onResourceThresholdExceeded({
                    type: 'memory',
                    current: performance.memory.usedJSHeapSize,
                    threshold: this.thresholds.maxMemoryUsage
                });
            }
            
            // Force cleanup of idle connections
            this.cleanupIdleConnections();
        }
        
        // Check queue size
        if (this.connectionQueue.length > this.thresholds.maxQueueSize) {
            console.warn('[ConnectionPool] Connection queue size exceeded threshold');
            
            if (this.onResourceThresholdExceeded) {
                this.onResourceThresholdExceeded({
                    type: 'queue',
                    current: this.connectionQueue.length,
                    threshold: this.thresholds.maxQueueSize
                });
            }
        }
    }

    /**
     * Update resource usage statistics
     */
    updateResourceUsage() {
        this.resourceUsage = {
            totalConnections: this.activeConnections.size + this.idleConnections.size,
            activeConnections: this.activeConnections.size,
            idleConnections: this.idleConnections.size,
            queuedRequests: this.connectionQueue.length,
            memoryUsage: performance.memory ? performance.memory.usedJSHeapSize : 0
        };
    }

    /**
     * Generate connection key
     * @param {string} channelName - KVS channel name
     * @param {Object} config - Connection configuration
     * @returns {string} Connection key
     */
    generateConnectionKey(channelName, config) {
        // Create a unique key based on channel name and relevant config
        const keyData = {
            channelName,
            region: config.region,
            clientId: config.clientId
        };
        
        return btoa(JSON.stringify(keyData));
    }

    /**
     * Close all connections
     */
    async closeAllConnections() {
        console.log('[ConnectionPool] Closing all connections');
        
        // Close active connections
        for (const [key, connection] of this.activeConnections.entries()) {
            if (connection.webrtcManager && connection.webrtcManager.cleanup) {
                await connection.webrtcManager.cleanup();
            }
        }
        
        // Close idle connections
        for (const [key, connection] of this.idleConnections.entries()) {
            if (connection.webrtcManager && connection.webrtcManager.cleanup) {
                await connection.webrtcManager.cleanup();
            }
        }
        
        // Clear all collections
        this.activeConnections.clear();
        this.idleConnections.clear();
        this.connectionQueue.length = 0;
        
        this.updateResourceUsage();
    }

    /**
     * Get pool statistics
     * @returns {Object} Pool statistics
     */
    getStatistics() {
        return {
            ...this.resourceUsage,
            maxConnections: this.maxConnections,
            connectionTimeout: this.connectionTimeout,
            idleTimeout: this.idleTimeout,
            thresholds: this.thresholds,
            isRunning: this.isRunning
        };
    }

    /**
     * Set pool configuration
     * @param {Object} options - Configuration options
     */
    configure(options) {
        if (options.maxConnections !== undefined) {
            this.maxConnections = options.maxConnections;
        }
        
        if (options.connectionTimeout !== undefined) {
            this.connectionTimeout = options.connectionTimeout;
        }
        
        if (options.idleTimeout !== undefined) {
            this.idleTimeout = options.idleTimeout;
        }
        
        if (options.thresholds) {
            this.thresholds = { ...this.thresholds, ...options.thresholds };
        }
        
        console.log('[ConnectionPool] Configuration updated:', {
            maxConnections: this.maxConnections,
            connectionTimeout: this.connectionTimeout,
            idleTimeout: this.idleTimeout,
            thresholds: this.thresholds
        });
    }
}

export default ConnectionPool;