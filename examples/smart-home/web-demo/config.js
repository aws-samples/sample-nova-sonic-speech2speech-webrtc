// AWS IoT Core Configuration
// Replace these values with your actual AWS credentials and IoT Core endpoint

const AWS_CONFIG = {
    region: 'ap-northeast-1', // Your AWS region
    accessKeyId: 'xxxxxxx', // Your AWS access key ID
    secretAccessKey: 'xxxxxxx', // Your AWS secret access key
    iotEndpoint: 'xxxxxxx-ats.iot.ap-northeast-1.amazonaws.com', // Your IoT Core endpoint
    
    // MQTT Configuration
    //clientId: 'smart-home-web-' + Math.random().toString(36).substr(2, 9),
    clientId: 'smart-home-web',
    
    // Connection options
    keepAlive: 30,
    connectTimeoutMs: 5000,
    pingTimeoutMs: 3000
};

// Export for use in app.js
window.AWS_CONFIG = AWS_CONFIG;
