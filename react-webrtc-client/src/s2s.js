/**
 * S2sChatBot - Nova Sonic Speech-to-Speech with NATIVE WebRTC
 * 
 * UPDATED: Now uses native WebRTC patterns following official KVS SDK examples
 * - Simple {audio: true} constraints
 * - No custom audio processing (ScriptProcessorNode removed)
 * - Direct media stream handling
 * - Native WebRTC audio playback
 * 
 * This should eliminate digital noise and audio clipping issues.
 */

import React from 'react';
import './s2s.css'
import { Icon, Alert, Button, Modal, Box, SpaceBetween, Container, ColumnLayout, Header, FormField, Select, Textarea, Checkbox } from '@cloudscape-design/components';
import S2sEvent from './helper/s2sEvents';
import Meter from './components/meter';
import S2sEventDisplay from './components/eventDisplay';
import WebRTCManager from './helper/WebRTCManager'; // Now uses NATIVE WebRTC patterns
import logExporter from './helper/LogExporter';

class S2sChatBot extends React.Component {

    constructor(props) {
        super(props);
        this.state = {
            status: "loading", // null, loading, loaded
            alert: null,
            sessionStarted: false,
            showEventJson: false,
            showConfig: false,
            selectedEvent: null,

            chatMessages: {},
            events: [],
            audioChunks: [],
            audioPlayPromise: null,
            includeChatHistory: false,

            promptName: null,
            textContentName: null,
            audioContentName: null,
            audioInputReady: false, // Flag to control when to start sending audioInput events

            showUsage: true,

            // S2S config items
            configAudioInput: null,
            configSystemPrompt: S2sEvent.DEFAULT_SYSTEM_PROMPT,
            configAudioOutput: S2sEvent.DEFAULT_AUDIO_OUTPUT_CONFIG,
            configVoiceIdOption: { label: "Matthew (en-US)", value: "matthew" },
            configToolUse: JSON.stringify(S2sEvent.DEFAULT_TOOL_CONFIG, null, 2),
            configChatHistory: JSON.stringify(S2sEvent.DEFAULT_CHAT_HISTORY, null, 2),

            // WebRTC config items
            configChannelName: process.env.REACT_APP_KVS_CHANNEL_NAME || 'nova-s2s-channel',
            configRegion: process.env.REACT_APP_AWS_REGION || 'ap-northeast-1',
            configAccessKeyId: process.env.REACT_APP_AWS_ACCESS_KEY_ID || '',
            configSecretAccessKey: process.env.REACT_APP_AWS_SECRET_ACCESS_KEY || '',
            configSessionToken: process.env.REACT_APP_AWS_SESSION_TOKEN || '',
        };
        this.webrtcManager = new WebRTCManager(); // Now uses NATIVE WebRTC patterns
        this.mediaRecorder = null;
        this.chatMessagesEndRef = React.createRef();
        this.stateRef = React.createRef();  
        this.eventDisplayRef = React.createRef();
        this.meterRef = React.createRef();
        this.audioHandlingSetup = false; // Track if audio handling is set up
        // AudioPlayer removed - using native WebRTC audio playback
    }

    componentDidMount() {
        this.stateRef.current = this.state;
        // Native WebRTC audio - no manual audio player initialization needed
        
        // Load configuration from localStorage if available
        this.loadConfiguration();
        
        // Add keyboard shortcut for quick log export (Ctrl+Shift+L)
        const handleKeyDown = (event) => {
            if (event.ctrlKey && event.shiftKey && event.key === 'L') {
                event.preventDefault();
                console.log('[S2sChatBot] Quick log export triggered (Ctrl+Shift+L)');
                logExporter.autoExportToLogsFolder().catch(err => {
                    console.warn('[S2sChatBot] Quick export failed:', err);
                });
            }
        };
        
        document.addEventListener('keydown', handleKeyDown);
        this.keydownHandler = handleKeyDown; // Store for cleanup
        
        logExporter.info('S2sChatBot', '🚀 S2sChatBot component mounted with NATIVE WebRTC', {
            sessionId: logExporter.sessionId,
            keyboardShortcut: 'Ctrl+Shift+L for quick log export',
            webrtcType: 'NATIVE WebRTC (no custom audio processing)',
            audioHandling: 'Native WebRTC media streams'
        });
    }

    loadConfiguration() {
        try {
            const savedConfig = localStorage.getItem('nova-s2s-webrtc-config');
            if (savedConfig) {
                const config = JSON.parse(savedConfig);
                this.setState({
                    configChannelName: config.channelName || this.state.configChannelName,
                    configRegion: config.region || this.state.configRegion,
                    configAccessKeyId: config.accessKeyId || this.state.configAccessKeyId,
                    configSecretAccessKey: config.secretAccessKey || this.state.configSecretAccessKey,
                    configSessionToken: config.sessionToken || this.state.configSessionToken,
                });
                console.log('[S2sChatBot] Configuration loaded from localStorage');
            }
        } catch (error) {
            console.warn('[S2sChatBot] Error loading configuration:', error);
        }
    }

    saveConfiguration() {
        try {
            const config = {
                channelName: this.state.configChannelName,
                region: this.state.configRegion,
                accessKeyId: this.state.configAccessKeyId,
                secretAccessKey: this.state.configSecretAccessKey,
                sessionToken: this.state.configSessionToken,
            };
            localStorage.setItem('nova-s2s-webrtc-config', JSON.stringify(config));
            console.log('[S2sChatBot] Configuration saved to localStorage');
        } catch (error) {
            console.warn('[S2sChatBot] Error saving configuration:', error);
        }
    }

    validateWebRTCConfiguration() {
        const errors = [];
        
        if (!this.state.configChannelName || this.state.configChannelName.trim() === '') {
            errors.push('KVS Channel Name is required');
        }
        
        if (!this.state.configRegion || this.state.configRegion.trim() === '') {
            errors.push('AWS Region is required');
        }
        
        if (!this.state.configAccessKeyId || this.state.configAccessKeyId.trim() === '') {
            errors.push('AWS Access Key ID is required');
        }
        
        if (!this.state.configSecretAccessKey || this.state.configSecretAccessKey.trim() === '') {
            errors.push('AWS Secret Access Key is required');
        }
        
        // Validate region format
        if (this.state.configRegion && !/^[a-z0-9-]+$/.test(this.state.configRegion.trim())) {
            errors.push('AWS Region format is invalid (e.g., ap-northeast-1)');
        }
        
        // Validate access key format
        if (this.state.configAccessKeyId && !/^AKIA[0-9A-Z]{16}$/.test(this.state.configAccessKeyId.trim())) {
            errors.push('AWS Access Key ID format is invalid (should start with AKIA)');
        }
        
        return errors;
    }

    async testWebRTCConfiguration() {
        let testWebRTCManager = null;
        
        try {
            this.setState({alert: null});
            
            // Validate configuration first
            const configErrors = this.validateWebRTCConfiguration();
            if (configErrors.length > 0) {
                this.setState({alert: `Configuration errors: ${configErrors.join(', ')}`});
                return;
            }

            console.log('[S2sChatBot] Testing WebRTC configuration...');
            
            // Create a temporary WebRTC manager for testing
            testWebRTCManager = new WebRTCManager();
            
            const testConfig = {
                channelName: this.state.configChannelName.trim(),
                region: this.state.configRegion.trim(),
                credentials: {
                    accessKeyId: this.state.configAccessKeyId.trim(),
                    secretAccessKey: this.state.configSecretAccessKey.trim(),
                    sessionToken: this.state.configSessionToken ? this.state.configSessionToken.trim() : undefined
                },
                clientId: `test-viewer-${crypto.randomUUID()}`,
                sendAudio: true, // Enable audio for comprehensive test
                sendVideo: true, // Enable video for comprehensive test
                audioConstraints: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                    sampleRate: 16000,        // Nova Sonic: 16kHz
                    sampleSize: 16,           // Nova Sonic: 16-bit
                    channelCount: 1           // Nova Sonic: mono (single channel)
                },
                videoConstraints: {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    frameRate: { ideal: 30 }
                }
            };

            // Set up test error handler
            testWebRTCManager.onError = (error) => {
                console.error('[S2sChatBot] WebRTC test error:', error);
                this.setState({alert: `WebRTC test failed: ${error.message}`});
            };

            // Set up test connection handler
            testWebRTCManager.onConnectionStateChange = (state) => {
                console.log('[S2sChatBot] WebRTC test connection state:', state);
                if (state === 'connected') {
                    this.setState({alert: 'WebRTC connected ✅ Testing data channel...'});
                    
                    // Show debug info
                    setTimeout(() => {
                        testWebRTCManager.debugConnectionStatus();
                    }, 500);
                    
                    // Start comprehensive testing
                    this.runComprehensiveTest(testWebRTCManager);
                    
                } else if (state === 'failed') {
                    this.setState({alert: 'WebRTC connection test failed ❌ Check console for details.'});
                    
                    // Show debug info on failure
                    setTimeout(() => {
                        testWebRTCManager.debugConnectionStatus();
                    }, 500);
                    
                    // Also disconnect on failure
                    testWebRTCManager.disconnect();
                } else if (state === 'connecting') {
                    this.setState({alert: 'Testing WebRTC connection... ⏳'});
                }
            };

            // Attempt connection with proper cleanup
            try {
                await testWebRTCManager.connect(testConfig);
            } finally {
                // Ensure test manager is always cleaned up after a delay - longer for loopback
                setTimeout(() => {
                    testWebRTCManager.disconnect();
                }, 20000); // Extended to 20 seconds for media recording
            }
            
        } catch (error) {
            console.error('[S2sChatBot] WebRTC configuration test error:', error);
            this.setState({alert: `WebRTC test error: ${error.message}`});
            
            // Clean up test manager on error
            if (testWebRTCManager) {
                testWebRTCManager.disconnect();
            }
        }
    }

    async runComprehensiveTest(testWebRTCManager) {
        try {
            console.log('[S2sChatBot] 🧪 Starting comprehensive WebRTC test...');
            
            // Step 1: Wait for data channel to be ready
            this.setState({alert: 'Data channel connecting... ⏳'});
            
            const dataChannelReady = await this.waitForDataChannelReady(testWebRTCManager, 10000);
            if (!dataChannelReady) {
                this.setState({alert: 'Data channel test failed ❌ Timeout waiting for data channel'});
                testWebRTCManager.disconnect();
                return;
            }
            
            console.log('[S2sChatBot] ✅ Data channel ready!');
            this.setState({alert: 'Data channel ready ✅ Testing S2S events...'});
            
            // Step 2: Test S2S event messaging
            const eventTestSuccess = await this.testS2SEvents(testWebRTCManager);
            if (!eventTestSuccess) {
                this.setState({alert: 'S2S event test failed ❌ Check console for details'});
                testWebRTCManager.disconnect();
                return;
            }
            
            console.log('[S2sChatBot] ✅ S2S events working!');
            this.setState({alert: 'S2S events working ✅ Testing audio transmission...'});
            
            // Step 3: Test audio transmission (short burst)
            const audioTestSuccess = await this.testAudioTransmission(testWebRTCManager);
            if (!audioTestSuccess) {
                this.setState({alert: 'Audio test failed ❌ Check console for details'});
                testWebRTCManager.disconnect();
                return;
            }
            
            console.log('[S2sChatBot] ✅ Audio transmission working!');
            this.setState({alert: 'Media test completed ✅ Server is saving MP4 file... 💾'});
            
            // Disconnect after successful test - wait longer for loopback audio
            setTimeout(() => {
                console.log('[S2sChatBot] Disconnecting test connection...');
                testWebRTCManager.disconnect();
                this.setState({alert: 'Test completed successfully ✅'});
            }, 15000); // Wait 15 seconds for media recording completion (10s recording + 5s buffer)
            
        } catch (error) {
            console.error('[S2sChatBot] Comprehensive test error:', error);
            this.setState({alert: `Test failed ❌ ${error.message}`});
            testWebRTCManager.disconnect();
        }
    }

    async waitForDataChannelReady(testWebRTCManager, timeout = 10000) {
        return new Promise((resolve) => {
            const startTime = Date.now();
            
            const checkDataChannel = () => {
                if (testWebRTCManager.isDataChannelReady()) {
                    console.log('[S2sChatBot] ✅ Data channel is ready');
                    resolve(true);
                    return;
                }
                
                if (Date.now() - startTime > timeout) {
                    console.log('[S2sChatBot] ❌ Data channel timeout');
                    resolve(false);
                    return;
                }
                
                setTimeout(checkDataChannel, 500);
            };
            
            checkDataChannel();
        });
    }

    async testS2SEvents(testWebRTCManager) {
        try {
            console.log('[S2sChatBot] 🧪 Testing S2S event messaging...');
            
            // Set up message handler to verify events are received
            let eventReceived = false;
            let receivedAcks = [];
            const originalHandler = testWebRTCManager.onDataChannelMessage;
            
            testWebRTCManager.onDataChannelMessage = (message) => {
                console.log('[S2sChatBot] ✅ Test response received:', message);
                
                if (message.type === 'TEST_ACK') {
                    console.log(`[S2sChatBot] 🎉 Test acknowledgment: ${message.eventType} - ${message.message}`);
                    receivedAcks.push(message.eventType);
                    eventReceived = true;
                } else if (message.type === 'TEST_AUDIO_START') {
                    console.log(`[S2sChatBot] 🔊 Test audio playback starting: ${message.message}`);
                    // Audio will be received via WebRTC media channel automatically
                } else {
                    console.log('[S2sChatBot] ✅ Other test response:', message);
                    eventReceived = true;
                }
                
                // Don't restore handler immediately - wait for all acks
            };
            
            // Send test events
            const testEvents = [
                S2sEvent.sessionStart(),
                S2sEvent.promptStart('test_prompt'),
                S2sEvent.contentStartText('test_prompt', 'test_content'),
                S2sEvent.textInput('test_prompt', 'test_content', 'This is a test message'),
                S2sEvent.contentEnd('test_prompt', 'test_content')
            ];
            
            for (const event of testEvents) {
                console.log('[S2sChatBot] 📤 Sending test event:', Object.keys(event.event)[0]);
                await testWebRTCManager.sendEvent(event);
                await new Promise(resolve => setTimeout(resolve, 200)); // Small delay between events
            }
            
            // Wait for responses (with timeout)
            const responseTimeout = 8000; // Longer timeout for multiple events
            const startTime = Date.now();
            const expectedAcks = ['sessionStart', 'promptStart', 'contentStart', 'textInput', 'contentEnd'];
            
            while (receivedAcks.length < expectedAcks.length && (Date.now() - startTime) < responseTimeout) {
                await new Promise(resolve => setTimeout(resolve, 200));
            }
            
            // Restore original handler
            if (originalHandler) {
                testWebRTCManager.onDataChannelMessage = originalHandler;
            }
            
            if (receivedAcks.length >= 3) { // At least 3 events acknowledged
                console.log(`[S2sChatBot] ✅ S2S event messaging test passed - ${receivedAcks.length} events acknowledged:`, receivedAcks);
                console.log(`[S2sChatBot] 🔊 Test audio should start playing from server after contentEnd event`);
                return true;
            } else {
                console.log(`[S2sChatBot] ❌ S2S event messaging test failed - only ${receivedAcks.length} events acknowledged:`, receivedAcks);
                return false;
            }
            
        } catch (error) {
            console.error('[S2sChatBot] S2S event test error:', error);
            return false;
        }
    }

    async testAudioTransmission(testWebRTCManager) {
        try {
            console.log('[S2sChatBot] 🧪 Testing audio transmission...');
            
            // Check if we have local audio stream
            if (!testWebRTCManager.localStream) {
                console.log('[S2sChatBot] ❌ No local audio stream available');
                return false;
            }
            
            const audioTracks = testWebRTCManager.localStream.getAudioTracks();
            if (audioTracks.length === 0) {
                console.log('[S2sChatBot] ❌ No audio tracks available');
                return false;
            }
            
            console.log('[S2sChatBot] ✅ Audio tracks available:', audioTracks.length);
            
            // Test audio and video for 10 seconds
            const testDuration = 10000;
            console.log(`[S2sChatBot] 🎥🎤 Testing audio and video transmission for ${testDuration}ms...`);
            console.log(`[S2sChatBot] 📹 VIDEO: Camera will be activated for recording`);
            console.log(`[S2sChatBot] 🎤 AUDIO: Nova Sonic format - 16kHz, 16-bit, mono`);
            console.log(`[S2sChatBot] 🎤 AUDIO: Linear PCM (LPCM) compatible`);
            console.log(`[S2sChatBot] 🎤 AUDIO: Speak clearly and loudly for best results!`);
            console.log(`[S2sChatBot] 📝 Server will save data as MP4 file in logs/media_test/`);
            
            // Enable audio track
            audioTracks.forEach(track => {
                track.enabled = true;
                console.log('[S2sChatBot] 📊 Audio track enabled:', {
                    label: track.label,
                    kind: track.kind,
                    readyState: track.readyState,
                    enabled: track.enabled
                });
            });
            
            // Show progress during test
            const progressInterval = setInterval(() => {
                const elapsed = Date.now() - Date.now() + testDuration;
                console.log(`[S2sChatBot] 🎤 Audio test in progress... (${Math.max(0, testDuration - elapsed)}ms remaining)`);
            }, 1000);
            
            // Wait for test duration
            await new Promise(resolve => setTimeout(resolve, testDuration));
            
            clearInterval(progressInterval);
            
            // Disable audio track
            audioTracks.forEach(track => {
                track.enabled = false;
                console.log('[S2sChatBot] 🔇 Audio track disabled');
            });
            
            console.log('[S2sChatBot] ✅ Audio transmission test completed');
            console.log('[S2sChatBot] 📁 Check server logs and logs/test_audio/ folder for saved audio files');
            console.log('[S2sChatBot] 🔄 In loopback mode: Wait 2 seconds for audio playback...');
            console.log('[S2sChatBot] 🔊 You should hear your voice played back from the server');
            return true;
            
        } catch (error) {
            console.error('[S2sChatBot] Audio transmission test error:', error);
            return false;
        }
    }

    componentWillUnmount() {
        // Native WebRTC audio cleanup handled by WebRTCManager
        if (this.webrtcManager) {
            this.webrtcManager.disconnect();
        }
        
        // Clean up keyboard event listener
        if (this.keydownHandler) {
            document.removeEventListener('keydown', this.keydownHandler);
        }
        
        logExporter.info('S2sChatBot', '🔄 S2sChatBot component unmounting');
    }


    componentDidUpdate(prevProps, prevState) {
        this.stateRef.current = this.state; 

        if (Object.keys(prevState.chatMessages).length !== Object.keys(this.state.chatMessages).length) {
            this.chatMessagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }
    
    async sendEvent(event) {
        let eventType = 'unknown'; // Declare eventType outside try block
        try {
            eventType = Object.keys(event?.event || {})[0] || 'unknown';
            
            // Enhanced logging
            logExporter.info('S2sChatBot', `📤 SENDING S2S EVENT: ${eventType}`, {
                eventType,
                webrtcConnected: this.webrtcManager?.isWebRTCConnected(),
                dataChannelReady: this.webrtcManager?.isDataChannelReady(),
                event: event
            });
            
            if (this.webrtcManager && this.webrtcManager.isWebRTCConnected() && this.webrtcManager.isDataChannelReady()) {
                logExporter.info('S2sChatBot', `🔗 WebRTC ready, sending ${eventType} event`, {
                    eventType
                });
                
                await this.webrtcManager.sendEvent(event);
                this.eventDisplayRef.current.displayEvent(event, "out");
                
                logExporter.info('S2sChatBot', `✅ SUCCESS: ${eventType} event sent`, {
                    eventType
                });
            } else {
                logExporter.warn('S2sChatBot', `❌ FAILED: WebRTC not ready for ${eventType} event`, {
                    eventType,
                    connected: this.webrtcManager?.isWebRTCConnected(),
                    dataChannelReady: this.webrtcManager?.isDataChannelReady()
                });
            }
        } catch (error) {
            logExporter.error('S2sChatBot', `❌ ERROR sending ${eventType} event: ${error.message}`, {
                error: error.message,
                stack: error.stack
            });
            this.setState({alert: `Error sending event: ${error.message}`});
        }
    }
    
    cancelAudio() {
        // Use NATIVE WebRTC manager's barge-in functionality
        if (this.webrtcManager) {
            this.webrtcManager.bargeIn();
        }
        // Native WebRTC audio - barge-in handled by WebRTCManager
        this.setState({ isPlaying: false });
    }

    async handleIncomingMessage (message) {
        console.log('[S2sChatBot] 📥 handleIncomingMessage called with:', message);
        console.log('[S2sChatBot] 🔍 Message structure analysis:');
        console.log('  - Message keys:', Object.keys(message || {}));
        console.log('  - Message.event type:', typeof message?.event);
        console.log('  - Message.event keys:', Object.keys(message?.event || {}));
        console.log('  - Full message.event:', JSON.stringify(message?.event, null, 2));
        
        if (!message || !message.event) {
            console.warn('[S2sChatBot] ⚠️ Invalid message structure:', message);
            return;
        }
        
        const eventType = Object.keys(message?.event)[0];
        console.log(`[S2sChatBot] 🎯 Processing Nova event: ${eventType}`);
        
        // Special debug for completion events
        if (eventType === "completionStart" || eventType === "completionEnd") {
            console.log(`[S2sChatBot] ⭐ COMPLETION EVENT RECEIVED: ${eventType}`, message);
        }
        
        const eventData = message.event[eventType];
        console.log(`[S2sChatBot] 🔍 EventData:`, eventData);
        
        const role = eventData?.role;
        const content = eventData?.content;
        const contentId = eventData?.contentId;
        let stopReason = eventData?.stopReason;
        const contentType = eventData?.type;
        var chatMessages = this.state.chatMessages;
        
        // Debug logging for conversation window issues
        console.log(`[S2sChatBot] 🔍 Event details - Type: ${eventType}, ContentId: ${contentId}, Role: ${role}, ContentType: ${contentType}`);
        console.log(`[S2sChatBot] 🔍 Current chatMessages keys:`, Object.keys(chatMessages));
        if (eventType === 'textOutput') {
            console.log(`[S2sChatBot] 🔍 TextOutput - Content: "${content?.substring(0, 100)}..."`);
            console.log(`[S2sChatBot] 🔍 TextOutput - Has contentId in chatMessages: ${chatMessages.hasOwnProperty(contentId)}`);
        }

        switch(eventType) {
            case "textOutput": 
                console.log(`[S2sChatBot] 📝 TextOutput - ContentId: ${contentId}, Content: "${content?.substring(0, 100)}..."`);
                
                // Detect interruption
                if (role === "ASSISTANT" && content.startsWith("{")) {
                    const evt = JSON.parse(content);
                    if (evt.interrupted === true) {
                        this.cancelAudio()
                    }
                }

                if (chatMessages.hasOwnProperty(contentId)) {
                    console.log(`[S2sChatBot] ✅ Updating existing chatMessage for contentId: ${contentId}`);
                    chatMessages[contentId].content = content;
                    chatMessages[contentId].role = role;
                    if (chatMessages[contentId].raw === undefined)
                        chatMessages[contentId].raw = [];
                    chatMessages[contentId].raw.push(message);
                } else {
                    console.log(`[S2sChatBot] ⚠️ No existing chatMessage for contentId: ${contentId}, creating new one`);
                    // Create new chat message entry if contentStart was missed
                    chatMessages[contentId] = {
                        "content": content,
                        "role": role,
                        "raw": [message],
                    };
                }
                console.log(`[S2sChatBot] 🔍 ChatMessages after textOutput:`, Object.keys(chatMessages));
                this.setState({chatMessages: chatMessages});
                break;
            case "audioOutput":
                // NOTE: Audio output now flows through WebRTC media channel, not data channel events
                // The remote audio track is automatically handled by AudioStreamHandler.handleRemoteAudioTrack()
                console.log('[S2sChatBot] 🔊 Audio output event received (audio flows via WebRTC media channel)');
                break;
            case "contentStart":
                console.log(`[S2sChatBot] 🚀 ContentStart - Type: ${contentType}, ContentId: ${contentId}, Role: ${role}`);
                if (contentType === "TEXT") {
                    var generationStage = "";
                    if (message.event.contentStart.additionalModelFields) {
                        generationStage = JSON.parse(message.event.contentStart.additionalModelFields)?.generationStage;
                    }

                    chatMessages[contentId] =  {
                        "content": "", 
                        "role": role,
                        "generationStage": generationStage,
                        "raw": [],
                    };
                    chatMessages[contentId].raw.push(message);
                    console.log(`[S2sChatBot] ✅ Created chatMessage entry for contentId: ${contentId}`);
                    console.log(`[S2sChatBot] 🔍 Updated chatMessages keys:`, Object.keys(chatMessages));
                    this.setState({chatMessages: chatMessages});
                } else {
                    console.log(`[S2sChatBot] ⚠️ ContentStart ignored - not TEXT type: ${contentType}`);
                }
                break;
            case "contentEnd":
                if (contentType === "TEXT") {
                    if (chatMessages.hasOwnProperty(contentId)) {
                        if (chatMessages[contentId].raw === undefined)
                            chatMessages[contentId].raw = [];
                        chatMessages[contentId].raw.push(message);
                        chatMessages[contentId].stopReason = stopReason;
                    }
                    this.setState({chatMessages: chatMessages});
                }
                break;
            case "usageEvent":
                if (this.meterRef.current) { 
                    this.meterRef.current.updateMeter(message);
                    if (this.state.showUsage === false) {
                        this.setState({showUsage: true});
                    }
                }
                break;
            case "completionStart":
                console.log('[S2sChatBot] 🎯 Nova completionStart event received:', message);
                logExporter.info('S2sChatBot', '🎯 Nova completionStart event', { event: message });
                break;
            case "completionEnd":
                console.log('[S2sChatBot] 🏁 Nova completionEnd event received:', message);
                logExporter.info('S2sChatBot', '🏁 Nova completionEnd event', { event: message });
                break;
            case "toolUse":
                console.log('[S2sChatBot] 🔧 Nova toolUse event received:', message);
                logExporter.info('S2sChatBot', '🔧 Nova toolUse event', { event: message });
                break;
            default:
                // Log all unhandled Nova events for debugging
                console.log(`[S2sChatBot] 📨 Unhandled Nova event type: ${eventType}`, message);
                logExporter.info('S2sChatBot', `📨 Unhandled Nova event: ${eventType}`, { 
                    eventType, 
                    event: message 
                });
                break;

        }

        this.eventDisplayRef.current.displayEvent(message, "in");
    }

    handleSessionChange = async (e) => {
        console.log(`[S2sChatBot] Session change requested: ${this.state.sessionStarted ? 'END' : 'START'} conversation`);
        
        if (this.state.sessionStarted) {
            // End session
            try {
                console.log('[S2sChatBot] Ending session...');
                await this.endSession();
                this.cancelAudio();
                if (this.meterRef.current) this.meterRef.current.stop();
                // Native WebRTC audio - no manual audio player restart needed
                console.log('[S2sChatBot] Session ended successfully');
            } catch (error) {
                console.error('[S2sChatBot] Error ending session:', error);
                this.setState({alert: `Error ending session: ${error.message}`});
                // Still try to disconnect WebRTC even if there was an error
                if (this.webrtcManager) {
                    this.webrtcManager.disconnect();
                }
            }
        }
        else {
            // Start session
            console.log('[S2sChatBot] Starting session...');
            this.setState({
                chatMessages:{}, 
                events: [], 
            });
            if (this.eventDisplayRef.current) this.eventDisplayRef.current.cleanup();
            if (this.meterRef.current) this.meterRef.current.start();
            
            // Init WebRTC connection
            try {
                if (!this.webrtcManager.isWebRTCConnected()) {
                    await this.connectWebRTC();
                    // Audio handling will be set up when connection is fully established
                    // via the onConnectionStateChange callback
                }
                console.log('[S2sChatBot] Session started successfully');
            } catch (error) {
                console.error('Error connecting WebRTC: ', error);
                this.setState({alert: `WebRTC connection failed: ${error.message}`});
                return; // Don't change session state if connection failed
            }
        }
        
        // Always update session state
        console.log(`[S2sChatBot] Updating session state: ${this.state.sessionStarted} -> ${!this.state.sessionStarted}`);
        this.setState({sessionStarted: !this.state.sessionStarted});
    }

    async connectWebRTC() {
        try {
            console.log('[S2sChatBot] Connecting to WebRTC...');
            
            // Validate WebRTC configuration
            const configErrors = this.validateWebRTCConfiguration();
            if (configErrors.length > 0) {
                throw new Error(`WebRTC configuration errors: ${configErrors.join(', ')}`);
            }
            
            // Use fixed names that match WebRTC server expectations
            const promptName = "webrtc_prompt";
            const textContentName = "system_content";
            const audioContentName = "audio_input";
            this.setState({
                promptName: promptName,
                textContentName: textContentName,
                audioContentName: audioContentName
            });

            // Prepare NATIVE WebRTC configuration (simplified)
            const webrtcConfig = {
                channelName: this.state.configChannelName.trim(),
                region: this.state.configRegion.trim(),
                credentials: {
                    accessKeyId: this.state.configAccessKeyId.trim(),
                    secretAccessKey: this.state.configSecretAccessKey.trim(),
                    sessionToken: this.state.configSessionToken ? this.state.configSessionToken.trim() : undefined
                },
                clientId: `viewer-${crypto.randomUUID()}`,
                sendAudio: true // Simple flag - let WebRTC handle everything natively
            };

            // Set up WebRTC event handlers
            this.webrtcManager.onConnectionStateChange = (state) => {
                console.log('[S2sChatBot] WebRTC connection state:', state);
                if (state === 'connected') {
                    // Set up audio handling now that connection is fully established
                    this.setupWebRTCAudioHandling();
                    // Wait for data channel to be ready before initializing S2S session
                    this.waitForDataChannelAndInitializeS2S();
                } else if (state === 'disconnected' || state === 'failed') {
                    this.setState({alert: 'WebRTC connection lost'});
                }
            };

            this.webrtcManager.onDataChannelMessage = (message) => {
                this.handleIncomingMessage(message);
            };

            this.webrtcManager.onError = (error) => {
                console.error('[S2sChatBot] WebRTC error:', error);
                this.setState({alert: `WebRTC Error: ${error.message}`});
            };

            this.webrtcManager.onAudioLevel = (level) => {
                // Update audio level visualization if needed
                if (this.meterRef.current) {
                    this.meterRef.current.updateAudioLevel(level);
                }
            };

            // Connect to WebRTC
            await this.webrtcManager.connect(webrtcConfig);
            
            console.log('[S2sChatBot] WebRTC connected successfully');
            
            // Set up audio handling immediately as backup (in case onConnectionStateChange doesn't fire)
            setTimeout(() => {
                if (!this.audioHandlingSetup) {
                    console.log('[S2sChatBot] Setting up audio handling as backup...');
                    this.setupWebRTCAudioHandling();
                }
            }, 1000);
            
            // Debug connection status after 2 seconds
            setTimeout(() => {
                this.webrtcManager.debugConnectionStatus();
            }, 2000);

        } catch (error) {
            console.error('[S2sChatBot] Error connecting WebRTC:', error);
            throw error;
        }
    }

    async waitForDataChannelAndInitializeS2S() {
        logExporter.info('S2sChatBot', '⏳ WAITING for data channel to be ready...');
        
        // Poll for data channel readiness
        const checkDataChannel = () => {
            const isReady = this.webrtcManager && this.webrtcManager.isDataChannelReady();
            logExporter.info('S2sChatBot', `🔍 CHECKING data channel readiness: ${isReady}`);
            
            if (isReady) {
                logExporter.info('S2sChatBot', '✅ DATA CHANNEL READY! Starting 2-second delay before S2S initialization...');
                
                // Add delay to ensure server is fully ready to receive S2S events
                const timeoutId = setTimeout(() => {
                    const stateCheck = {
                        sessionStarted: this.state?.sessionStarted,
                        hasWebRTCManager: !!this.webrtcManager,
                        isConnected: this.webrtcManager?.isWebRTCConnected(),
                        isDataChannelReady: this.webrtcManager?.isDataChannelReady()
                    };
                    
                    logExporter.info('S2sChatBot', '🚀 TIMEOUT FIRED! Starting S2S session initialization after delay...', stateCheck);
                    
                    try {
                        logExporter.info('S2sChatBot', '🎯 About to call initializeS2SSession...');
                        this.initializeS2SSession().catch(error => {
                            logExporter.error('S2sChatBot', '❌ Error in S2S session initialization', {
                                error: error.message,
                                stack: error.stack
                            });
                        });
                    } catch (error) {
                        logExporter.error('S2sChatBot', '❌ Synchronous error calling initializeS2SSession', {
                            error: error.message,
                            stack: error.stack
                        });
                    }
                }, 2000); // Wait 2 seconds after data channel is ready
                
                logExporter.info('S2sChatBot', `⏰ Timeout scheduled with ID: ${timeoutId}`);
            } else {
                logExporter.debug('S2sChatBot', '⏳ Data channel not ready yet, waiting 1 second...');
                setTimeout(checkDataChannel, 1000); // Check every 1 second
            }
        };
        
        checkDataChannel();
    }

    async initializeS2SSession() {
        try {
            const sessionNames = {
                promptName: this.state.promptName,
                textContentName: this.state.textContentName,
                audioContentName: this.state.audioContentName
            };
            
            logExporter.info('S2sChatBot', '🚀 STARTING S2S SESSION INITIALIZATION', sessionNames);
            
            // Start session events
            logExporter.info('S2sChatBot', '📤 SENDING sessionStart event...');
            await this.sendEvent(S2sEvent.sessionStart());

            var audioConfig = S2sEvent.DEFAULT_AUDIO_OUTPUT_CONFIG;
            audioConfig.voiceId = this.state.configVoiceIdOption.value;
            var toolConfig = this.state.configToolUse ? JSON.parse(this.state.configToolUse) : S2sEvent.DEFAULT_TOOL_CONFIG;

            logExporter.info('S2sChatBot', '📤 SENDING promptStart event...', {
                promptName: this.state.promptName,
                voiceId: audioConfig.voiceId
            });
            await this.sendEvent(S2sEvent.promptStart(this.state.promptName, audioConfig, toolConfig));

            logExporter.info('S2sChatBot', '📤 SENDING contentStartText event...', {
                promptName: this.state.promptName,
                textContentName: this.state.textContentName
            });
            await this.sendEvent(S2sEvent.contentStartText(this.state.promptName, this.state.textContentName));

            await this.sendEvent(S2sEvent.textInput(this.state.promptName, this.state.textContentName, this.state.configSystemPrompt));
            await this.sendEvent(S2sEvent.contentEnd(this.state.promptName, this.state.textContentName));

            // Chat history
            if (this.state.includeChatHistory) {
                var chatHistory = JSON.parse(this.state.configChatHistory);
                if (chatHistory === null) chatHistory = S2sEvent.DEFAULT_CHAT_HISTORY;
                for (const chat of chatHistory) {
                    const chatHistoryContentName = crypto.randomUUID();
                    await this.sendEvent(S2sEvent.contentStartText(this.state.promptName, chatHistoryContentName, chat.role));
                    await this.sendEvent(S2sEvent.textInput(this.state.promptName, chatHistoryContentName, chat.content));
                    await this.sendEvent(S2sEvent.contentEnd(this.state.promptName, chatHistoryContentName));
                }
            }

            logExporter.info('S2sChatBot', '📤 SENDING contentStartAudio event...', {
                promptName: this.state.promptName,
                audioContentName: this.state.audioContentName
            });
            await this.sendEvent(S2sEvent.contentStartAudio(this.state.promptName, this.state.audioContentName));
            
            // Create initial audioInput event immediately (synchronously)
            const initialAudioInputEvent = {
                event: {
                    audioInput: {
                        promptName: this.state.promptName,
                        contentName: this.state.audioContentName,
                        content: 'WebRTC Media Channel (ready)',
                        isTransmitting: false,
                        packetsCount: 0,
                        dataSize: 0,
                        duration: 0
                    }
                },
                timestamp: Date.now(),
                audioTransmissionStats: {
                    action: 'ready',
                    packetsCount: 0,
                    dataSize: 0,
                    duration: 0
                }
            };
            
            if (this.eventDisplayRef.current) {
                this.eventDisplayRef.current.displayEvent(initialAudioInputEvent, "out");
            }
            
            // CRITICAL: Start audio transmission ONLY after all S2S events are sent
            if (this.webrtcManager && this.webrtcManager.audioTransmissionStats) {
                this.webrtcManager.startAudioTransmissionSession();
                console.log('[S2sChatBot] 🎤 ✅ Audio transmission started AFTER S2S events (correct order!)');
                logExporter.info('S2sChatBot', '🎤 ✅ Audio transmission started AFTER S2S events (correct order!)');
            }
            
            // Audio now flows through WebRTC media channel, not as events
            this.setState({ audioInputReady: true });
            
            logExporter.info('S2sChatBot', '✅ AUDIO CONTENT STARTED - audio flows through WebRTC media channel');
            
            logExporter.info('S2sChatBot', '✅ S2S SESSION INITIALIZATION COMPLETED SUCCESSFULLY!');
        } catch (error) {
            logExporter.error('S2sChatBot', 'Error initializing S2S session', {
                error: error.message,
                stack: error.stack
            });
            this.setState({alert: `S2S session initialization failed: ${error.message}`});
            
            // Auto-export logs on session initialization failure
            setTimeout(async () => {
                console.log('[S2sChatBot] Auto-exporting logs due to session initialization failure...');
                await logExporter.autoExportToLogsFolder();
            }, 1000);
        }
    }
      
    setupWebRTCAudioHandling() {
        if (this.audioHandlingSetup) {
            console.log('[S2sChatBot] Audio handling already set up, skipping...');
            return;
        }
        
        console.log('[S2sChatBot] 🎤 Setting up NATIVE WebRTC audio handling...');
        
        // Set up NATIVE WebRTC audio handlers
        this.webrtcManager.onLocalAudioTrack = (track, stream) => {
            console.log('[S2sChatBot] 🎤 NATIVE local audio track ready:', {
                kind: track.kind,
                label: track.label,
                readyState: track.readyState,
                streamId: stream.id
            });
            
            // Audio flows natively through WebRTC - no custom processing needed!
            console.log('[S2sChatBot] ✅ Audio flows NATIVELY through WebRTC media channel');
        };

        this.webrtcManager.onRemoteAudioTrack = (track, stream) => {
            console.log('[S2sChatBot] 🔊 NATIVE remote audio track received:', {
                kind: track.kind,
                label: track.label,
                readyState: track.readyState,
                streamId: stream.id
            });
            
            // Remote audio is automatically handled by native WebRTC
            console.log('[S2sChatBot] ✅ Remote audio handled NATIVELY by WebRTC');
        };

        // Set up audio input event handler for Events display
        this.webrtcManager.onAudioInputEvent = (eventData) => {
            this.handleAudioInputEvent(eventData);
        };

        this.audioHandlingSetup = true;
        console.log('[S2sChatBot] ✅ NATIVE WebRTC audio handling set up - no custom processing!');
        console.log('[S2sChatBot] ⏳ Audio transmission will start AFTER S2S events are sent');
    }

    handleAudioInputEvent(eventData) {
        const { action, isTransmitting, packetsCount, dataSize, duration } = eventData;
        
        // Log audio transmission status
        if (action === 'start') {
            console.log('[S2sChatBot] 🎤 Audio transmission started');
        } else if (action === 'end') {
            console.log(`[S2sChatBot] 🎤 Audio transmission ended (${packetsCount} packets, ${dataSize} bytes, ${duration}ms)`);
        }
        
        // Update existing audioInput event for Events display
        if (this.state.sessionStarted && (this.state.promptName && this.state.audioContentName)) {
            const displayEvent = {
                event: {
                    audioInput: {
                        promptName: this.state.promptName,
                        contentName: this.state.audioContentName,
                        content: `WebRTC Media Channel (${packetsCount} packets)`,
                        isTransmitting: isTransmitting,
                        packetsCount: packetsCount,
                        dataSize: dataSize,
                        duration: duration
                    }
                },
                timestamp: Date.now(),
                audioTransmissionStats: {
                    action: action,
                    packetsCount: packetsCount,
                    dataSize: dataSize,
                    duration: duration
                }
            };
            
            // Update the existing audioInput event in event viewer
            if (this.eventDisplayRef.current) {
                this.eventDisplayRef.current.updateAudioInputEvent(displayEvent);
            }
        }
    }

    async endSession() {
        if (this.webrtcManager) {
            try {
                // Send session end events only if connected
                if (this.webrtcManager.isWebRTCConnected()) {
                    await this.sendEvent(S2sEvent.contentEnd(this.state.promptName, this.state.audioContentName));
                    await this.sendEvent(S2sEvent.promptEnd(this.state.promptName));
                    await this.sendEvent(S2sEvent.sessionEnd());
                    
                    // Wait for final events before disconnecting
                    console.log('[S2sChatBot] Waiting for final events before disconnecting...');
                    await new Promise(resolve => setTimeout(resolve, 3000)); // Wait 3 seconds
                }

                // Always disconnect WebRTC regardless of connection state
                this.webrtcManager.disconnect();
                
                // Reset audio input flag and audio handling setup
                this.setState({ audioInputReady: false });
                this.audioHandlingSetup = false;

                logExporter.info('S2sChatBot', '✅ Session ended and WebRTC disconnected');
            } catch (error) {
                logExporter.error('S2sChatBot', 'Error ending session', {
                    error: error.message,
                    stack: error.stack
                });
                // Still try to disconnect even if there was an error
                this.webrtcManager.disconnect();
            }

            // Don't set sessionStarted here - let handleSessionChange manage the state
        }
    }
    render() {
        return (
            <div className="s2s">
                {this.state.alert !== null && this.state.alert.length > 0?
                <div><Alert statusIconAriaLabel="Warning" type="warning">
                {this.state.alert}
                </Alert><br/></div>:<div/>}
                <div className='top'>
                    <div className='action'>
                        <Button variant='primary' onClick={this.handleSessionChange}>
                            <Icon name={this.state.sessionStarted?"microphone-off":"microphone"} />&nbsp;&nbsp;
                            {this.state.sessionStarted?"End Conversation":"Start Conversation"}
                        </Button>
                        <div className='chathistory'>
                            <Checkbox checked={this.state.includeChatHistory} onChange={({ detail }) => this.setState({includeChatHistory: detail.checked})}>Include chat history</Checkbox>
                            <div className='desc'>You can view sample chat history in the settings.</div>
                        </div>
                    </div>
                    {this.state.showUsage && <Meter ref={this.meterRef}/>}
                    <div className='setting'>
                        <Button onClick={()=> 
                            this.setState({
                                showConfig: true, 
                            })
                        }>
                            <Icon name="settings"/>
                        </Button>
                        
                    </div>
                </div>
                <br/>
                <ColumnLayout columns={2}>
                    <Container header={
                        <Header variant="h2">Conversation</Header>
                    }>
                    <div className="chatarea">
                        {(() => {
                            const messageKeys = Object.keys(this.state.chatMessages);
                            console.log(`[S2sChatBot] 🎨 Rendering conversation - ${messageKeys.length} messages:`, messageKeys);
                            
                            if (messageKeys.length === 0) {
                                console.log(`[S2sChatBot] 📭 No messages to render`);
                                return <div style={{padding: '20px', color: '#666', fontStyle: 'italic'}}>
                                    No conversation messages yet...
                                </div>;
                            }
                            
                            return messageKeys.map((key,index) => {
                                const msg = this.state.chatMessages[key];
                                console.log(`[S2sChatBot] 🎨 Rendering message ${index}: key=${key}, role=${msg.role}, content="${msg.content?.substring(0, 50)}..."`);
                                
                                //if (msg.stopReason === "END_TURN" || msg.role === "USER")
                                return <div key={key} className='item'>
                                    <div className={msg.role === "USER"?"user":"bot"} onClick={()=> 
                                            this.setState({
                                                showEventJson: true, 
                                                selectedEvent: {events:msg.raw}
                                            })
                                        }>
                                        <Icon name={msg.role === "USER"?"user-profile":"gen-ai"} />&nbsp;&nbsp;
                                        {msg.content}
                                        {msg.role === "ASSISTANT" && msg.generationStage? ` [${msg.generationStage}]`:""}
                                    </div>
                                </div>
                            });
                        })()}
                        <div className='endbar' ref={this.chatMessagesEndRef}></div>
                    </div>
                    </Container>
                    <Container header={
                        <Header variant="h2">Events</Header>
                    }>
                        <S2sEventDisplay ref={this.eventDisplayRef}></S2sEventDisplay>
                    </Container>
                </ColumnLayout>
                <Modal
                    onDismiss={() => this.setState({showEventJson: false})}
                    visible={this.state.showEventJson}
                    header="Event details"
                    size='medium'
                    footer={
                        <Box float="right">
                        <SpaceBetween direction="horizontal" size="xs">
                            <Button variant="link" onClick={() => this.setState({showEventJson: false})}>Close</Button>
                        </SpaceBetween>
                        </Box>
                    }
                >
                    <div className='eventdetail'>
                    <pre id="jsonDisplay">
                        {this.state.selectedEvent && this.state.selectedEvent.events.map(e=>{
                            const eventType = Object.keys(e?.event)[0];
                            if (eventType === "audioInput" || eventType === "audioOutput")
                                e.event[eventType].content = e.event[eventType].content.substr(0,10) + "...";
                            const ts = new Date(e.timestamp).toLocaleString(undefined, {
                                year: "numeric",
                                month: "2-digit",
                                day: "2-digit",
                                hour: "2-digit",
                                minute: "2-digit",
                                second: "2-digit",
                                fractionalSecondDigits: 3, // Show milliseconds
                                hour12: false // 24-hour format
                            });
                            var displayJson = { ...e };
                            delete displayJson.timestamp;
                            return ts + "\n" + JSON.stringify(displayJson,null,2) + "\n";
                        })}
                    </pre>
                    </div>
                </Modal>
                <Modal  
                    onDismiss={() => this.setState({showConfig: false})}
                    visible={this.state.showConfig}
                    header="Nova S2S settings"
                    size='large'
                    footer={
                        <Box float="right">
                        <SpaceBetween direction="horizontal" size="xs">
                            <Button variant="normal" onClick={() => {
                                logExporter.exportToText();
                            }}>Export TXT</Button>
                            <Button variant="normal" onClick={() => {
                                logExporter.exportToFile();
                            }}>Export JSON</Button>
                            <Button variant="link" onClick={() => {
                                this.saveConfiguration();
                                this.setState({showConfig: false});
                            }}>Save</Button>
                        </SpaceBetween>
                        </Box>
                    }
                >
                    <div className='config'>
                        <FormField
                            label="Voice Id"
                            stretch={true}
                        >
                            <Select
                                selectedOption={this.state.configVoiceIdOption}
                                onChange={({ detail }) =>
                                    this.setState({configVoiceIdOption: detail.selectedOption})
                                }
                                options={[
                                    { label: "Matthew (English US)", value: "matthew" },
                                    { label: "Tiffany (English US)", value: "tiffany" },
                                    { label: "Amy (English GB)", value: "amy" },
                                    { label: "Ambre (French)", value: "ambre" },
                                    { label: "Florian (French)", value: "florian" },
                                    { label: "Beatrice (Italian)", value: "beatrice" },
                                    { label: "Lorenzo (Italian)", value: "lorenzo" },
                                    { label: "Greta (German)", value: "greta" },
                                    { label: "Lennart (German)", value: "lennart" },
                                    { label: "Lupe (Spanish)", value: "lupe"},
                                    { label: "Carlos (Spanish)", value: "carlos"},
                                ]}
                                />
                        </FormField>
                        <br/>
                        <FormField
                            label="System prompt"
                            description="For the speech model"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configSystemPrompt: detail.value})}
                                value={this.state.configSystemPrompt}
                                placeholder="Speech system prompt"
                                rows={5}
                            />
                        </FormField>
                        <br/>
                        <FormField
                            label="Tool use configuration"
                            description="For external integration such as RAG and Agents"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configToolUse: detail.value})}
                                value={this.state.configToolUse}
                                rows={10}
                                placeholder="{}"
                            />
                        </FormField>
                                <br/>
                        <FormField
                            label="Chat history"
                            description="Sample chat history to resume conversation"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configChatHistory: detail.value})}
                                value={this.state.configChatHistory}
                                rows={15}
                                placeholder="{}"
                            />
                        </FormField>
                        <br/>
                        <Header variant="h3">WebRTC Configuration</Header>
                        <br/>
                        <FormField
                            label="KVS Channel Name"
                            description="Amazon Kinesis Video Streams signaling channel name"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configChannelName: detail.value})}
                                value={this.state.configChannelName}
                                rows={1}
                                placeholder="nova-s2s-channel"
                            />
                        </FormField>
                        <br/>
                        <FormField
                            label="AWS Region"
                            description="AWS region for KVS WebRTC"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configRegion: detail.value})}
                                value={this.state.configRegion}
                                rows={1}
                                placeholder="ap-northeast-1"
                            />
                        </FormField>
                        <br/>
                        <FormField
                            label="AWS Access Key ID"
                            description="AWS credentials for KVS access"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configAccessKeyId: detail.value})}
                                value={this.state.configAccessKeyId}
                                rows={1}
                                placeholder="AKIA..."
                            />
                        </FormField>
                        <br/>
                        <FormField
                            label="AWS Secret Access Key"
                            description="AWS secret access key"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configSecretAccessKey: detail.value})}
                                value={this.state.configSecretAccessKey}
                                rows={1}
                                placeholder="Secret key"
                            />
                        </FormField>
                        <br/>
                        <FormField
                            label="AWS Session Token (Optional)"
                            description="AWS session token for temporary credentials"
                            stretch={true}
                        >
                            <Textarea
                                onChange={({ detail }) => this.setState({configSessionToken: detail.value})}
                                value={this.state.configSessionToken}
                                rows={2}
                                placeholder="Session token (optional)"
                            />
                        </FormField>
                        <br/>
                        <Button 
                            variant="normal" 
                            onClick={() => this.testWebRTCConfiguration()}
                            disabled={this.state.sessionStarted}
                        >
                            Test WebRTC Configuration
                        </Button>
                    </div>
                </Modal>
            </div>
        );
    }
}

export default S2sChatBot;