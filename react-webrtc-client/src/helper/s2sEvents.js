class S2sEvent {
    static DEFAULT_INFER_CONFIG = {
      maxTokens: 1024,
      topP: 0.95,
      temperature: 0.7
    };
  
    static DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant. The user and you will engage in a spoken dialog exchanging the transcripts of a natural real-time conversation. Keep your responses short, generally two or three sentences for chatty scenarios. You have access to various tools including location services, weather information, booking management, knowledge bases, and IoT device control via MQTT publishing to AWS IoT Core. When users ask about controlling smart home devices, sending sensor data, or publishing to MQTT topics, use getKbTool_Camera tool to find out the appropriate MQTT topic & payload, then use the publish_mqtt tool publish control message to IoT Core.";
  
    static DEFAULT_AUDIO_INPUT_CONFIG = {
      mediaType: "audio/lpcm",
      sampleRateHertz: 16000,
      sampleSizeBits: 16,
      channelCount: 1,
      audioType: "SPEECH",
      encoding: "base64"
    };
  
    static DEFAULT_AUDIO_OUTPUT_CONFIG = {
      mediaType: "audio/lpcm",
      sampleRateHertz: 24000,
      sampleSizeBits: 16,
      channelCount: 1,
      voiceId: "matthew",
      encoding: "base64",
      audioType: "SPEECH"
    };
  
    static DEFAULT_TOOL_CONFIG = {
      tools: [
        {
        toolSpec: {
          name: "getDateTool",
          description: "get information about the date and time",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {},
                "required": []
                }
            )
          }
        }
      },
      {
        toolSpec: {
          name: "getKbTool",
          description: "get information about Amazon Nova, Nova Sonic and Amazon foundation models",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    "description": "The question about Amazon Nova"
                  }},
                "required": []
              }
            )
          }
        }
      },
      {
        toolSpec: {
          name: "getKbTool_Camera",
          description: "get MQTT topics and payload formats for controlling smart home devices, like light & smart lock in living room, light and oven in kitchen, and light in bedroom. Or get information about network camera manuals",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    //"description": "The question about HikVision network cameras"
                    "description": "The question about MQTT topic definition for lights & lock & oven in living room, kitchen, or bedroom. Or the question about HikVision network cameras."
                  }},
                "required": []
              }
            )
          }
        }
      },
      {
        toolSpec: {
          name: "getLocationTool",
          description: "Search for places, addresses, or nearby points of interest, and access detailed information about specific locations.",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {
                  "tool": {
                    "type": "string",
                    "description": "The function name to search the location service. One of: search_places, get_place, search_nearby, reverse_geocode",
                  },
                  "query": {
                    "type": "string",
                    "description": "The search query to find relevant information"
                  }
                },
                "required": ["query"]
              }
            )
          }
        }
      },
      {
        toolSpec: {
          name: "externalAgent",
          description: "Get weather information for specific locations.",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    "description": "The search query to find relevant information"
                  }
                },
                "required": ["query"]
              }
            )
          }
        }
      },
      {
        toolSpec: {
          name: "getBookingDetails",
          description: "Manage bookings and reservations: create, get, update, delete, list, or find bookings by customer name. For update_booking, you can update by booking_id or by customer_name. If booking_id is not provided, all bookings for the given customer_name will be updated.",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    "description": "The request about booking, reservation"
                  }},
                "required": []
              }
            )
          }
        }
      },
      {
        toolSpec: {
          name: "publish_mqtt",
          description: "Publish MQTT message to Amazon IoT Core for device communication, sensor data, or IoT device control.",
          inputSchema: {
            json: JSON.stringify({
                "type": "object",
                "properties": {
                  "topic": {
                    "type": "string",
                    "description": "MQTT topic to publish to (e.g., 'device/sensor/temperature', 'home/lights/control')"
                  },
                  "payload": {
                    "type": "string",
                    "description": "Message payload (JSON string or plain text)"
                  },
                  "endpoint": {
                    "type": "string",
                    "description": "IoT Core endpoint URL (optional, uses IOT_ENDPOINT env var if not provided)"
                  },
                  "cert_path": {
                    "type": "string",
                    "description": "Path to device certificate file (optional)"
                  },
                  "key_path": {
                    "type": "string",
                    "description": "Path to private key file (optional)"
                  },
                  "username": {
                    "type": "string",
                    "description": "MQTT username for custom authorizer (optional)"
                  },
                  "password": {
                    "type": "string",
                    "description": "MQTT password for custom authorizer (optional)"
                  },
                  "custom_authorizer": {
                    "type": "string",
                    "description": "Custom authorizer name (optional)"
                  },
                  "client_id": {
                    "type": "string",
                    "description": "MQTT client ID (optional, auto-generated if not provided)"
                  },
                  "qos": {
                    "type": "integer",
                    "description": "Quality of Service level (0, 1, or 2)",
                    "default": 1
                  },
                  "retain": {
                    "type": "boolean",
                    "description": "Retain message flag",
                    "default": false
                  }
                },
                "required": ["topic", "payload"]
              }
            )
          }
        }
      }
    ]
    };

    static DEFAULT_CHAT_HISTORY = [
      {
        "content": "hi there i would like to cancel my hotel reservation",
        "role": "USER"
      },
      {
        "content": "Hello! I'd be happy to assist you with cancelling your hotel reservation. To get started, could you please provide me with your full name and the check-in date for your reservation?",
        "role": "ASSISTANT"
      },
      {
        "content": "yeah so my name is don smith",
        "role": "USER"
      },
      {
        "content": "Thank you, Don. Now, could you please provide me with the check-in date for your reservation?",
        "role": "ASSISTANT"
      },
      {
        "content": "yes so um let me check just a second",
        "role": "USER"
      },
      {
        "content": "Take your time, Don. I'll be here when you're ready.",
        "role": "ASSISTANT"
      }
    ];
  
    static sessionStart(inferenceConfig = S2sEvent.DEFAULT_INFER_CONFIG) {
      return { event: { sessionStart: { inferenceConfiguration: inferenceConfig } } };
    }
  
    static promptStart(promptName, audioOutputConfig = S2sEvent.DEFAULT_AUDIO_OUTPUT_CONFIG, toolConfig = S2sEvent.DEFAULT_TOOL_CONFIG) {
      return {
        "event": {
          "promptStart": {
            "promptName": promptName,
            "textOutputConfiguration": {
              "mediaType": "text/plain"
            },
            "audioOutputConfiguration": audioOutputConfig,
          
          "toolUseOutputConfiguration": {
            "mediaType": "application/json"
          },
          "toolConfiguration": toolConfig
        }
        }
      }
    }
  
    static contentStartText(promptName, contentName, role="SYSTEM") {
      return {
        "event": {
          "contentStart": {
            "promptName": promptName,
            "contentName": contentName,
            "type": "TEXT",
            "interactive": true,
            "role": role,
            "textInputConfiguration": {
              "mediaType": "text/plain"
            }
          }
        }
      }
    }
  
    static textInput(promptName, contentName, systemPrompt = S2sEvent.DEFAULT_SYSTEM_PROMPT) {
      var evt = {
        "event": {
          "textInput": {
            "promptName": promptName,
            "contentName": contentName,
            "content": systemPrompt
          }
        }
      }
      return evt;
    }
  
    static contentEnd(promptName, contentName) {
      return {
        "event": {
          "contentEnd": {
            "promptName": promptName,
            "contentName": contentName
          }
        }
      }
    }
  
    static contentStartAudio(promptName, contentName, audioInputConfig = S2sEvent.DEFAULT_AUDIO_INPUT_CONFIG) {
      return {
        "event": {
          "contentStart": {
            "promptName": promptName,
            "contentName": contentName,
            "type": "AUDIO",
            "interactive": true,
            "role": "USER",
            "audioInputConfiguration": {
              "mediaType": "audio/lpcm",
              "sampleRateHertz": 16000,
              "sampleSizeBits": 16,
              "channelCount": 1,
              "audioType": "SPEECH",
              "encoding": "base64"
            }
          }
        }
      }
    }
  
    static audioInput(promptName, contentName, content) {
      return {
        event: {
          audioInput: {
            promptName,
            contentName,
            content,
          }
        }
      };
    }
  
    static contentStartTool(promptName, contentName, toolUseId) {
      return {
        event: {
          contentStart: {
            promptName,
            contentName,
            interactive: false,
            type: "TOOL",
            toolResultInputConfiguration: {
              toolUseId,
              type: "TEXT",
              textInputConfiguration: { mediaType: "text/plain" }
            }
          }
        }
      };
    }
  
    static textInputTool(promptName, contentName, content) {
      return {
        event: {
          textInput: {
            promptName,
            contentName,
            content,
            role: "TOOL"
          }
        }
      };
    }
  
    static promptEnd(promptName) {
      return {
        event: {
          promptEnd: {
            promptName
          }
        }
      };
    }
  
    static sessionEnd() {
      return { event: { sessionEnd: {} } };
    }
  }
  export default S2sEvent;