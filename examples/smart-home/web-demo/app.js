class SmartHomeApp {
    constructor() {
        this.connection = null;
        this.isConnected = false;
        this.devices = new Map();
        this.topics = this.loadTopics();
        
        this.init();
    }

    loadTopics() {
        return {
            'living-room': {
                'light': {
                    status: 'smarthome/living-room/light/status',
                    control: 'smarthome/living-room/light/control'
                },
                'lock': {
                    status: 'smarthome/living-room/lock/status',
                    control: 'smarthome/living-room/lock/control'
                }
            },
            'kitchen': {
                'light': {
                    status: 'smarthome/kitchen/light/status',
                    control: 'smarthome/kitchen/light/control'
                },
                'oven': {
                    status: 'smarthome/kitchen/oven/status',
                    control: 'smarthome/kitchen/oven/control'
                }
            },
            'bedroom': {
                'light': {
                    status: 'smarthome/bedroom/light/status',
                    control: 'smarthome/bedroom/light/control'
                }
            }
        };
    }

    async init() {
        this.setupEventListeners();
        this.initializeDeviceStates();
        await this.connectToIoT();
    }

    setupEventListeners() {
        // Toggle buttons
        document.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const device = e.target.closest('.device');
                this.toggleDevice(device);
            });
        });

        // Brightness sliders
        document.querySelectorAll('.brightness-slider').forEach(slider => {
            slider.addEventListener('change', (e) => {
                const device = e.target.closest('.device');
                this.setBrightness(device, parseInt(e.target.value));
            });
        });

        // Temperature inputs
        document.querySelectorAll('.temperature-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const device = e.target.closest('.device');
                this.setTemperature(device, parseInt(e.target.value));
            });
        });
    }

    initializeDeviceStates() {
        document.querySelectorAll('.device').forEach(deviceEl => {
            const room = deviceEl.dataset.room;
            const device = deviceEl.dataset.device;
            const key = `${room}-${device}`;
            
            this.devices.set(key, {
                element: deviceEl,
                room: room,
                device: device,
                state: device === 'lock' ? 'locked' : 'off',
                brightness: 50,
                temperature: 200
            });
        });
    }

    async connectToIoT() {
        try {
            // Configure AWS SDK
            AWS.config.update({
                accessKeyId: AWS_CONFIG.accessKeyId,
                secretAccessKey: AWS_CONFIG.secretAccessKey,
                region: AWS_CONFIG.region
            });

            // Create signed WebSocket URL for IoT Core
            const signedUrl = await this.createSignedWebSocketUrl();
            
            // Create MQTT client with signed WebSocket URL
            const urlParts = new URL(signedUrl);
            this.client = new Paho.MQTT.Client(urlParts.host, 443, urlParts.pathname + urlParts.search, AWS_CONFIG.clientId);

            // Set up event handlers
            this.client.onConnectionLost = (responseObject) => {
                console.log('Connection lost:', responseObject.errorMessage);
                this.isConnected = false;
                this.updateConnectionStatus(false);
            };

            this.client.onMessageArrived = (message) => {
                console.log('Message arrived:', message.destinationName, message.payloadString);
                this.handleIncomingMessage(message.destinationName, JSON.parse(message.payloadString));
            };

            // Connect using WebSocket with SigV4 authentication
            this.client.connect({
                useSSL: true,
                onSuccess: () => {
                    console.log('Connected to AWS IoT Core via WebSocket with SigV4');
                    this.isConnected = true;
                    this.updateConnectionStatus(true);
                    this.subscribeToTopics();
                },
                onFailure: (error) => {
                    console.error('Connection failed:', error);
                    this.updateConnectionStatus(false);
                }
            });

        } catch (error) {
            console.error('Failed to connect to IoT Core:', error);
            this.updateConnectionStatus(false);
        }
    }

    sha256(data) {
        const encoder = new TextEncoder();
        return crypto.subtle.digest('SHA-256', encoder.encode(data)).then(buffer => {
            return Array.from(new Uint8Array(buffer)).map(b => b.toString(16).padStart(2, '0')).join('');
        });
    }

    async createSignedWebSocketUrl() {
        const now = new Date();
        const dateStamp = now.toISOString().slice(0, 10).replace(/-/g, '');
        const amzDate = now.toISOString().replace(/[:\-]|\.\d{3}/g, '');
        
        // Create canonical request
        const method = 'GET';
        const uri = '/mqtt';
        const queryString = `X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=${encodeURIComponent(AWS_CONFIG.accessKeyId + '/' + dateStamp + '/' + AWS_CONFIG.region + '/iotdevicegateway/aws4_request')}&X-Amz-Date=${amzDate}&X-Amz-SignedHeaders=host`;
        const headers = `host:${AWS_CONFIG.iotEndpoint}\n`;
        const signedHeaders = 'host';
        const payloadHash = await this.sha256('');
        
        const canonicalRequest = `${method}\n${uri}\n${queryString}\n${headers}\n${signedHeaders}\n${payloadHash}`;
        
        // Create string to sign
        const algorithm = 'AWS4-HMAC-SHA256';
        const credentialScope = `${dateStamp}/${AWS_CONFIG.region}/iotdevicegateway/aws4_request`;
        const stringToSign = `${algorithm}\n${amzDate}\n${credentialScope}\n${await this.sha256(canonicalRequest)}`;
        
        // Calculate signature
        const signature = await this.calculateSignature(AWS_CONFIG.secretAccessKey, dateStamp, AWS_CONFIG.region, 'iotdevicegateway', stringToSign);
        
        // Create signed URL
        const signedUrl = `wss://${AWS_CONFIG.iotEndpoint}/mqtt?${queryString}&X-Amz-Signature=${signature}`;
        
        return signedUrl;
    }

    async calculateSignature(secretKey, dateStamp, region, service, stringToSign) {
        const kDate = await this.hmacSha256('AWS4' + secretKey, dateStamp);
        const kRegion = await this.hmacSha256(kDate, region);
        const kService = await this.hmacSha256(kRegion, service);
        const kSigning = await this.hmacSha256(kService, 'aws4_request');
        const signature = await this.hmacSha256(kSigning, stringToSign);
        
        return Array.from(new Uint8Array(signature)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    async hmacSha256(key, data) {
        const encoder = new TextEncoder();
        const keyData = typeof key === 'string' ? encoder.encode(key) : key;
        const dataBuffer = encoder.encode(data);
        
        const cryptoKey = await crypto.subtle.importKey(
            'raw',
            keyData,
            { name: 'HMAC', hash: 'SHA-256' },
            false,
            ['sign']
        );
        
        return await crypto.subtle.sign('HMAC', cryptoKey, dataBuffer);
    }

    subscribeToTopics() {
        // Subscribe to all control topics to receive commands
        Object.keys(this.topics).forEach(room => {
            Object.keys(this.topics[room]).forEach(device => {
                const controlTopic = this.topics[room][device].control;
                console.log(`Subscribing to: ${controlTopic}`);
                if (this.client && this.isConnected) {
                    this.client.subscribe(controlTopic);
                }
            });
        });
    }

    updateConnectionStatus(connected) {
        const statusEl = document.getElementById('connectionStatus');
        if (connected) {
            statusEl.innerHTML = '<i class="fas fa-circle"></i> Connected';
            statusEl.classList.add('connected');
        } else {
            statusEl.innerHTML = '<i class="fas fa-circle"></i> Disconnected';
            statusEl.classList.remove('connected');
        }
    }

    toggleDevice(deviceEl) {
        const room = deviceEl.dataset.room;
        const device = deviceEl.dataset.device;
        const key = `${room}-${device}`;
        const deviceData = this.devices.get(key);

        deviceEl.classList.add('loading');

        // Directly change device state (simulating physical device response)
        let newState;
        if (device === 'lock') {
            newState = deviceData.state === 'locked' ? 'unlocked' : 'locked';
        } else {
            newState = deviceData.state === 'on' ? 'off' : 'on';
        }

        setTimeout(() => {
            deviceData.state = newState;
            this.updateDeviceUI(deviceEl, deviceData);
            this.publishStatus(room, device, deviceData);
            deviceEl.classList.remove('loading');
        }, 500);
    }

    setBrightness(deviceEl, brightness) {
        const room = deviceEl.dataset.room;
        const device = deviceEl.dataset.device;
        const key = `${room}-${device}`;
        const deviceData = this.devices.get(key);

        deviceData.brightness = brightness;
        this.publishStatus(room, device, deviceData);
    }

    setTemperature(deviceEl, temperature) {
        const room = deviceEl.dataset.room;
        const device = deviceEl.dataset.device;
        const key = `${room}-${device}`;
        const deviceData = this.devices.get(key);

        deviceData.temperature = temperature;
        this.publishStatus(room, device, deviceData);
    }

    handleControlMessage(room, device, message) {
        const key = `${room}-${device}`;
        const deviceData = this.devices.get(key);
        
        if (!deviceData) return;

        // Process the control command
        if (message.action === 'toggle') {
            // Toggle the current state
            if (device === 'lock') {
                deviceData.state = deviceData.state === 'locked' ? 'unlocked' : 'locked';
            } else {
                deviceData.state = deviceData.state === 'on' ? 'off' : 'on';
            }
        } else if (message.action === 'set_brightness' && message.brightness !== undefined) {
            deviceData.brightness = message.brightness;
            if (deviceData.state === 'off') deviceData.state = 'on';
        } else if (message.action === 'set_temperature' && message.temperature !== undefined) {
            deviceData.temperature = message.temperature;
            if (deviceData.state === 'off') deviceData.state = 'on';
        } else if (message.state !== undefined) {
            // Direct state setting
            deviceData.state = message.state;
        }

        // Handle direct property updates (without action field)
        if (message.brightness !== undefined) {
            deviceData.brightness = message.brightness;
            if (deviceData.state === 'off') deviceData.state = 'on';
        }
        if (message.temperature !== undefined) {
            deviceData.temperature = message.temperature;
            if (deviceData.state === 'off') deviceData.state = 'on';
        }

        // Update UI
        this.updateDeviceUI(deviceData.element, deviceData);
        
        // Publish status update
        this.publishStatus(room, device, deviceData);
    }

    publishStatus(room, device, deviceData) {
        const topic = this.topics[room][device].status;
        const message = {
            state: deviceData.state,
            timestamp: new Date().toISOString()
        };

        if (deviceData.device === 'light') {
            message.brightness = deviceData.brightness;
        } else if (deviceData.device === 'oven') {
            message.temperature = deviceData.temperature;
        }

        console.log(`Publishing status to ${topic}:`, message);
        
        if (this.client && this.isConnected) {
            const mqttMessage = new Paho.MQTT.Message(JSON.stringify(message));
            mqttMessage.destinationName = topic;
            this.client.send(mqttMessage);
        }
    }

    handleIncomingMessage(topic, message) {
        // Parse topic to get room and device
        const parts = topic.split('/');
        if (parts.length >= 4 && parts[0] === 'smarthome') {
            const room = parts[1];
            const device = parts[2];
            const action = parts[3];
            
            if (action === 'control') {
                this.handleControlMessage(room, device, message);
            }
        }
    }

    handleStatusMessage(room, device, message) {
        const key = `${room}-${device}`;
        const deviceData = this.devices.get(key);
        
        if (deviceData) {
            deviceData.state = message.state;
            if (message.brightness !== undefined) {
                deviceData.brightness = message.brightness;
            }
            if (message.temperature !== undefined) {
                deviceData.temperature = message.temperature;
            }
            
            this.updateDeviceUI(deviceData.element, deviceData);
        }
    }

    updateDeviceUI(deviceEl, deviceData) {
        const toggleBtn = deviceEl.querySelector('.toggle-btn');
        const statusSpan = toggleBtn.querySelector('.status');
        const brightnessSlider = deviceEl.querySelector('.brightness-slider');
        const temperatureInput = deviceEl.querySelector('.temperature-input');

        // Update toggle button
        if (deviceData.device === 'lock') {
            statusSpan.textContent = deviceData.state.toUpperCase();
            toggleBtn.className = `toggle-btn ${deviceData.state === 'unlocked' ? 'on' : ''}`;
            deviceEl.className = `device lock-device ${deviceData.state}`;
        } else {
            statusSpan.textContent = deviceData.state.toUpperCase();
            toggleBtn.className = `toggle-btn ${deviceData.state === 'on' ? 'on' : ''}`;
            
            if (deviceData.device === 'light') {
                deviceEl.className = `device light-device ${deviceData.state}`;
                if (brightnessSlider) {
                    brightnessSlider.value = deviceData.brightness;
                    brightnessSlider.disabled = deviceData.state === 'off';
                }
            } else if (deviceData.device === 'oven') {
                deviceEl.className = `device oven-device ${deviceData.state} ${deviceData.state === 'on' ? 'heating' : ''}`;
                if (temperatureInput) {
                    temperatureInput.value = deviceData.temperature;
                    temperatureInput.disabled = deviceData.state === 'off';
                }
            }
        }

        // Add visual feedback
        deviceEl.style.transform = 'scale(1.05)';
        setTimeout(() => {
            deviceEl.style.transform = '';
        }, 200);
    }
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new SmartHomeApp();
});
