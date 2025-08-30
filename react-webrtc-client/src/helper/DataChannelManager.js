/**
 * DataChannelManager - Manages S2S event messaging via WebRTC data channels
 * Handles event serialization, transmission, deserialization, and routing to existing event handlers
 */

class DataChannelManager {
    constructor() {
        this.dataChannel = null;
        this.isReady = false;
        this.messageQueue = [];
        this.eventHandlers = new Map();
        this.messageId = 0;
        this.pendingAcks = new Map();
        this.maxRetries = 3;
        this.retryDelay = 1000; // 1 second
        
        // Event callbacks
        this.onMessage = null;
        this.onError = null;
        this.onStateChange = null;
        
        // Enhanced reliability features
        this.sequenceNumber = 0;
        this.expectedSequenceNumber = 0;
        this.outOfOrderBuffer = new Map();
        this.deliveredMessages = new Set();
        this.messageRetryMap = new Map();
        this.connectionMonitor = {
            interval: null,
            lastActivity: Date.now(),
            heartbeatInterval: 45000, // 45 seconds (more frequent)
            timeoutThreshold: 120000 // 120 seconds (2x+ heartbeat interval)
        };
        
        // Statistics
        this.stats = {
            messagesSent: 0,
            messagesReceived: 0,
            messagesRetried: 0,
            messagesDropped: 0,
            outOfOrderMessages: 0,
            duplicateMessages: 0,
            ackTimeouts: 0,
            connectionLosses: 0
        };
        
        console.log('[DataChannelManager] Initialized with enhanced reliability');
    }

    /**
     * Initialize data channel manager with WebRTC data channel
     * @param {RTCDataChannel} dataChannel - WebRTC data channel instance
     */
    initialize(dataChannel) {
        if (!dataChannel) {
            throw new Error('Data channel is required');
        }

        this.dataChannel = dataChannel;
        this.setupDataChannelHandlers();
        this._startConnectionMonitoring();
        
        console.log('[DataChannelManager] Initialized with data channel:', dataChannel.label);
    }

    /**
     * Set up data channel event handlers
     */
    setupDataChannelHandlers() {
        this.dataChannel.onopen = () => {
            console.log('[DataChannelManager] Data channel opened');
            this.isReady = true;
            this.connectionMonitor.lastActivity = Date.now();
            this.processMessageQueue();
            
            // Heartbeat disabled - relying on WebRTC native connection monitoring
            // this._sendHeartbeat();
            
            if (this.onStateChange) {
                this.onStateChange('open');
            }
        };

        this.dataChannel.onmessage = (event) => {
            this.connectionMonitor.lastActivity = Date.now();
            this.stats.messagesReceived++;
            
            try {
                const message = JSON.parse(event.data);
                console.log('[DataChannelManager] Received message:', message);
                this.handleIncomingMessage(message);
            } catch (error) {
                console.error('[DataChannelManager] Error parsing message:', error);
                this.stats.messagesDropped++;
                
                if (this.onError) {
                    this.onError(new Error(`Message parsing failed: ${error.message}`));
                }
            }
        };

        this.dataChannel.onerror = (error) => {
            console.error('[DataChannelManager] Data channel error:', error);
            this.stats.connectionLosses++;
            
            if (this.onError) {
                this.onError(new Error(`Data channel error: ${error.message || 'Unknown error'}`));
            }
        };

        this.dataChannel.onclose = () => {
            console.log('[DataChannelManager] Data channel closed');
            this.isReady = false;
            this.stats.connectionLosses++;
            this._stopConnectionMonitoring();
            
            // Handle pending messages
            this._handleDisconnection();
            
            if (this.onStateChange) {
                this.onStateChange('closed');
            }
        };
    }

    /**
     * Send S2S event via data channel
     * @param {Object} event - S2S event object
     * @param {boolean} requireAck - Whether to require acknowledgment
     * @returns {Promise} Promise that resolves when message is sent (and acknowledged if required)
     */
    async sendEvent(event, requireAck = false) {
        const messageId = this.generateMessageId();
        const sequenceNumber = this.getNextSequenceNumber();
        
        const message = {
            id: messageId,
            type: 'S2S_EVENT',
            timestamp: Date.now(),
            sequenceNumber,
            requireAck,
            event
        };

        console.log('[DataChannelManager] 🚀 Preparing to send S2S event:', {
            messageId,
            sequenceNumber,
            eventType: Object.keys(event?.event || {})[0] || 'unknown',
            isReady: this.isReady,
            channelState: this.getChannelState(),
            message: message
        });

        if (this.isReady) {
            console.log('[DataChannelManager] ✅ Channel ready, sending S2S event immediately');
            return this.sendMessageWithRetry(message, requireAck);
        } else {
            // Queue message if data channel not ready
            console.log('[DataChannelManager] ⏳ Queueing S2S event (channel not ready):', message);
            return new Promise((resolve, reject) => {
                this.messageQueue.push({ message, requireAck, resolve, reject });
            });
        }
    }

    /**
     * Send message via data channel with retry mechanism
     * @param {Object} message - Message to send
     * @param {boolean} requireAck - Whether to require acknowledgment
     * @returns {Promise} Promise that resolves when message is sent (and acknowledged if required)
     */
    async sendMessageWithRetry(message, requireAck = false) {
        let retryCount = 0;
        
        while (retryCount <= this.maxRetries) {
            try {
                await this.sendMessage(message, requireAck);
                this.stats.messagesSent++;
                
                // Remove from retry map if successful
                this.messageRetryMap.delete(message.id);
                return;
                
            } catch (error) {
                retryCount++;
                this.stats.messagesRetried++;
                
                if (retryCount > this.maxRetries) {
                    this.stats.messagesDropped++;
                    this.messageRetryMap.delete(message.id);
                    throw new Error(`Message failed after ${this.maxRetries} retries: ${error.message}`);
                }
                
                console.warn(`[DataChannelManager] Message send failed (attempt ${retryCount}/${this.maxRetries}):`, error);
                
                // Store retry information
                this.messageRetryMap.set(message.id, {
                    message,
                    requireAck,
                    retryCount,
                    lastAttempt: Date.now()
                });
                
                // Wait before retry with exponential backoff
                const delay = this.retryDelay * Math.pow(2, retryCount - 1);
                await this._delay(delay);
                
                // Check if channel is still available
                if (!this.isChannelReady()) {
                    throw new Error('Data channel not available for retry');
                }
            }
        }
    }

    /**
     * Send message via data channel
     * @param {Object} message - Message to send
     * @param {boolean} requireAck - Whether to require acknowledgment
     * @returns {Promise} Promise that resolves when message is sent (and acknowledged if required)
     */
    async sendMessage(message, requireAck = false) {
        return new Promise((resolve, reject) => {
            try {
                const serialized = JSON.stringify(message);
                
                console.log('[DataChannelManager] 📤 Sending message via data channel:', {
                    messageId: message.id,
                    messageType: message.type,
                    size: serialized.length,
                    channelState: this.dataChannel?.readyState,
                    requireAck: requireAck
                });
                
                // Check message size (WebRTC data channel has size limits)
                if (serialized.length > 65536) { // 64KB limit
                    console.log('[DataChannelManager] 📦 Message too large, using chunking');
                    return this.sendLargeMessage(message, requireAck, resolve, reject);
                }

                this.dataChannel.send(serialized);
                console.log('[DataChannelManager] ✅ Message sent successfully via data channel');

                if (requireAck) {
                    // Set up acknowledgment handling with timeout
                    const timeout = setTimeout(() => {
                        this.pendingAcks.delete(message.id);
                        this.stats.ackTimeouts++;
                        reject(new Error(`Message acknowledgment timeout: ${message.id}`));
                    }, 5000); // 5 second timeout

                    this.pendingAcks.set(message.id, { resolve, reject, timeout, timestamp: Date.now() });
                } else {
                    resolve();
                }
            } catch (error) {
                console.error('[DataChannelManager] ❌ Error sending message:', error);
                reject(error);
            }
        });
    }

    /**
     * Send large message by chunking
     * @param {Object} message - Large message to send
     * @param {boolean} requireAck - Whether to require acknowledgment
     * @param {Function} resolve - Promise resolve function
     * @param {Function} reject - Promise reject function
     */
    async sendLargeMessage(message, requireAck, resolve, reject) {
        try {
            const serialized = JSON.stringify(message);
            const chunkSize = 60000; // 60KB chunks to be safe
            const totalChunks = Math.ceil(serialized.length / chunkSize);
            const chunkId = this.generateMessageId();

            console.log(`[DataChannelManager] Sending large message in ${totalChunks} chunks`);

            // Send chunks
            for (let i = 0; i < totalChunks; i++) {
                const start = i * chunkSize;
                const end = Math.min(start + chunkSize, serialized.length);
                const chunk = serialized.slice(start, end);

                const chunkMessage = {
                    id: this.generateMessageId(),
                    type: 'CHUNK',
                    chunkId,
                    chunkIndex: i,
                    totalChunks,
                    isLast: i === totalChunks - 1,
                    data: chunk,
                    requireAck: requireAck && i === totalChunks - 1 // Only require ack for last chunk
                };

                await this.sendMessage(chunkMessage, chunkMessage.requireAck);
            }

            if (!requireAck) {
                resolve();
            }
        } catch (error) {
            reject(error);
        }
    }

    /**
     * Handle incoming message from data channel
     * @param {Object} message - Received message
     */
    handleIncomingMessage(message) {
        // Handle heartbeat messages
        if (message.type === 'HEARTBEAT') {
            this._handleHeartbeat(message);
            return;
        }

        // Handle acknowledgments
        if (message.type === 'ACK') {
            this.handleAcknowledgment(message);
            return;
        }

        // Handle chunks
        if (message.type === 'CHUNK') {
            this.handleChunk(message);
            return;
        }

        // Check for duplicate messages
        if (message.id && this.deliveredMessages.has(message.id)) {
            console.log('[DataChannelManager] Duplicate message detected, ignoring:', message.id);
            this.stats.duplicateMessages++;
            
            // Still send ACK if required to prevent sender from retrying
            if (message.requireAck) {
                this.sendAcknowledgment(message.id);
            }
            return;
        }

        // Handle ordered delivery for S2S events (both S2S_EVENT and S2S_RESPONSE)
        if ((message.type === 'S2S_EVENT' || message.type === 'S2S_RESPONSE') && typeof message.sequenceNumber === 'number') {
            if (!this._handleOrderedMessage(message)) {
                return; // Message was buffered for later processing
            }
        }

        // Mark message as delivered
        if (message.id) {
            this.deliveredMessages.add(message.id);
            
            // Limit the size of delivered messages set
            if (this.deliveredMessages.size > 1000) {
                const oldestMessages = Array.from(this.deliveredMessages).slice(0, 500);
                oldestMessages.forEach(id => this.deliveredMessages.delete(id));
            }
        }

        // Send acknowledgment if required
        if (message.requireAck) {
            this.sendAcknowledgment(message.id);
        }

        // Handle S2S events (both S2S_EVENT and S2S_RESPONSE)
        if (message.type === 'S2S_EVENT' || message.type === 'S2S_RESPONSE') {
            console.log(`[DataChannelManager] 🎯 Processing ${message.type} message:`, message);
            console.log(`[DataChannelManager] 📋 Event structure:`, message.event);
            this.routeEvent(message.event, message);
        } else {
            console.log(`[DataChannelManager] ❓ Unhandled message type: ${message.type}`, message);
        }

        // Call general message handler
        if (this.onMessage) {
            this.onMessage(message);
        }
    }

    /**
     * Handle acknowledgment message
     * @param {Object} ackMessage - Acknowledgment message
     */
    handleAcknowledgment(ackMessage) {
        const pending = this.pendingAcks.get(ackMessage.messageId);
        if (pending) {
            clearTimeout(pending.timeout);
            this.pendingAcks.delete(ackMessage.messageId);
            pending.resolve();
            console.log('[DataChannelManager] Received acknowledgment for message:', ackMessage.messageId);
        }
    }

    /**
     * Handle chunk message for large message reassembly
     * @param {Object} chunkMessage - Chunk message
     */
    handleChunk(chunkMessage) {
        const { chunkId, chunkIndex, totalChunks, data } = chunkMessage;
        
        if (!this.chunkBuffers) {
            this.chunkBuffers = new Map();
        }

        if (!this.chunkBuffers.has(chunkId)) {
            this.chunkBuffers.set(chunkId, {
                chunks: new Array(totalChunks),
                receivedCount: 0
            });
        }

        const buffer = this.chunkBuffers.get(chunkId);
        buffer.chunks[chunkIndex] = data;
        buffer.receivedCount++;

        console.log(`[DataChannelManager] Received chunk ${chunkIndex + 1}/${totalChunks} for message ${chunkId}`);

        // Check if all chunks received
        if (buffer.receivedCount === totalChunks) {
            try {
                const reassembled = buffer.chunks.join('');
                const originalMessage = JSON.parse(reassembled);
                
                console.log('[DataChannelManager] Reassembled large message:', originalMessage);
                
                // Clean up buffer
                this.chunkBuffers.delete(chunkId);
                
                // Process the reassembled message
                this.handleIncomingMessage(originalMessage);
            } catch (error) {
                console.error('[DataChannelManager] Error reassembling chunks:', error);
                this.chunkBuffers.delete(chunkId);
            }
        }
    }

    /**
     * Send acknowledgment for received message
     * @param {string} messageId - ID of message to acknowledge
     */
    sendAcknowledgment(messageId) {
        const ackMessage = {
            id: this.generateMessageId(),
            type: 'ACK',
            messageId,
            timestamp: Date.now()
        };

        try {
            this.dataChannel.send(JSON.stringify(ackMessage));
            console.log('[DataChannelManager] Sent acknowledgment for message:', messageId);
        } catch (error) {
            console.error('[DataChannelManager] Error sending acknowledgment:', error);
        }
    }

    /**
     * Route S2S event to appropriate handler
     * @param {Object} event - S2S event object
     * @param {Object} message - Full message object
     */
    routeEvent(event, message) {
        console.log('[DataChannelManager] Routing S2S event:', event);

        // Extract event type from the event structure
        const eventType = this.getEventType(event);
        
        // Call registered event handlers
        const handlers = this.eventHandlers.get(eventType) || [];
        handlers.forEach(handler => {
            try {
                handler(event, message);
            } catch (error) {
                console.error(`[DataChannelManager] Error in event handler for ${eventType}:`, error);
            }
        });

        // Call registered handlers for 'all' events
        const allHandlers = this.eventHandlers.get('all') || [];
        allHandlers.forEach(handler => {
            try {
                handler(event, message);
            } catch (error) {
                console.error('[DataChannelManager] Error in general event handler:', error);
            }
        });
    }

    /**
     * Get event type from S2S event object
     * @param {Object} event - S2S event object
     * @returns {string} Event type
     */
    getEventType(event) {
        if (!event || !event.event) {
            return 'unknown';
        }

        // Extract the first key from the event object
        const eventKeys = Object.keys(event.event);
        return eventKeys.length > 0 ? eventKeys[0] : 'unknown';
    }

    /**
     * Register event handler for specific event type
     * @param {string} eventType - Event type to handle ('all' for all events)
     * @param {Function} handler - Handler function
     */
    onEvent(eventType, handler) {
        if (!this.eventHandlers.has(eventType)) {
            this.eventHandlers.set(eventType, []);
        }
        this.eventHandlers.get(eventType).push(handler);
        console.log(`[DataChannelManager] Registered handler for event type: ${eventType}`);
    }

    /**
     * Remove event handler
     * @param {string} eventType - Event type
     * @param {Function} handler - Handler function to remove
     */
    offEvent(eventType, handler) {
        const handlers = this.eventHandlers.get(eventType);
        if (handlers) {
            const index = handlers.indexOf(handler);
            if (index > -1) {
                handlers.splice(index, 1);
                console.log(`[DataChannelManager] Removed handler for event type: ${eventType}`);
            }
        }
    }

    /**
     * Process queued messages when data channel becomes ready
     */
    processMessageQueue() {
        console.log(`[DataChannelManager] 📋 Processing ${this.messageQueue.length} queued messages`);
        
        while (this.messageQueue.length > 0) {
            const { message, requireAck, resolve, reject } = this.messageQueue.shift();
            
            console.log(`[DataChannelManager] 📤 Processing queued message:`, {
                messageId: message.id,
                messageType: message.type,
                requireAck: requireAck
            });
            
            this.sendMessage(message, requireAck)
                .then(() => {
                    console.log(`[DataChannelManager] ✅ Queued message sent successfully: ${message.id}`);
                    resolve();
                })
                .catch((error) => {
                    console.error(`[DataChannelManager] ❌ Error sending queued message: ${message.id}`, error);
                    reject(error);
                });
        }
        
        console.log(`[DataChannelManager] ✅ Finished processing message queue`);
    }

    /**
     * Generate unique message ID
     * @returns {string} Unique message ID
     */
    generateMessageId() {
        return `msg_${Date.now()}_${++this.messageId}`;
    }

    /**
     * Check if data channel is ready for sending messages
     * @returns {boolean} Ready status
     */
    isChannelReady() {
        const ready = this.isReady && this.dataChannel && this.dataChannel.readyState === 'open';
        console.log('[DataChannelManager] 🔍 Channel ready check:', {
            isReady: this.isReady,
            hasDataChannel: !!this.dataChannel,
            readyState: this.dataChannel?.readyState,
            finalResult: ready
        });
        return ready;
    }

    /**
     * Get data channel state
     * @returns {string} Data channel ready state
     */
    getChannelState() {
        return this.dataChannel ? this.dataChannel.readyState : 'not_initialized';
    }



    /**
     * Get next sequence number for ordered delivery
     * @private
     */
    getNextSequenceNumber() {
        return ++this.sequenceNumber;
    }

    /**
     * Handle ordered message delivery
     * @private
     */
    _handleOrderedMessage(message) {
        const { sequenceNumber } = message;
        
        if (sequenceNumber === this.expectedSequenceNumber) {
            // Message is in order, process it
            this.expectedSequenceNumber++;
            
            // Check if we can process any buffered out-of-order messages
            this._processBufferedMessages();
            
            return true; // Process this message
        } else if (sequenceNumber > this.expectedSequenceNumber) {
            // Message is out of order, buffer it
            console.log(`[DataChannelManager] Out-of-order message buffered: expected ${this.expectedSequenceNumber}, got ${sequenceNumber}`);
            this.outOfOrderBuffer.set(sequenceNumber, message);
            this.stats.outOfOrderMessages++;
            
            // Send ACK if required (even for buffered messages)
            if (message.requireAck) {
                this.sendAcknowledgment(message.id);
            }
            
            return false; // Don't process this message yet
        } else {
            // Message is older than expected (duplicate or very late)
            console.log(`[DataChannelManager] Old message ignored: expected ${this.expectedSequenceNumber}, got ${sequenceNumber}`);
            this.stats.duplicateMessages++;
            
            // Send ACK if required
            if (message.requireAck) {
                this.sendAcknowledgment(message.id);
            }
            
            return false; // Don't process this message
        }
    }

    /**
     * Process buffered out-of-order messages
     * @private
     */
    _processBufferedMessages() {
        while (this.outOfOrderBuffer.has(this.expectedSequenceNumber)) {
            const message = this.outOfOrderBuffer.get(this.expectedSequenceNumber);
            this.outOfOrderBuffer.delete(this.expectedSequenceNumber);
            
            console.log(`[DataChannelManager] Processing buffered message with sequence ${this.expectedSequenceNumber}`);
            
            // Mark as delivered and process
            if (message.id) {
                this.deliveredMessages.add(message.id);
            }
            
            if (message.type === 'S2S_EVENT') {
                this.routeEvent(message.event, message);
            }
            
            if (this.onMessage) {
                this.onMessage(message);
            }
            
            this.expectedSequenceNumber++;
        }
    }

    /**
     * Start connection monitoring with heartbeat
     * @private
     */
    _startConnectionMonitoring() {
        this._stopConnectionMonitoring();
        
        this.connectionMonitor.interval = setInterval(() => {
            this._checkConnectionHealth();
        }, this.connectionMonitor.heartbeatInterval);
    }

    /**
     * Stop connection monitoring
     * @private
     */
    _stopConnectionMonitoring() {
        if (this.connectionMonitor.interval) {
            clearInterval(this.connectionMonitor.interval);
            this.connectionMonitor.interval = null;
        }
    }

    /**
     * Check connection health and send heartbeat
     * @private
     */
    _checkConnectionHealth() {
        const now = Date.now();
        const timeSinceLastActivity = now - this.connectionMonitor.lastActivity;
        
        if (timeSinceLastActivity > this.connectionMonitor.timeoutThreshold) {
            console.warn('[DataChannelManager] Connection timeout detected');
            this.stats.connectionLosses++;
            
            if (this.onError) {
                this.onError(new Error('Data channel connection timeout'));
            }
        } else if (timeSinceLastActivity > this.connectionMonitor.heartbeatInterval * 0.75) {
            // Heartbeat disabled - relying on WebRTC native connection monitoring
            // this._sendHeartbeat();
        }
    }

    /**
     * Send heartbeat message
     * @private
     */
    _sendHeartbeat() {
        if (this.isChannelReady()) {
            const heartbeat = {
                id: this.generateMessageId(),
                type: 'HEARTBEAT',
                timestamp: Date.now()
            };
            
            try {
                this.dataChannel.send(JSON.stringify(heartbeat));
                console.debug(`[DataChannelManager] Sent heartbeat at ${new Date().toISOString()}`); // Changed to debug level
            } catch (error) {
                console.error('[DataChannelManager] Error sending heartbeat:', error);
            }
        }
    }

    /**
     * Handle heartbeat message
     * @private
     */
    _handleHeartbeat(message) {
        // Only respond to original heartbeats, not responses (to avoid ping-pong)
        if (message.responseToId) {
            console.debug('[DataChannelManager] Received heartbeat response'); // Changed to debug level
            // This is a response to our heartbeat, don't respond back
            return;
        }
        
        console.debug('[DataChannelManager] Received heartbeat request, sending response'); // Changed to debug level
        
        // Send heartbeat response only for original heartbeat requests
        const response = {
            id: this.generateMessageId(),
            type: 'HEARTBEAT',
            timestamp: Date.now(),
            responseToId: message.id
        };
        
        try {
            this.dataChannel.send(JSON.stringify(response));
        } catch (error) {
            console.error('[DataChannelManager] Error sending heartbeat response:', error);
        }
    }

    /**
     * Handle disconnection by managing pending messages
     * @private
     */
    _handleDisconnection() {
        console.log('[DataChannelManager] Handling disconnection...');
        
        // Move pending ACK messages back to queue for retry when reconnected
        this.pendingAcks.forEach(({ timeout }, messageId) => {
            clearTimeout(timeout);
            
            const retryInfo = this.messageRetryMap.get(messageId);
            if (retryInfo && retryInfo.retryCount < this.maxRetries) {
                console.log(`[DataChannelManager] Queueing message for retry after reconnection: ${messageId}`);
                this.messageQueue.push({
                    message: retryInfo.message,
                    requireAck: retryInfo.requireAck,
                    resolve: () => {}, // Will be handled by retry mechanism
                    reject: () => {}
                });
            }
        });
        
        this.pendingAcks.clear();
    }

    /**
     * Retry failed messages
     * @private
     */
    async _retryFailedMessages() {
        const now = Date.now();
        const retryPromises = [];
        
        for (const [messageId, retryInfo] of this.messageRetryMap.entries()) {
            const timeSinceLastAttempt = now - retryInfo.lastAttempt;
            const shouldRetry = timeSinceLastAttempt > this.retryDelay * Math.pow(2, retryInfo.retryCount);
            
            if (shouldRetry && retryInfo.retryCount < this.maxRetries) {
                console.log(`[DataChannelManager] Retrying failed message: ${messageId}`);
                retryPromises.push(this.sendMessageWithRetry(retryInfo.message, retryInfo.requireAck));
            } else if (retryInfo.retryCount >= this.maxRetries) {
                console.error(`[DataChannelManager] Message exceeded max retries, dropping: ${messageId}`);
                this.messageRetryMap.delete(messageId);
                this.stats.messagesDropped++;
            }
        }
        
        if (retryPromises.length > 0) {
            try {
                await Promise.allSettled(retryPromises);
            } catch (error) {
                console.error('[DataChannelManager] Error during message retry:', error);
            }
        }
    }

    /**
     * Delay helper for retry mechanism
     * @private
     */
    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Get enhanced statistics
     * @returns {Object} Enhanced statistics object
     */
    getStatistics() {
        return {
            isReady: this.isReady,
            channelState: this.getChannelState(),
            queuedMessages: this.messageQueue.length,
            pendingAcks: this.pendingAcks.size,
            registeredHandlers: Array.from(this.eventHandlers.keys()),
            activeChunkBuffers: this.chunkBuffers ? this.chunkBuffers.size : 0,
            sequenceNumber: this.sequenceNumber,
            expectedSequenceNumber: this.expectedSequenceNumber,
            outOfOrderBufferSize: this.outOfOrderBuffer.size,
            deliveredMessagesCount: this.deliveredMessages.size,
            retryMapSize: this.messageRetryMap.size,
            lastActivity: this.connectionMonitor.lastActivity,
            timeSinceLastActivity: Date.now() - this.connectionMonitor.lastActivity,
            stats: { ...this.stats }
        };
    }

    /**
     * Reset statistics
     */
    resetStatistics() {
        this.stats = {
            messagesSent: 0,
            messagesReceived: 0,
            messagesRetried: 0,
            messagesDropped: 0,
            outOfOrderMessages: 0,
            duplicateMessages: 0,
            ackTimeouts: 0,
            connectionLosses: 0
        };
    }

    /**
     * Get reliability status
     * @returns {Object} Reliability status
     */
    getReliabilityStatus() {
        const stats = this.getStatistics();
        const totalMessages = stats.stats.messagesSent + stats.stats.messagesReceived;
        
        return {
            isHealthy: this.isChannelReady() && stats.timeSinceLastActivity < this.connectionMonitor.timeoutThreshold,
            reliabilityScore: totalMessages > 0 ? 
                ((totalMessages - stats.stats.messagesDropped) / totalMessages * 100).toFixed(2) + '%' : 
                'N/A',
            orderingEfficiency: stats.stats.outOfOrderMessages > 0 ? 
                ((stats.stats.messagesReceived - stats.stats.outOfOrderMessages) / stats.stats.messagesReceived * 100).toFixed(2) + '%' : 
                '100%',
            duplicateRate: stats.stats.messagesReceived > 0 ? 
                (stats.stats.duplicateMessages / stats.stats.messagesReceived * 100).toFixed(2) + '%' : 
                '0%',
            retryRate: stats.stats.messagesSent > 0 ? 
                (stats.stats.messagesRetried / stats.stats.messagesSent * 100).toFixed(2) + '%' : 
                '0%'
        };
    }

    /**
     * Clean up resources
     */
    cleanup() {
        console.log('[DataChannelManager] Cleaning up...');
        
        // Stop connection monitoring
        this._stopConnectionMonitoring();
        
        // Clear pending acknowledgments
        this.pendingAcks.forEach(({ timeout }) => clearTimeout(timeout));
        this.pendingAcks.clear();
        
        // Clear message queue
        this.messageQueue.forEach(({ reject }) => {
            reject(new Error('DataChannelManager cleanup'));
        });
        this.messageQueue = [];
        
        // Clear chunk buffers
        if (this.chunkBuffers) {
            this.chunkBuffers.clear();
        }
        
        // Clear reliability buffers
        this.outOfOrderBuffer.clear();
        this.deliveredMessages.clear();
        this.messageRetryMap.clear();
        
        // Clear event handlers
        this.eventHandlers.clear();
        
        // Reset state
        this.isReady = false;
        this.dataChannel = null;
        this.sequenceNumber = 0;
        this.expectedSequenceNumber = 0;
        
        console.log('[DataChannelManager] Cleanup complete');
    }
}

export default DataChannelManager;