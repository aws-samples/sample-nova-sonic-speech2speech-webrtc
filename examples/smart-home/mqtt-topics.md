# Smart Home MQTT Topics Configuration

## Topic Structure
All topics follow the pattern: `smarthome/{room}/{device}/{action}`

## Rooms and Devices

### Living Room
- **Light**
  - Status: `smarthome/living-room/light/status`
  - Control: `smarthome/living-room/light/control`
- **Smart Lock**
  - Status: `smarthome/living-room/lock/status`
  - Control: `smarthome/living-room/lock/control`

### Kitchen
- **Light**
  - Status: `smarthome/kitchen/light/status`
  - Control: `smarthome/kitchen/light/control`
- **Oven**
  - Status: `smarthome/kitchen/oven/status`
  - Control: `smarthome/kitchen/oven/control`

### Bedroom
- **Light**
  - Status: `smarthome/bedroom/light/status`
  - Control: `smarthome/bedroom/light/control`

## Message Formats

### Light Messages
**Status:**
```json
{
  "state": "on|off",
  "brightness": 0-100,
  "timestamp": "2025-09-11T13:55:38.095Z"
}
```

**Control:**
```json
{
  "action": "toggle|set_brightness",
  "state": "on|off",
  "brightness": 0-100
}
```

### Lock Messages
**Status:**
```json
{
  "state": "locked|unlocked",
  "timestamp": "2025-09-11T13:55:38.095Z"
}
```

**Control:**
```json
{
  "action": "toggle",
  "state": "locked|unlocked"
}
```

### Oven Messages
**Status:**
```json
{
  "state": "on|off",
  "temperature": 100-500,
  "timestamp": "2025-09-11T13:55:38.095Z"
}
```

**Control:**
```json
{
  "action": "toggle|set_temperature",
  "state": "on|off",
  "temperature": 100-500
}
```

## Device Relationships

| Room | Device | Status Topic | Control Topic |
|------|--------|-------------|---------------|
| Living Room | Light | `smarthome/living-room/light/status` | `smarthome/living-room/light/control` |
| Living Room | Lock | `smarthome/living-room/lock/status` | `smarthome/living-room/lock/control` |
| Kitchen | Light | `smarthome/kitchen/light/status` | `smarthome/kitchen/light/control` |
| Kitchen | Oven | `smarthome/kitchen/oven/status` | `smarthome/kitchen/oven/control` |
| Bedroom | Light | `smarthome/bedroom/light/status` | `smarthome/bedroom/light/control` |
