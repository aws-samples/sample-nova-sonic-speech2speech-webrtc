export default class AudioPlayer {
    constructor() {
        this.initialized = false;
        this.audioContext = null;
        this.workletNode = null;
        this.analyser = null;
    }

    async start() {
        if (this.initialized) return;

        this.audioContext = new AudioContext({ "sampleRate": 24000 });
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 512;

        // Load the audio worklet
        let workletUrl;
        try {
            // For production/development
            workletUrl = new URL('./audioPlayerProcessor.worklet.js', import.meta.url).toString();
        } catch (error) {
            // Fallback for build environment
            workletUrl = './audioPlayerProcessor.worklet.js';
        }
        await this.audioContext.audioWorklet.addModule(workletUrl);

        this.workletNode = new AudioWorkletNode(this.audioContext, "audio-player-processor");
        this.workletNode.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);

        this.initialized = true;
    }

    bargeIn() {
        if (!this.initialized) return;
        this.workletNode.port.postMessage({
            type: "barge-in",
        });
    }

    stop() {
        if (!this.initialized) return;

        if (this.audioContext) {
            this.audioContext.close();
        }

        if (this.analyser) {
            this.analyser.disconnect();
        }

        if (this.workletNode) {
            this.workletNode.disconnect();
        }

        this.initialized = false;
        this.audioContext = null;
        this.analyser = null;
        this.workletNode = null;
    }

    playAudio(samples) {
        if (!this.initialized) {
            console.error("The audio player is not initialized. Call start() before attempting to play audio.");
            return;
        }

        this.workletNode.port.postMessage({
            type: "audio",
            audioData: samples,
        });
    }
}