import React, { useState, useRef, useEffect } from 'react';
import MultiPartyConnection from './MultiPartyConnection';

export default function ParticipantPanel({ participantName, channelName, region, credentials, color }) {
  const [connected, setConnected] = useState(false);
  const [muted, setMuted] = useState(false);
  const [status, setStatus] = useState('idle');
  const [messages, setMessages] = useState([]);
  const connRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const addMessage = (msg) => setMessages(prev => [...prev, { ...msg, ts: Date.now() }]);

  const handleConnect = async () => {
    if (connected) {
      connRef.current?.disconnect();
      connRef.current = null;
      setConnected(false);
      setStatus('idle');
      setMuted(false);
      return;
    }

    const conn = new MultiPartyConnection();
    connRef.current = conn;

    conn.onConnected = () => {
      setConnected(true);
      setStatus('connected');
      addMessage({ type: 'system', content: 'Connected to conversation' });
    };

    conn.onDisconnected = () => {
      setConnected(false);
      setStatus('idle');
      addMessage({ type: 'system', content: 'Disconnected' });
    };

    conn.onTextMessage = (msg) => {
      // Filter out interrupted JSON messages
      if (msg.content && msg.content.trim().startsWith('{') && msg.content.includes('interrupted')) {
        return;
      }
      if (msg.role === 'USER') {
        const label = msg.isSelf ? 'You' : 'Other';
        addMessage({ type: 'chat', role: msg.role, content: msg.content, label, isSelf: msg.isSelf });
      } else {
        addMessage({ type: 'chat', role: msg.role, content: msg.content, label: 'Nova' });
      }
    };

    conn.onError = (err) => {
      addMessage({ type: 'system', content: `Error: ${err.message || err}` });
      setStatus('error');
    };

    try {
      setStatus('connecting');
      const clientId = `${participantName}-${crypto.randomUUID().slice(0, 8)}`;
      await conn.connect({ channelName, region, credentials, clientId });
    } catch (err) {
      addMessage({ type: 'system', content: `Failed: ${err.message || err}` });
      setStatus('error');
    }
  };

  const handleMute = () => {
    if (connRef.current) setMuted(connRef.current.toggleMute());
  };

  const statusColor = { connected: '#037f0c', connecting: '#ff9800', idle: '#9e9e9e', error: '#d91515' }[status] || '#9e9e9e';

  return (
    <div className="participant-panel" style={{ borderTop: `3px solid ${color}` }}>
      <div className="panel-header">
        <span className="name">
          <span className="status-dot" style={{ background: statusColor }} />
          {participantName}
        </span>
        <span className="status-text">{status}</span>
      </div>

      <div className="controls">
        <button
          className={connected ? 'btn-leave' : 'btn-join'}
          onClick={handleConnect}
        >
          {connected ? '⏹ Leave' : '🎤 Join'}
        </button>
        {connected && (
          <button
            className={muted ? 'btn-unmute' : 'btn-mute'}
            onClick={handleMute}
          >
            {muted ? '🔇 Unmute' : '🔊 Mute'}
          </button>
        )}
      </div>

      <div className="chatarea">
        {messages.length === 0 && (
          <p className="empty">
            {connected ? 'Listening... speak to start' : 'Click "Join" to connect'}
          </p>
        )}
        {messages.map((msg, i) => {
          if (msg.type === 'system') {
            return <div key={i} className="system-msg">{msg.content}</div>;
          }
          const isUser = msg.role === 'USER';
          const isBot = msg.role === 'ASSISTANT';
          const className = isBot ? 'bot' : (msg.isSelf ? 'user' : 'other');
          const icon = isBot ? '🤖' : (msg.isSelf ? '🧑' : '👤');
          return (
            <div key={i} className="item">
              <div className={className}>
                <span className="label">{icon} {msg.label}</span>
                {msg.content}
              </div>
            </div>
          );
        })}
        <div className="endbar" ref={messagesEndRef} />
      </div>
    </div>
  );
}
