/**
 * WebRTCManager - Native KVS WebRTC implementation following official SDK patterns
 * Based on amazon-kinesis-video-streams-webrtc-sdk-js/examples/viewer.js
 * 
 * Key optimizations:
 * 1. Native WebRTC audio handling (no custom processing)
 * 2. Simple {audio: true} constraints like official examples
 * 3. Direct media stream handling without intermediate processing
 * 4. Proper codec preferences and ICE configuration
 */

import { SignalingClient, Role } from 'amazon-kinesis-video-streams-webrtc';
import AWS from 'aws-sdk';
import AudioStreamHandler from './AudioStreamHandler.js';

// Ensure KinesisVideoSignalingChannels is available
import 'aws-sdk/clients/kinesisvideosignalingchannels';

class WebRTCManager {
    constructor() {
        this.instanceId = Math.random().toString(36).substring(2, 9);
        
        // Core WebRTC components
        this.signalingClient = null;
        this.peerConnection = null;
        this.localStream = null;
        this.remoteStream = null;
        this.dataChannel = null;
        
        // Connection state
        this.isConnected = false;
        this.connectionState = 'disconnected';
        this.config = null;
        
        // Event callbacks
        this.onConnectionStateChange = null;
        this.onDataChannelMessage = null;
        this.onRemoteAudioTrack = null;
        this.onError = null;
        this.onLocalAudioTrack = null;
        this.onAudioData = null; // For compatibility with existing code
        this.onAudioLevel = null; // For compatibility with existing code
        this.onAudioInputEvent = null; // Callback for audioInput events
        
        // Audio transmission tracking
        this.audioTransmissionStats = {
            isTransmitting: false,
            currentSessionCount: 0,
            totalDataSize: 0,
            sessionStartTime: null,
            lastLogTime: 0
        };
        
        // Connection monitoring
        this.connectionMonitor = {
            interval: null,
            checkFrequency: 5000,
            lastSuccessfulCheck: Date.now()
        };
        
        // Initialize AudioStreamHandler for audio level monitoring
        this.audioStreamHandler = new AudioStreamHandler();
        this.audioStreamHandler.onAudioLevel = (level) => {
            if (this.onAudioLevel) {
                this.onAudioLevel(level);
            }
        };
        
        console.log(`[WebRTCManager-${this.instanceId}] 🚀 Initialized with NATIVE WebRTC patterns (no custom audio processing)`);
    }

    /**
     * Connect to KVS WebRTC following official SDK patterns
     * @param {Object} config - WebRTC configuration
     */
    async connect(config) {
        try {
            this.config = config;
            this.connectionState = 'connecting';
            
            console.log(`[WebRTCManager-${this.instanceId}] 🔌 Starting connection with NATIVE WebRTC patterns...`);
            console.log(`[WebRTCManager-${this.instanceId}] Config:`, {
                channelName: config.channelName,
                region: config.region,
                clientId: config.clientId,
                sendAudio: config.sendAudio
            });

            // Step 1: Create KVS client (exactly like official examples)
            const kinesisVideoClient = new AWS.KinesisVideo({
                region: config.region,
                credentials: config.credentials,
                correctClockSkew: true,
            });

            // Step 2: Get signaling channel ARN
            console.log(`[WebRTCManager-${this.instanceId}] 📡 Getting signaling channel ARN...`);
            const describeSignalingChannelResponse = await kinesisVideoClient.describeSignalingChannel({
                ChannelName: config.channelName,
            }).promise();

            const channelARN = describeSignalingChannelResponse.ChannelInfo.ChannelARN;
            console.log(`[WebRTCManager-${this.instanceId}] ✅ Channel ARN:`, channelARN);

            // Step 3: Get signaling channel endpoints
            console.log(`[WebRTCManager-${this.instanceId}] 🌐 Getting signaling endpoints...`);
            const getSignalingChannelEndpointResponse = await kinesisVideoClient.getSignalingChannelEndpoint({
                ChannelARN: channelARN,
                SingleMasterChannelEndpointConfiguration: {
                    Protocols: ['WSS', 'HTTPS'],
                    Role: Role.VIEWER,
                },
            }).promise();

            const endpointsByProtocol = getSignalingChannelEndpointResponse.ResourceEndpointList.reduce((endpoints, endpoint) => {
                endpoints[endpoint.Protocol] = endpoint.ResourceEndpoint;
                return endpoints;
            }, {});

            console.log(`[WebRTCManager-${this.instanceId}] ✅ Endpoints:`, endpointsByProtocol);

            // Step 4: Get ICE server configuration from KVS (with error handling)
            console.log(`[WebRTCManager-${this.instanceId}] 🧊 Getting ICE server configuration...`);
            
            let iceServers = [
                { urls: `stun:stun.kinesisvideo.${config.region}.amazonaws.com:443` }
            ];

            try {
                // Create signaling client for ICE config
                const kinesisVideoSignalingChannelsClient = new AWS.KinesisVideoSignalingChannels({
                    region: config.region,
                    credentials: config.credentials,
                    endpoint: endpointsByProtocol.HTTPS,
                });

                // Get ICE server config
                const getIceServerConfigResponse = await kinesisVideoSignalingChannelsClient.getIceServerConfig({
                    ChannelARN: channelARN,
                    ClientId: config.clientId,
                }).promise();

                // Add TURN servers
                getIceServerConfigResponse.IceServerList.forEach((iceServer, index) => {
                    iceServers.push({
                        urls: iceServer.Uris,
                        username: iceServer.Username,
                        credential: iceServer.Password,
                    });
                    console.log(`[WebRTCManager-${this.instanceId}] 🎯 Added ICE server ${index + 1}:`, iceServer.Uris);
                });

            } catch (error) {
                console.warn(`[WebRTCManager-${this.instanceId}] ⚠️ Failed to get TURN servers, using STUN only:`, error.message);
            }

            console.log(`[WebRTCManager-${this.instanceId}] ✅ ICE servers configured:`, iceServers.length);

            // Step 5: Create SignalingClient (exactly like official examples)
            console.log(`[WebRTCManager-${this.instanceId}] 📞 Creating signaling client...`);
            this.signalingClient = new SignalingClient({
                channelARN,
                channelEndpoint: endpointsByProtocol.WSS,
                clientId: config.clientId,
                role: Role.VIEWER,
                region: config.region,
                credentials: config.credentials,
                systemClockOffset: kinesisVideoClient.config.systemClockOffset,
            });

            // Step 6: Create RTCPeerConnection (exactly like official examples)
            const peerConnectionConfig = {
                iceServers,
                iceTransportPolicy: 'all', // Allow both STUN and TURN
            };

            console.log(`[WebRTCManager-${this.instanceId}] 🔗 Creating peer connection...`);
            this.peerConnection = new RTCPeerConnection(peerConnectionConfig);

            // Step 7: Set up event handlers
            this.setupPeerConnectionHandlers();
            this.setupSignalingClientHandlers();

            // Step 8: Create data channel (for S2S events) - use KVS standard name
            console.log(`[WebRTCManager-${this.instanceId}] 📨 Creating data channel...`);
            this.dataChannel = this.peerConnection.createDataChannel('kvsDataChannel', {
                ordered: true,
                maxRetransmits: 3
            });
            this.setupDataChannelHandlers();

            // Step 9: Open signaling connection
            console.log(`[WebRTCManager-${this.instanceId}] 🚀 Opening signaling connection...`);
            this.signalingClient.open();

        } catch (error) {
            this.connectionState = 'failed';
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Connection failed:`, error);
            
            if (this.onError) {
                this.onError(error);
            }
            throw error;
        }
    }

    /**
     * Set up signaling client event handlers (following official patterns)
     */
    setupSignalingClientHandlers() {
        this.signalingClient.on('open', async () => {
            console.log(`[WebRTCManager-${this.instanceId}] ✅ Signaling connected`);
            
            // Get media stream AFTER signaling is connected (official pattern)
            await this.setupMediaStream();
            
            // As VIEWER, we need to initiate the WebRTC handshake by creating and sending an SDP offer
            console.log(`[WebRTCManager-${this.instanceId}] 🚀 Creating SDP offer (viewer initiates)...`);
            try {
                // Create offer with proper constraints
                const offerOptions = {
                    offerToReceiveAudio: true,
                    offerToReceiveVideo: false
                };
                
                const offer = await this.peerConnection.createOffer(offerOptions);
                await this.peerConnection.setLocalDescription(offer);
                console.log(`[WebRTCManager-${this.instanceId}] ✅ Local description set (offer)`);
                console.log(`[WebRTCManager-${this.instanceId}] 📋 SDP offer details:`, {
                    type: offer.type,
                    sdpLength: offer.sdp.length
                });
                
                // Send offer to master
                this.signalingClient.sendSdpOffer(offer);
                console.log(`[WebRTCManager-${this.instanceId}] 📤 SDP offer sent to master`);
                
            } catch (error) {
                console.error(`[WebRTCManager-${this.instanceId}] ❌ Error creating SDP offer:`, error);
                if (this.onError) {
                    this.onError(error);
                }
            }
        });

        this.signalingClient.on('sdpAnswer', async (answer, remoteClientId) => {
            console.log(`[WebRTCManager-${this.instanceId}] 📥 Received SDP answer from:`, remoteClientId);
            
            try {
                // Set remote description (answer from master)
                await this.peerConnection.setRemoteDescription(answer);
                console.log(`[WebRTCManager-${this.instanceId}] ✅ Remote description set (answer)`);

            } catch (error) {
                console.error(`[WebRTCManager-${this.instanceId}] ❌ Error handling SDP answer:`, error);
                if (this.onError) {
                    this.onError(error);
                }
            }
        });

        this.signalingClient.on('iceCandidate', async (candidate) => {
            console.log(`[WebRTCManager-${this.instanceId}] 🧊 Received ICE candidate`);
            
            try {
                await this.peerConnection.addIceCandidate(candidate);
            } catch (error) {
                console.error(`[WebRTCManager-${this.instanceId}] ❌ Error adding ICE candidate:`, error);
            }
        });

        this.signalingClient.on('close', () => {
            console.log(`[WebRTCManager-${this.instanceId}] 🔌 Signaling disconnected`);
            this.connectionState = 'disconnected';
            
            if (this.onConnectionStateChange) {
                this.onConnectionStateChange('disconnected');
            }
        });

        this.signalingClient.on('error', (error) => {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Signaling error:`, error);
            
            if (this.onError) {
                this.onError(error);
            }
        });
    }

    /**
     * Set up peer connection event handlers (following official patterns)
     */
    setupPeerConnectionHandlers() {
        this.peerConnection.onconnectionstatechange = () => {
            const state = this.peerConnection.connectionState;
            console.log(`[WebRTCManager-${this.instanceId}] 🔄 Peer connection state: ${state}`);
            
            this.connectionState = state;
            this.isConnected = state === 'connected';
            
            if (state === 'connected') {
                console.log(`[WebRTCManager-${this.instanceId}] 🎉 NATIVE WebRTC connection established!`);
                console.log(`[WebRTCManager-${this.instanceId}] 📊 Connection details:`, {
                    connectionState: this.peerConnection.connectionState,
                    iceConnectionState: this.peerConnection.iceConnectionState,
                    iceGatheringState: this.peerConnection.iceGatheringState,
                    dataChannelState: this.dataChannel ? this.dataChannel.readyState : 'none'
                });
                this.startConnectionMonitoring();
            } else if (state === 'failed' || state === 'disconnected') {
                console.log(`[WebRTCManager-${this.instanceId}] ❌ Connection ${state}`);
                this.stopConnectionMonitoring();
            }
            
            if (this.onConnectionStateChange) {
                this.onConnectionStateChange(state);
            }
        };

        this.peerConnection.ontrack = (event) => {
            console.log(`[WebRTCManager-${this.instanceId}] 🎵 Remote track received:`, event.track.kind);
            
            if (event.track.kind === 'audio') {
                this.remoteStream = event.streams[0];
                
                // Handle remote audio track (native WebRTC audio)
                if (this.onRemoteAudioTrack) {
                    this.onRemoteAudioTrack(event.track, event.streams[0]);
                }
                
                // Auto-play remote audio (following official patterns)
                this.playRemoteAudio(event.streams[0]);
            }
        };

        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                console.log(`[WebRTCManager-${this.instanceId}] 🧊 Sending ICE candidate`);
                this.signalingClient.sendIceCandidate(event.candidate);
            }
        };

        this.peerConnection.oniceconnectionstatechange = () => {
            const iceState = this.peerConnection.iceConnectionState;
            console.log(`[WebRTCManager-${this.instanceId}] 🧊 ICE connection state: ${iceState}`);
            
            if (iceState === 'connected' || iceState === 'completed') {
                console.log(`[WebRTCManager-${this.instanceId}] ✅ ICE connection established`);
                this.connectionMonitor.lastSuccessfulCheck = Date.now();
            } else if (iceState === 'failed') {
                console.error(`[WebRTCManager-${this.instanceId}] ❌ ICE connection failed`);
                if (this.onError) {
                    this.onError(new Error('ICE connection failed'));
                }
            }
        };
    }

    /**
     * Set up media stream (following official patterns - simple {audio: true})
     */
    async setupMediaStream() {
        try {
            if (!this.config.sendAudio) {
                console.log(`[WebRTCManager-${this.instanceId}] 🔇 Audio disabled, skipping media setup`);
                return;
            }

            console.log(`[WebRTCManager-${this.instanceId}] 🎥🎤 Getting user media with NATIVE constraints...`);
            
            // Use detailed constraints based on config
            const constraints = {
                audio: this.config.sendAudio ? (this.config.audioConstraints || {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    // Critical: Limit input volume to prevent clipping
                    volume: { ideal: 0.3, max: 0.4 },
                    sampleRate: { ideal: 16000 },  // Nova Sonic default: 16kHz
                    sampleSize: { ideal: 16 },     // Nova Sonic: 16-bit
                    channelCount: { ideal: 1 }     // Nova Sonic: mono
                }) : false,
                video: this.config.sendVideo ? (this.config.videoConstraints || {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    frameRate: { ideal: 30 }
                }) : false
            };

            console.log(`[WebRTCManager-${this.instanceId}] 📋 Requesting ${this.config.sendVideo ? 'camera and ' : ''}${this.config.sendAudio ? 'microphone' : ''} permissions...`);

            console.log(`[WebRTCManager-${this.instanceId}] 📋 NATIVE Media constraints:`, constraints);
            
            // Get user media (native WebRTC)
            this.localStream = await navigator.mediaDevices.getUserMedia(constraints);
            console.log(`[WebRTCManager-${this.instanceId}] ✅ Local stream obtained with NATIVE WebRTC`);
            console.log(`[WebRTCManager-${this.instanceId}] 📊 Stream details:`, {
                id: this.localStream.id,
                tracks: this.localStream.getTracks().length,
                audioTracks: this.localStream.getAudioTracks().length,
                videoTracks: this.localStream.getVideoTracks().length
            });

            // Add tracks to peer connection (native WebRTC)
            this.localStream.getTracks().forEach(track => {
                console.log(`[WebRTCManager-${this.instanceId}] ➕ Adding ${track.kind} track to peer connection (NATIVE)`);
                console.log(`[WebRTCManager-${this.instanceId}] 📊 Track details:`, {
                    kind: track.kind,
                    label: track.label,
                    enabled: track.enabled,
                    readyState: track.readyState
                });
                
                this.peerConnection.addTrack(track, this.localStream);
                
                if (track.kind === 'audio') {
                    // Set up audio transmission monitoring immediately
                    this.setupAudioTransmissionMonitoring(track);
                    
                    if (this.onLocalAudioTrack) {
                        this.onLocalAudioTrack(track, this.localStream);
                    }
                } else if (track.kind === 'video' && this.onLocalVideoTrack) {
                    this.onLocalVideoTrack(track, this.localStream);
                }
            });

            console.log(`[WebRTCManager-${this.instanceId}] 🎵 NATIVE WebRTC audio setup complete - NO CUSTOM PROCESSING!`);

            // Start audio capture with AudioStreamHandler for level monitoring
            await this.audioStreamHandler.startCapture(this.localStream);
            console.log(`[WebRTCManager-${this.instanceId}] 🎤 Started audio capture and level monitoring`);

            // For compatibility: simulate audio data callback (but audio flows natively)
            if (this.onAudioData) {
                console.log(`[WebRTCManager-${this.instanceId}] 📝 Note: Audio flows natively through WebRTC media channel, not data channel events`);
            }

        } catch (error) {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Error setting up media:`, error);
            
            if (error.name === 'NotAllowedError') {
                throw new Error('Microphone access denied. Please grant microphone permissions and refresh the page.');
            } else if (error.name === 'NotFoundError') {
                throw new Error('No microphone found. Please connect a microphone and refresh the page.');
            } else if (error.name === 'OverconstrainedError') {
                console.warn(`[WebRTCManager-${this.instanceId}] ⚠️ Audio constraints too restrictive, trying basic constraints...`);
                
                // Fallback to basic constraints
                try {
                    this.localStream = await navigator.mediaDevices.getUserMedia({
                        audio: true,
                        video: false
                    });
                    
                    console.log(`[WebRTCManager-${this.instanceId}] ✅ Fallback media stream obtained`);
                    
                    // Add tracks to peer connection
                    this.localStream.getTracks().forEach(track => {
                        console.log(`[WebRTCManager-${this.instanceId}] ➕ Adding fallback ${track.kind} track`);
                        this.peerConnection.addTrack(track, this.localStream);
                        
                        if (track.kind === 'audio' && this.onLocalAudioTrack) {
                            this.onLocalAudioTrack(track, this.localStream);
                        }
                    });
                    
                    return; // Success with fallback
                } catch (fallbackError) {
                    throw new Error(`Media setup failed: ${fallbackError.message}`);
                }
            }
            
            throw error;
        }
    }

    /**
     * Play remote audio using native WebRTC (following official patterns)
     */
    playRemoteAudio(stream) {
        try {
            console.log(`[WebRTCManager-${this.instanceId}] 🔊 Setting up NATIVE remote audio playback...`);
            
            // Create audio element for remote stream (official pattern)
            const audioElement = new Audio();
            audioElement.srcObject = stream;
            audioElement.autoplay = true;
            audioElement.muted = false;
            
            // Store reference for cleanup
            this.remoteAudioElement = audioElement;
            
            console.log(`[WebRTCManager-${this.instanceId}] ✅ NATIVE remote audio playback ready`);
            
        } catch (error) {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Error setting up remote audio:`, error);
        }
    }

    /**
     * Set up data channel handlers
     */
    setupDataChannelHandlers() {
        this.dataChannel.onopen = () => {
            console.log(`[WebRTCManager-${this.instanceId}] 📨 Data channel opened - ready for S2S events!`);
            console.log(`[WebRTCManager-${this.instanceId}] 📊 Data channel state:`, {
                label: this.dataChannel.label,
                readyState: this.dataChannel.readyState,
                bufferedAmount: this.dataChannel.bufferedAmount
            });
        };

        this.dataChannel.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                const eventType = Object.keys(message.event || {})[0] || 'unknown';
                console.log(`[WebRTCManager-${this.instanceId}] 📥 Data channel message:`, eventType);
                
                if (this.onDataChannelMessage) {
                    this.onDataChannelMessage(message);
                }
            } catch (error) {
                console.error(`[WebRTCManager-${this.instanceId}] ❌ Error parsing data channel message:`, error);
                console.error(`[WebRTCManager-${this.instanceId}] 📄 Raw message:`, event.data);
            }
        };

        this.dataChannel.onerror = (error) => {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Data channel error:`, error);
            if (this.onError) {
                this.onError(new Error(`Data channel error: ${error}`));
            }
        };

        this.dataChannel.onclose = () => {
            console.log(`[WebRTCManager-${this.instanceId}] 📨 Data channel closed`);
        };

        // Handle incoming data channels from remote peer
        this.peerConnection.ondatachannel = (event) => {
            const channel = event.channel;
            console.log(`[WebRTCManager-${this.instanceId}] 📥 Received data channel:`, channel.label);
            
            // Set up handlers for incoming data channel
            channel.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    if (this.onDataChannelMessage) {
                        this.onDataChannelMessage(message);
                    }
                } catch (error) {
                    console.error(`[WebRTCManager-${this.instanceId}] ❌ Error parsing incoming data channel message:`, error);
                }
            };
        };
    }

    /**
     * Send event through data channel
     */
    async sendEvent(event) {
        try {
            if (!this.dataChannel) {
                throw new Error('Data channel not initialized');
            }
            
            if (this.dataChannel.readyState !== 'open') {
                console.warn(`[WebRTCManager-${this.instanceId}] ⚠️ Data channel not ready (state: ${this.dataChannel.readyState}), queuing event...`);
                
                // Wait for data channel to open (with timeout)
                await new Promise((resolve, reject) => {
                    const timeout = setTimeout(() => {
                        reject(new Error('Data channel open timeout'));
                    }, 5000);
                    
                    if (this.dataChannel.readyState === 'open') {
                        clearTimeout(timeout);
                        resolve();
                        return;
                    }
                    
                    const onOpen = () => {
                        clearTimeout(timeout);
                        this.dataChannel.removeEventListener('open', onOpen);
                        resolve();
                    };
                    
                    this.dataChannel.addEventListener('open', onOpen);
                });
            }

            const message = JSON.stringify(event);
            this.dataChannel.send(message);
            
            const eventType = Object.keys(event.event || {})[0] || 'unknown';
            console.log(`[WebRTCManager-${this.instanceId}] 📤 Event sent:`, eventType, `(${message.length} bytes)`);
            
        } catch (error) {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Error sending event:`, error);
            throw error;
        }
    }

    /**
     * Start connection monitoring
     */
    startConnectionMonitoring() {
        if (this.connectionMonitor.interval) {
            return;
        }

        this.connectionMonitor.interval = setInterval(() => {
            if (this.peerConnection) {
                const connectionState = this.peerConnection.connectionState;
                const iceConnectionState = this.peerConnection.iceConnectionState;
                
                if (connectionState === 'connected' && (iceConnectionState === 'connected' || iceConnectionState === 'completed')) {
                    this.connectionMonitor.lastSuccessfulCheck = Date.now();
                } else {
                    const timeSinceLastSuccess = Date.now() - this.connectionMonitor.lastSuccessfulCheck;
                    if (timeSinceLastSuccess > 30000) { // 30 seconds
                        console.warn(`[WebRTCManager-${this.instanceId}] ⚠️ Connection unhealthy for ${timeSinceLastSuccess}ms`);
                    }
                }
            }
        }, this.connectionMonitor.checkFrequency);
    }

    /**
     * Stop connection monitoring
     */
    stopConnectionMonitoring() {
        if (this.connectionMonitor.interval) {
            clearInterval(this.connectionMonitor.interval);
            this.connectionMonitor.interval = null;
        }
    }

    /**
     * Check if WebRTC is connected
     */
    isWebRTCConnected() {
        return this.isConnected && this.peerConnection && this.peerConnection.connectionState === 'connected';
    }

    /**
     * Check if data channel is ready
     */
    isDataChannelReady() {
        return this.dataChannel && this.dataChannel.readyState === 'open';
    }

    /**
     * Trigger barge-in (interrupt current playback)
     */
    bargeIn() {
        console.log(`[WebRTCManager-${this.instanceId}] 🛑 Barge-in triggered (NATIVE WebRTC)`);
        
        // For native WebRTC audio, reset position but keep audio element ready for new audio
        if (this.remoteAudioElement) {
            // Reset current playback position to clear any buffered audio
            this.remoteAudioElement.currentTime = 0;
            
            // Ensure audio element is ready to play new audio after barge-in
            // Don't pause - let it continue playing the new audio stream
            if (this.remoteAudioElement.paused) {
                this.remoteAudioElement.play().catch(e => {
                    console.warn(`[WebRTCManager-${this.instanceId}] Could not resume audio after barge-in:`, e);
                });
            }
            
            console.log(`[WebRTCManager-${this.instanceId}] 🔄 Audio element reset and ready for new audio`);
        }
    }

    /**
     * Disconnect and cleanup
     */
    disconnect() {
        try {
            console.log(`[WebRTCManager-${this.instanceId}] 🔌 Disconnecting NATIVE WebRTC...`);
            
            this.connectionState = 'disconnected';
            this.isConnected = false;
            
            // Stop connection monitoring
            this.stopConnectionMonitoring();
            
            // Stop audio monitoring
            if (this.audioMonitorInterval) {
                clearInterval(this.audioMonitorInterval);
                this.audioMonitorInterval = null;
            }
            
            // End any active audio transmission session
            this.endAudioTransmissionSession();
            
            // Clean up audio stream handler
            if (this.audioStreamHandler) {
                this.audioStreamHandler.cleanup();
            }
            
            // Close data channel
            if (this.dataChannel) {
                this.dataChannel.close();
                this.dataChannel = null;
            }
            
            // Stop local stream tracks
            if (this.localStream) {
                this.localStream.getTracks().forEach(track => {
                    track.stop();
                    console.log(`[WebRTCManager-${this.instanceId}] 🛑 Stopped ${track.kind} track`);
                });
                this.localStream = null;
            }
            
            // Clean up remote audio element
            if (this.remoteAudioElement) {
                this.remoteAudioElement.srcObject = null;
                this.remoteAudioElement = null;
            }
            
            // Close peer connection
            if (this.peerConnection) {
                this.peerConnection.close();
                this.peerConnection = null;
            }
            
            // Close signaling client
            if (this.signalingClient) {
                this.signalingClient.close();
                this.signalingClient = null;
            }
            
            console.log(`[WebRTCManager-${this.instanceId}] ✅ NATIVE WebRTC disconnected and cleaned up`);
            
        } catch (error) {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Error during disconnect:`, error);
        }
    }

    /**
     * Set up audio transmission monitoring
     */
    setupAudioTransmissionMonitoring(audioTrack) {
        console.log(`[WebRTCManager-${this.instanceId}] 🎤 Setting up audio transmission monitoring...`);
        
        // Don't start monitoring immediately - wait for S2S session to be ready
        // The transmission session will be started when S2S events are properly initialized
        if (audioTrack.enabled && audioTrack.readyState === 'live') {
            console.log(`[WebRTCManager-${this.instanceId}] 🎤 Audio track is live, monitoring ready (waiting for S2S session)`);
        }
        
        // Monitor track enabled state changes
        let lastEnabledState = audioTrack.enabled;
        
        // Use a property observer pattern to detect when audio starts/stops
        const monitorInterval = setInterval(() => {
            const currentEnabled = audioTrack.enabled && audioTrack.readyState === 'live';
            
            if (currentEnabled !== lastEnabledState) {
                if (currentEnabled) {
                    // Only start if S2S session is ready (check if we have a session)
                    // This prevents early audioInput events before S2S initialization
                    console.log(`[WebRTCManager-${this.instanceId}] 🎤 Audio enabled state changed, but waiting for manual start`);
                } else {
                    this.endAudioTransmissionSession();
                }
                lastEnabledState = currentEnabled;
            }
            
            // If transmitting, update stats and log periodically
            if (this.audioTransmissionStats.isTransmitting) {
                this.updateAudioTransmissionStats();
            }
            
        }, 100); // Check every 100ms for responsive UI updates
        
        // Store interval for cleanup
        this.audioMonitorInterval = monitorInterval;
        
        // Also monitor track events
        audioTrack.addEventListener('ended', () => {
            console.log(`[WebRTCManager-${this.instanceId}] 🎤 Audio track ended`);
            this.endAudioTransmissionSession();
            if (this.audioMonitorInterval) {
                clearInterval(this.audioMonitorInterval);
                this.audioMonitorInterval = null;
            }
        });
    }

    /**
     * Start audio transmission session
     */
    startAudioTransmissionSession() {
        if (this.audioTransmissionStats.isTransmitting) {
            return; // Already transmitting
        }
        
        this.audioTransmissionStats.isTransmitting = true;
        this.audioTransmissionStats.sessionStartTime = Date.now();
        this.audioTransmissionStats.currentSessionCount = 0;
        this.audioTransmissionStats.totalDataSize = 0;
        this.audioTransmissionStats.lastLogTime = Date.now();
        
        console.log(`[WebRTCManager-${this.instanceId}] 🎤 Audio transmission started`);
        
        // Trigger audioInput event for Events display
        this.triggerAudioInputEvent('start');
    }

    /**
     * End audio transmission session
     */
    endAudioTransmissionSession() {
        if (!this.audioTransmissionStats.isTransmitting) {
            return; // Not transmitting
        }
        
        const duration = Date.now() - this.audioTransmissionStats.sessionStartTime;
        
        console.log(`[WebRTCManager-${this.instanceId}] 🎤 Audio transmission ended`, {
            duration: `${duration}ms`,
            packetsCount: this.audioTransmissionStats.currentSessionCount,
            totalDataSize: this.audioTransmissionStats.totalDataSize
        });
        
        // Trigger audioInput event for Events display
        this.triggerAudioInputEvent('end');
        
        this.audioTransmissionStats.isTransmitting = false;
        this.audioTransmissionStats.sessionStartTime = null;
    }

    /**
     * Update audio transmission statistics
     */
    updateAudioTransmissionStats() {
        const now = Date.now();
        
        // Simulate audio packet counting (since we can't directly access WebRTC audio packets)
        // Estimate based on 16kHz, 16-bit, mono = ~32KB/sec
        const timeSinceStart = now - this.audioTransmissionStats.sessionStartTime;
        const estimatedPackets = Math.floor(timeSinceStart / 20); // ~50 packets per second (20ms each)
        const estimatedDataSize = Math.floor(timeSinceStart * 32); // ~32 bytes per ms
        
        this.audioTransmissionStats.currentSessionCount = estimatedPackets;
        this.audioTransmissionStats.totalDataSize = estimatedDataSize;
        
        // Log every 2 seconds during transmission
        if (now - this.audioTransmissionStats.lastLogTime > 2000) {
            console.log(`[WebRTCManager-${this.instanceId}] 🎤 Audio transmitting (${estimatedPackets} packets, ${estimatedDataSize} bytes)`);
            this.audioTransmissionStats.lastLogTime = now;
            
            // Update Events display
            this.triggerAudioInputEvent('update');
        }
    }

    /**
     * Trigger audioInput event for Events display
     */
    triggerAudioInputEvent(action) {
        if (this.onAudioInputEvent) {
            const eventData = {
                action: action, // 'start', 'update', 'end'
                isTransmitting: this.audioTransmissionStats.isTransmitting,
                packetsCount: this.audioTransmissionStats.currentSessionCount,
                dataSize: this.audioTransmissionStats.totalDataSize,
                duration: this.audioTransmissionStats.sessionStartTime ? 
                    Date.now() - this.audioTransmissionStats.sessionStartTime : 0
            };
            
            this.onAudioInputEvent(eventData);
        }
    }

    /**
     * Get current audio transmission stats
     */
    getAudioTransmissionStats() {
        return { ...this.audioTransmissionStats };
    }

    /**
     * Get connection statistics
     */
    async getStats() {
        if (!this.peerConnection) {
            return null;
        }

        try {
            const stats = await this.peerConnection.getStats();
            const result = {
                connection: this.peerConnection.connectionState,
                ice: this.peerConnection.iceConnectionState,
                gathering: this.peerConnection.iceGatheringState,
                signaling: this.peerConnection.signalingState,
                dataChannel: this.dataChannel ? this.dataChannel.readyState : 'none',
                tracks: {
                    local: this.localStream ? this.localStream.getTracks().length : 0,
                    remote: this.remoteStream ? this.remoteStream.getTracks().length : 0
                },
                statsCount: stats.size
            };
            
            return result;
        } catch (error) {
            console.error(`[WebRTCManager-${this.instanceId}] ❌ Error getting stats:`, error);
            return null;
        }
    }

    /**
     * Debug connection status
     */
    debugConnectionStatus() {
        console.log(`[WebRTCManager-${this.instanceId}] 🔍 CONNECTION DEBUG:`);
        console.log(`[WebRTCManager-${this.instanceId}] - Signaling Client:`, !!this.signalingClient);
        console.log(`[WebRTCManager-${this.instanceId}] - Peer Connection:`, !!this.peerConnection);
        console.log(`[WebRTCManager-${this.instanceId}] - Local Stream:`, !!this.localStream);
        console.log(`[WebRTCManager-${this.instanceId}] - Data Channel:`, !!this.dataChannel);
        
        if (this.peerConnection) {
            console.log(`[WebRTCManager-${this.instanceId}] - Connection State:`, this.peerConnection.connectionState);
            console.log(`[WebRTCManager-${this.instanceId}] - ICE Connection State:`, this.peerConnection.iceConnectionState);
            console.log(`[WebRTCManager-${this.instanceId}] - ICE Gathering State:`, this.peerConnection.iceGatheringState);
            console.log(`[WebRTCManager-${this.instanceId}] - Signaling State:`, this.peerConnection.signalingState);
        }
        
        if (this.dataChannel) {
            console.log(`[WebRTCManager-${this.instanceId}] - Data Channel State:`, this.dataChannel.readyState);
            console.log(`[WebRTCManager-${this.instanceId}] - Data Channel Label:`, this.dataChannel.label);
        }
    }
}

export default WebRTCManager;