/**
 * MultiPartyConnection - KVS WebRTC Viewer for multi-party conversation.
 * Connects to the server (Master) via KVS signaling channel.
 */
import { SignalingClient, Role } from 'amazon-kinesis-video-streams-webrtc';
import AWS from 'aws-sdk';
import 'aws-sdk/clients/kinesisvideosignalingchannels';

export default class MultiPartyConnection {
  constructor() {
    this.signalingClient = null;
    this.peerConnection = null;
    this.localStream = null;
    this.dataChannel = null;
    this.isMuted = false;

    this.onConnected = null;
    this.onDisconnected = null;
    this.onTextMessage = null;
    this.onError = null;
  }

  async connect({ channelName, region, credentials, clientId }) {
    const kinesisVideo = new AWS.KinesisVideo({ region, credentials, correctClockSkew: true });

    const { ChannelInfo } = await kinesisVideo.describeSignalingChannel({ ChannelName: channelName }).promise();
    const channelARN = ChannelInfo.ChannelARN;

    const epResp = await kinesisVideo.getSignalingChannelEndpoint({
      ChannelARN: channelARN,
      SingleMasterChannelEndpointConfiguration: { Protocols: ['WSS', 'HTTPS'], Role: Role.VIEWER },
    }).promise();
    const endpoints = epResp.ResourceEndpointList.reduce((acc, ep) => { acc[ep.Protocol] = ep.ResourceEndpoint; return acc; }, {});

    let iceServers = [{ urls: `stun:stun.kinesisvideo.${region}.amazonaws.com:443` }];
    try {
      const sigChannels = new AWS.KinesisVideoSignalingChannels({ region, credentials, endpoint: endpoints.HTTPS });
      const iceResp = await sigChannels.getIceServerConfig({ ChannelARN: channelARN, ClientId: clientId }).promise();
      iceResp.IceServerList.forEach(s => iceServers.push({ urls: s.Uris, username: s.Username, credential: s.Password }));
    } catch (e) {
      console.warn('[MultiParty] TURN unavailable, using STUN only');
    }

    this.localStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 16000, channelCount: 1 },
      video: false,
    });

    this.signalingClient = new SignalingClient({
      channelARN,
      channelEndpoint: endpoints.WSS,
      clientId,
      role: Role.VIEWER,
      region,
      credentials,
      systemClockOffset: kinesisVideo.config.systemClockOffset,
    });

    this.peerConnection = new RTCPeerConnection({ iceServers, iceTransportPolicy: 'all' });

    this.localStream.getTracks().forEach(t => this.peerConnection.addTrack(t, this.localStream));

    this.peerConnection.ontrack = (event) => {
      if (event.track.kind === 'audio') {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const stream = event.streams[0] || new MediaStream([event.track]);
        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(audioCtx.destination);
        if (audioCtx.state === 'suspended') audioCtx.resume();
        this._audioContext = audioCtx;
      }
    };

    this.dataChannel = this.peerConnection.createDataChannel('kvsDataChannel', { ordered: true });
    this.dataChannel.onmessage = (event) => this._handleDataMessage(event);

    this.peerConnection.ondatachannel = (event) => {
      event.channel.onmessage = (e) => this._handleDataMessage(e);
    };

    this.peerConnection.onconnectionstatechange = () => {
      const state = this.peerConnection.connectionState;
      if (state === 'connected' && this.onConnected) this.onConnected();
      if ((state === 'disconnected' || state === 'failed' || state === 'closed') && this.onDisconnected) this.onDisconnected();
    };

    let signalingOpen = false;
    const pendingCandidates = [];

    this.peerConnection.onicecandidate = (event) => {
      if (event.candidate) {
        if (signalingOpen) {
          this.signalingClient.sendIceCandidate(event.candidate);
        } else {
          pendingCandidates.push(event.candidate);
        }
      }
    };

    const offer = await this.peerConnection.createOffer({ offerToReceiveAudio: true });
    await this.peerConnection.setLocalDescription(offer);

    this.signalingClient.on('open', () => {
      signalingOpen = true;
      this.signalingClient.sendSdpOffer(this.peerConnection.localDescription);
      pendingCandidates.forEach(c => this.signalingClient.sendIceCandidate(c));
      pendingCandidates.length = 0;
    });

    this.signalingClient.on('sdpAnswer', async (answer) => {
      await this.peerConnection.setRemoteDescription(answer);
    });

    this.signalingClient.on('iceCandidate', async (candidate) => {
      await this.peerConnection.addIceCandidate(candidate);
    });

    this.signalingClient.on('error', (err) => {
      if (this.onError) this.onError(err);
    });

    this.signalingClient.open();
  }

  _handleDataMessage(event) {
    try {
      const msg = JSON.parse(event.data);
      // Handle S2S_RESPONSE wrapper from EventBridge
      const payload = msg.type === 'S2S_RESPONSE' ? msg.event : msg;
      if (payload && payload.event) {
        const evType = Object.keys(payload.event)[0];
        if (evType === 'textOutput' && this.onTextMessage) {
          const d = payload.event.textOutput;
          this.onTextMessage({
            role: d.role,
            content: d.content,
            speaker: payload.speaker || null,
            isSelf: payload.isSelf || false,
          });
        }
      }
    } catch (e) {
      console.error('[MultiParty] DC parse error', e);
    }
  }

  toggleMute() {
    this.isMuted = !this.isMuted;
    if (this.localStream) {
      this.localStream.getAudioTracks().forEach(t => { t.enabled = !this.isMuted; });
    }
    return this.isMuted;
  }

  disconnect() {
    if (this.localStream) this.localStream.getTracks().forEach(t => t.stop());
    if (this.dataChannel) this.dataChannel.close();
    if (this.peerConnection) this.peerConnection.close();
    if (this.signalingClient) this.signalingClient.close();
    if (this._audioContext) this._audioContext.close();
    this.localStream = null;
    this.dataChannel = null;
    this.peerConnection = null;
    this.signalingClient = null;
    this._audioContext = null;
  }
}
