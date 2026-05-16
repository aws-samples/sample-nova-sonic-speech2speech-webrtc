import React from 'react';
import ParticipantPanel from './ParticipantPanel';

const REGION = process.env.REACT_APP_AWS_REGION || 'us-east-1';
const CHANNEL_NAME = process.env.REACT_APP_KVS_CHANNEL_NAME || 'nova-s2s-webrtc-test';

const credentials = {
  accessKeyId: process.env.REACT_APP_AWS_ACCESS_KEY_ID,
  secretAccessKey: process.env.REACT_APP_AWS_SECRET_ACCESS_KEY,
  sessionToken: process.env.REACT_APP_AWS_SESSION_TOKEN,
};

const DEFAULT_NAMES = ['Alice', 'Bob'];
const participantCount = Math.min(5, Math.max(1, parseInt(process.env.REACT_APP_PARTICIPANT_COUNT || '2', 10)));
const envNames = (process.env.REACT_APP_PARTICIPANT_NAMES || '').split(',').map(n => n.trim()).filter(Boolean);
const participants = Array.from({ length: participantCount }, (_, i) => envNames[i] || DEFAULT_NAMES[i] || `P${i + 1}`);

const COLORS = ['#0972d3', '#e65100'];

export default function App() {
  return (
    <div className="multi-party">
      <div className="header">
        <h1>🎙️ Multi-Party Nova Sonic Conversation</h1>
        <p>{participantCount} participant{participantCount > 1 ? 's' : ''} + Nova Sonic AI Agent</p>
      </div>

      <div className="info-bar">
        Channel: <strong>{CHANNEL_NAME}</strong> &nbsp;|&nbsp; Region: <strong>{REGION}</strong>
      </div>

      <div className="panels">
        {participants.map((name, i) => (
          <ParticipantPanel
            key={name}
            participantName={name}
            channelName={CHANNEL_NAME}
            region={REGION}
            credentials={credentials}
            color={COLORS[i % COLORS.length]}
          />
        ))}
      </div>
    </div>
  );
}
