/**
 * AudioStreamHandler - Handles audio streaming for WebRTC Nova S2S integration
 * Manages microphone capture, audio format conversion, and playback functionality
 */

import AudioPlayer from './audioPlayer.js';
import { base64ToFloat32Array } from './audioHelper.js';

class AudioStreamHandler {
    constructor() {
        this.audioPlayer = new AudioPlayer();
        this.audioContext = null;
        this.analyser = null;
        this.microphone = null;
        this.processor = null;
        this.isCapturing = false;
        this.isPlaying = false;

        // Audio configuration for Nova Sonic compatibility
        this.sampleRate = 16000; // Nova Sonic expects 16kHz
        this.channelCount = 1;   // Mono audio
        this.bufferSize = 1024;  // Smaller buffer for lower latency (64ms at 16kHz)

        // Event callbacks
        this.onAudioData = null;
        this.onAudioLevel = null;
        this.onError = null;

        // Audio level monitoring
        this.audioLevelInterval = null;
        this.lastAudioLevel = 0;
    }

    /**
     * Initialize audio context and components
     */
    async initialize() {
        try {
            console.log('[AudioStreamHandler] Initializing audio components...');

            // Initialize audio player for playback
            await this.audioPlayer.start();

            // Create audio context for processing
            this.audioContext = new AudioContext({
                sampleRate: this.sampleRate
            });

            // Create analyser for audio level monitoring
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            this.analyser.smoothingTimeConstant = 0.8;

            console.log('[AudioStreamHandler] Audio components initialized');

        } catch (error) {
            console.error('[AudioStreamHandler] Error initializing audio:', error);
            if (this.onError) {
                this.onError(error);
            }
            throw error;
        }
    }

    /**
     * Start capturing microphone audio
     * @param {MediaStream} stream - WebRTC media stream from getUserMedia
     */
    async startCapture(stream) {
        try {
            if (this.isCapturing) {
                console.warn('[AudioStreamHandler] Already capturing audio');
                return;
            }

            console.log('[AudioStreamHandler] Starting audio capture...');

            if (!this.audioContext) {
                await this.initialize();
            }

            // Resume audio context if suspended
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }

            // Create microphone source from WebRTC stream
            this.microphone = this.audioContext.createMediaStreamSource(stream);

            // TEMPORARY: Disable gain node to test if it's causing issues
            // Connect directly: microphone → analyser
            this.microphone.connect(this.analyser);
            console.log('[AudioStreamHandler] 🔧 Bypassing gain node - using direct connection');

            // Create script processor for audio data extraction
            // Note: ScriptProcessorNode is deprecated but still widely supported
            // In production, consider migrating to AudioWorklet
            this.processor = this.audioContext.createScriptProcessor(this.bufferSize, this.channelCount, this.channelCount);

            this.processor.onaudioprocess = (event) => {
                this.processAudioData(event);
            };

            // Connect processing chain: microphone → processor → destination
            this.microphone.connect(this.processor);
            this.processor.connect(this.audioContext.destination);

            this.isCapturing = true;

            // Start audio level monitoring
            this.startAudioLevelMonitoring();

            console.log('[AudioStreamHandler] Audio capture started');

        } catch (error) {
            console.error('[AudioStreamHandler] Error starting audio capture:', error);
            if (this.onError) {
                this.onError(error);
            }
            throw error;
        }
    }

    /**
     * Stop capturing microphone audio
     */
    stopCapture() {
        try {
            console.log('[AudioStreamHandler] Stopping audio capture...');

            this.isCapturing = false;

            // Stop audio level monitoring
            this.stopAudioLevelMonitoring();

            // Disconnect and clean up audio nodes
            if (this.processor) {
                this.processor.disconnect();
                this.processor = null;
            }

            // Gain node disabled for testing

            if (this.microphone) {
                this.microphone.disconnect();
                this.microphone = null;
            }

            console.log('[AudioStreamHandler] Audio capture stopped');

        } catch (error) {
            console.error('[AudioStreamHandler] Error stopping audio capture:', error);
        }
    }

    /**
     * Process captured audio data and convert to Nova Sonic format
     * @param {AudioProcessingEvent} event - Audio processing event
     */
    processAudioData(event) {
        if (!this.isCapturing || !this.onAudioData) {
            return;
        }

        try {
            const inputBuffer = event.inputBuffer;
            const inputData = inputBuffer.getChannelData(0); // Get mono channel

            // Convert Float32Array to Int16Array (PCM 16-bit)
            // Nova Sonic expects 16-bit PCM audio data

            // Remove duplicate gain reduction - already handled by Web Audio API GainNode
            // The GainNode (5%) + Server (1%) should be sufficient
            const maxValue = 0x7FFF; // Use full range since gain is handled elsewhere

            const int16Array = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
                // Clamp to [-1, 1] and convert to 16-bit integer with gain control
                const sample = Math.max(-1, Math.min(1, inputData[i]));
                int16Array[i] = Math.round(sample * maxValue);
            }

            // Convert to base64 for transmission (matching existing S2S format)
            const uint8Array = new Uint8Array(int16Array.buffer);
            const base64String = btoa(String.fromCharCode.apply(null, uint8Array));

            // Calculate audio metrics for monitoring
            const rms = Math.sqrt(inputData.reduce((sum, sample) => sum + sample * sample, 0) / inputData.length);
            const maxSample = Math.max(...inputData.map(Math.abs));

            // Log audio quality periodically (every 50 chunks to avoid spam)
            if (this.audioChunkCounter === undefined) this.audioChunkCounter = 0;
            this.audioChunkCounter++;

            if (this.audioChunkCounter % 50 === 0) {
                console.log(`[AudioStreamHandler] Audio chunk #${this.audioChunkCounter}: RMS=${rms.toFixed(3)}, Max=${maxSample.toFixed(3)}, DirectConnection=true`);

                if (maxSample > 0.8) {
                    console.warn(`[AudioStreamHandler] High audio levels detected (${maxSample.toFixed(3)}) - consider reducing microphone gain`);
                }
            }

            // Send audio data via callback
            this.onAudioData({
                audioData: base64String,
                sampleRate: this.sampleRate,
                channels: this.channelCount,
                format: 'pcm16',
                timestamp: Date.now(),
                rms: rms,
                maxLevel: maxSample
            });

        } catch (error) {
            console.error('[AudioStreamHandler] Error processing audio data:', error);
        }
    }

    /**
     * Play audio received from Nova Sonic
     * @param {string} base64AudioData - Base64 encoded audio data
     * @param {number} sampleRate - Audio sample rate (default: 24000 for Nova Sonic output)
     */
    async playAudio(base64AudioData, sampleRate = 24000) {
        try {
            if (!this.audioPlayer.initialized) {
                await this.audioPlayer.start();
            }

            // Convert base64 to Float32Array using existing helper
            const audioSamples = base64ToFloat32Array(base64AudioData);

            // Play audio through existing AudioPlayer
            this.audioPlayer.playAudio(audioSamples);

            console.log(`[AudioStreamHandler] Playing audio: ${audioSamples.length} samples at ${sampleRate}Hz`);

        } catch (error) {
            console.error('[AudioStreamHandler] Error playing audio:', error);
            if (this.onError) {
                this.onError(error);
            }
        }
    }

    /**
     * Handle remote audio track from WebRTC
     * @param {MediaStreamTrack} track - Remote audio track
     * @param {MediaStream} stream - Remote media stream
     */
    handleRemoteAudioTrack(track, stream) {
        try {
            console.log('[AudioStreamHandler] Handling remote audio track');

            // Create audio element for remote stream playback
            // This handles WebRTC audio that bypasses Nova Sonic processing
            const audioElement = new Audio();
            audioElement.srcObject = stream;
            audioElement.autoplay = true;
            audioElement.muted = false;

            // Store reference for cleanup
            this.remoteAudioElement = audioElement;

            // Handle track events
            track.onended = () => {
                console.log('[AudioStreamHandler] Remote audio track ended');
                if (this.remoteAudioElement) {
                    this.remoteAudioElement.srcObject = null;
                    this.remoteAudioElement = null;
                }
            };

        } catch (error) {
            console.error('[AudioStreamHandler] Error handling remote audio track:', error);
        }
    }

    /**
     * Start monitoring audio input levels
     */
    startAudioLevelMonitoring() {
        if (this.audioLevelInterval) {
            return;
        }

        this.audioLevelInterval = setInterval(() => {
            if (this.analyser && this.isCapturing) {
                const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
                this.analyser.getByteFrequencyData(dataArray);

                // Calculate RMS level
                let sum = 0;
                for (let i = 0; i < dataArray.length; i++) {
                    sum += dataArray[i] * dataArray[i];
                }
                const rms = Math.sqrt(sum / dataArray.length);

                // Convert to percentage (0-100)
                const level = Math.round((rms / 255) * 100);

                if (level !== this.lastAudioLevel) {
                    this.lastAudioLevel = level;
                    if (this.onAudioLevel) {
                        this.onAudioLevel(level);
                    }
                }
            }
        }, 100); // Update every 100ms
    }

    /**
     * Stop monitoring audio input levels
     */
    stopAudioLevelMonitoring() {
        if (this.audioLevelInterval) {
            clearInterval(this.audioLevelInterval);
            this.audioLevelInterval = null;
            this.lastAudioLevel = 0;
        }
    }

    /**
     * Trigger barge-in (interrupt current playback)
     */
    bargeIn() {
        try {
            console.log('[AudioStreamHandler] Triggering barge-in');

            if (this.audioPlayer && this.audioPlayer.initialized) {
                this.audioPlayer.bargeIn();
            }

        } catch (error) {
            console.error('[AudioStreamHandler] Error during barge-in:', error);
        }
    }

    /**
     * Get current audio input level
     * @returns {number} Audio level (0-100)
     */
    getAudioLevel() {
        return this.lastAudioLevel;
    }

    /**
     * Check if audio capture is active
     * @returns {boolean} Capture status
     */
    isAudioCapturing() {
        return this.isCapturing;
    }

    /**
     * Get audio configuration
     * @returns {Object} Audio configuration
     */
    getAudioConfig() {
        return {
            sampleRate: this.sampleRate,
            channelCount: this.channelCount,
            bufferSize: this.bufferSize
        };
    }

    /**
     * Clean up audio resources
     */
    cleanup() {
        try {
            console.log('[AudioStreamHandler] Cleaning up audio resources...');

            // Stop capture
            this.stopCapture();

            // Stop audio player
            if (this.audioPlayer) {
                this.audioPlayer.stop();
            }

            // Clean up remote audio element
            if (this.remoteAudioElement) {
                this.remoteAudioElement.srcObject = null;
                this.remoteAudioElement = null;
            }

            // Close audio context
            if (this.audioContext && this.audioContext.state !== 'closed') {
                this.audioContext.close();
                this.audioContext = null;
            }

            // Clear references
            this.analyser = null;
            this.microphone = null;
            // this.gainNode = null; // Disabled for testing
            this.processor = null;

            console.log('[AudioStreamHandler] Audio cleanup complete');

        } catch (error) {
            console.error('[AudioStreamHandler] Error during cleanup:', error);
        }
    }
}

export default AudioStreamHandler;