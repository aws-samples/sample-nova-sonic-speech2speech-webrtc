# Smart Home Web Dashboard

A web-based dashboard for controlling smart home devices through AWS IoT Core using MQTT over WebSockets with SigV4 authentication.

## Features

- **Real-time device control** via MQTT
- **Fancy UI** with animations and visual effects
- **Responsive design** for desktop and mobile
- **Device types**: Lights (with brightness), Smart Locks, Ovens (with temperature)
- **Rooms**: Living Room, Kitchen, Bedroom

## Setup Instructions

### 1. Configure AWS Credentials

Edit `config.js` and replace the placeholder values:

```javascript
const AWS_CONFIG = {
    region: 'your-aws-region',
    accessKeyId: 'YOUR_ACCESS_KEY_ID',
    secretAccessKey: 'YOUR_SECRET_ACCESS_KEY',
    iotEndpoint: 'YOUR_IOT_ENDPOINT.iot.your-region.amazonaws.com'
};
```

### 2. AWS IoT Core Setup

1. Create an IoT Core endpoint in your AWS account
2. Set up appropriate IAM policies for IoT access
3. Configure CORS for your IoT endpoint to allow web access

### 3. MQTT Topics

The application uses topics defined in `mqtt-topics.md`. You can modify these topics as needed.

### 4. Run the Application

Since this uses browser-based MQTT, you need to serve the files over HTTP/HTTPS:

```bash
# Using Python 3
python -m http.server 8000

# Using Node.js (if you have http-server installed)
npx http-server

# Using PHP
php -S localhost:8000
```

Then open `http://localhost:8000` in your browser.

## File Structure

```
web-demo/
├── index.html          # Main HTML file
├── styles.css          # CSS with animations and styling
├── app.js             # Main JavaScript application
├── config.js          # AWS configuration
├── mqtt-topics.md     # MQTT topics documentation
└── README.md          # This file
```

## Device Control

- **Lights**: Toggle on/off, adjust brightness (0-100)
- **Smart Locks**: Toggle locked/unlocked
- **Ovens**: Toggle on/off, set temperature (100-500°F)

## MQTT Message Format

All messages follow JSON format as documented in `mqtt-topics.md`.

## Browser Compatibility

- Chrome 60+
- Firefox 55+
- Safari 12+
- Edge 79+

## Notes

- The current implementation includes simulation mode for testing without AWS IoT Core
- For production use, implement proper error handling and reconnection logic
- Consider using AWS Cognito for user authentication in production
