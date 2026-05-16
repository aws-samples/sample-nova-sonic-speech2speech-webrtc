"""S2S Event definitions for Nova Sonic bidirectional streaming."""

DEFAULT_SYSTEM_PROMPT = (
    "You are Nova, a helpful AI assistant participating in a multi-party conversation with two human participants. "
    "When someone addresses you directly, respond helpfully and concisely. "
    "When participants are clearly talking to each other, stay quiet. "
    "Keep responses to 1-3 sentences unless asked for detail."
)

DEFAULT_INFER_CONFIG = {"maxTokens": 512, "topP": 0.9, "temperature": 0.7}

DEFAULT_AUDIO_INPUT_CONFIG = {
    "mediaType": "audio/lpcm",
    "sampleRateHertz": 16000,
    "sampleSizeBits": 16,
    "channelCount": 1,
    "audioType": "SPEECH",
    "encoding": "base64",
}

DEFAULT_AUDIO_OUTPUT_CONFIG = {
    "mediaType": "audio/lpcm",
    "sampleRateHertz": 24000,
    "sampleSizeBits": 16,
    "channelCount": 1,
    "voiceId": "matthew",
    "encoding": "base64",
    "audioType": "SPEECH",
}


def session_start(inference_config=None):
    return {"event": {"sessionStart": {"inferenceConfiguration": inference_config or DEFAULT_INFER_CONFIG}}}


def prompt_start(prompt_name, audio_output_config=None):
    return {
        "event": {
            "promptStart": {
                "promptName": prompt_name,
                "textOutputConfiguration": {"mediaType": "text/plain"},
                "audioOutputConfiguration": audio_output_config or DEFAULT_AUDIO_OUTPUT_CONFIG,
                "toolUseOutputConfiguration": {"mediaType": "application/json"},
            }
        }
    }


def content_start_text(prompt_name, content_name, role="SYSTEM"):
    return {
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": content_name,
                "type": "TEXT",
                "interactive": True,
                "role": role,
                "textInputConfiguration": {"mediaType": "text/plain"},
            }
        }
    }


def text_input(prompt_name, content_name, content=DEFAULT_SYSTEM_PROMPT):
    return {"event": {"textInput": {"promptName": prompt_name, "contentName": content_name, "content": content}}}


def content_end(prompt_name, content_name):
    return {"event": {"contentEnd": {"promptName": prompt_name, "contentName": content_name}}}


def content_start_audio(prompt_name, content_name, audio_input_config=None):
    return {
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": content_name,
                "type": "AUDIO",
                "interactive": True,
                "role": "USER",
                "audioInputConfiguration": audio_input_config or DEFAULT_AUDIO_INPUT_CONFIG,
            }
        }
    }


def audio_input(prompt_name, content_name, content):
    return {"event": {"audioInput": {"promptName": prompt_name, "contentName": content_name, "content": content}}}


def session_end():
    return {"event": {"sessionEnd": {}}}


def prompt_end(prompt_name):
    return {"event": {"promptEnd": {"promptName": prompt_name}}}
