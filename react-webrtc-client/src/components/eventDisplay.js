import React from 'react';
import './eventDisplay.css'
import { Icon, Button, Modal, Box, SpaceBetween, Toggle } from '@cloudscape-design/components';

class S2sEventDisplay extends React.Component {

    constructor(props) {
        super(props);
        this.state = {
            audioInputIndex: 0,
            eventsByContentName: [],

            selectedEvent: null,
            showEventJson: false,

            displayUsage: false,
        };
        this.message = null;
        this.reset= false;
    }

    componentDidUpdate(prevProps, prevState) {
        if (prevProps.message !== this.props.message) {
            this.displayEvent(this.props.message);
        }
    }

    cleanup() {
        this.setState({
                eventsByContentName: [], 
                audioInputIndex: 0,
                selectedEvent: null,
                showEventJson: false
            });
    }

    getEventDisplayName(event) {
        if (event.name === "audioInput" && event.events.length > 0) {
            // Get the latest event to show current stats
            const latestEvent = event.events[event.events.length - 1];
            const audioInputData = latestEvent.event.audioInput;
            
            if (audioInputData && audioInputData.packetsCount !== undefined) {
                // Show audioInput with packet count and data size
                const packets = audioInputData.packetsCount;
                const bytes = audioInputData.dataSize || 0;
                return `audioInput (${packets} packets, ${bytes} bytes)`;
            }
        }
        
        return event.name;
    }

    updateAudioInputEvent(newEvent) {
        // Find and update existing audioInput event instead of creating a new one
        let eventsByContentName = this.state.eventsByContentName;
        const eventName = Object.keys(newEvent?.event)[0];
        const contentName = newEvent.event[eventName].contentName;
        
        if (eventName === "audioInput") {
            // Look for existing audioInput event with same contentName
            for (let i = 0; i < eventsByContentName.length; i++) {
                const item = eventsByContentName[i];
                if (item.name === "audioInput" && item.key.includes(contentName)) {
                    // Update the existing event
                    item.events[item.events.length - 1] = newEvent; // Update the latest event
                    item.ts = Date.now(); // Update timestamp
                    this.setState({eventsByContentName: eventsByContentName});
                    return;
                }
            }
        }
        
        // If no existing audioInput event found, create new one (fallback)
        this.displayEvent(newEvent, "out");
    }
    
    displayEvent(event, type) {
        if (event && event.event) {
            const eventName = Object.keys(event?.event)[0];
            
            // Debug log for all events to track completionEnd
            console.log(`[EventDisplay] Processing event: ${eventName} (type: ${type})`, event);
            
            // Special debug for completion events
            if (eventName === "completionStart" || eventName === "completionEnd") {
                console.log(`[EventDisplay] ⭐ COMPLETION EVENT: ${eventName}`, {
                    eventData: event.event[eventName],
                    fullEvent: event
                });
            }
            let key = null;
            let ts = Date.now();
            let interrupted = false;
            // Safely extract event properties (some events may not have all fields)
            const contentType = event.event[eventName]?.type || 'unknown';
            const contentName = event.event[eventName]?.contentName || 'unnamed';
            const contentId = event.event[eventName]?.contentId || 'no-id';

            if (eventName === "audioOutput") {
                // Use contentId and a time window to group related audioOutput events
                const timeWindow = Math.floor(ts / 1000); // Group events within same second
                key = `${eventName}-${contentId}-${timeWindow}`;
                // truncate event audio content
                event.event.audioOutput.content = event.event.audioOutput.content.substr(0,10);
            }
            else if (eventName === "audioInput") {
                // Handle WebRTC Media Channel audioInput events with stats
                const audioStats = event.audioTransmissionStats;
                if (audioStats) {
                    // Use action to determine if this is a new session or update
                    if (audioStats.action === 'start') {
                        this.setState({audioInputIndex: this.state.audioInputIndex + 1});
                    }
                    key = `${eventName}-${contentName}-${this.state.audioInputIndex}`;
                } else {
                    // Legacy audioInput event
                    key = `${eventName}-${contentName}-${this.state.audioInputIndex}`;
                }
            }
            else if (eventName === "contentStart" || eventName === "textInput" || eventName === "contentEnd") {
                // Always use timestamp for contentEnd to prevent incorrect merging
                if (eventName === "contentEnd") {
                    key = `${eventName}-${contentName}-${contentType}-${ts}`;
                } else {
                    key = `${eventName}}-${contentName}-${contentType}`;
                }
                
                if (type === "in" && event.event[eventName].type === "AUDIO") {
                    this.setState({audioInputIndex: this.state.audioInputIndex + 1});
                }
                else if(type === "out" && eventName !== "contentEnd") {
                    key = `${eventName}-${contentName}-${contentType}-${ts}`;
                }
            }
            else if(eventName === "textOutput") {
                const role = event.event[eventName].role;
                const content = event.event[eventName].content;
                if (role === "ASSISTANT" && content.startsWith("{")) {
                    const evt = JSON.parse(content);
                    interrupted = evt.interrupted === true;
                }
                key = `${eventName}-${ts}`;
            }
            else if (eventName === "completionStart" || eventName === "completionEnd") {
                // Always use timestamp for completion events to show each one separately
                key = `${eventName}-${ts}`;
            }
            else {
                key = `${eventName}-${ts}`;
            }

            let eventsByContentName = this.state.eventsByContentName;
            if (eventsByContentName === null)
                eventsByContentName = [];

            let exists = false;
            // Only allow merging for audioInput and audioOutput events
            const allowMerging = eventName === "audioInput" || eventName === "audioOutput";
            
            if (allowMerging) {
                for(var i=0;i<eventsByContentName.length;i++) {
                    var item = eventsByContentName[i];
                    if (item.key === key && item.type === type) {
                        item.events.push(event);
                        item.interrupted = interrupted;
                        item.ts = ts; // Update timestamp to latest
                        exists = true;
                        break;
                    }
                }
            }
            if (!exists) {
                const item = {
                    key: key, 
                    name: eventName, 
                    type: type, 
                    events: [event], 
                    ts: ts,
                    interrupted: interrupted,
                };
                
                eventsByContentName.unshift(item);
            }
            this.setState({eventsByContentName: eventsByContentName});
        }
    }

    render() {
        return (
            <div>
                <div className="toggleUsage">
                <Toggle
                    onChange={({ detail }) =>
                        this.setState({displayUsage: detail.checked })
                    }
                    checked={this.state.displayUsage}
                    >
                    Display Usage Event
                </Toggle>
                </div>
                <div className='events'>
                    {this.state.eventsByContentName.map((event, index)=>{
                        if (!this.state.displayUsage && event.name === "usageEvent")
                            return null;
                        else return <div key={index} className={
                                event.name === "toolUse"? "event-tool": 
                                event.name === "usageEvent"? "event-usage": 
                                event.interrupted === true?"event-int":
                                event.type === "in"?"event-in":"event-out"
                            } 
                            onClick={() => {
                                this.setState({selectedEvent: event, showEventJson: true});
                            }}
                            >
                            <Icon name={event.type === "in"? "arrow-down": "arrow-up"} />&nbsp;&nbsp;
                            {this.getEventDisplayName(event)}
                            {event.events.length > 1? ` (${event.events.length})`: ""}
                            <div className="tooltip">
                                <pre id="jsonDisplay">{event.events.map((e, eIndex)=>{
                                    return JSON.stringify(e,null,2);
                                })
                            }</pre>
                            </div>
                        </div>
                    })}
                    <Modal
                        onDismiss={() => this.setState({showEventJson: false})}
                        visible={this.state.showEventJson}
                        header="Event details"
                        size='medium'
                        footer={
                            <Box float="right">
                            <SpaceBetween direction="horizontal" size="xs">
                                <Button variant="link" onClick={() => this.setState({showEventJson: false})}>Close</Button>
                            </SpaceBetween>
                            </Box>
                        }
                    >
                        <div className='eventdetail'>
                        <pre id="jsonDisplay">
                            {this.state.selectedEvent && this.state.selectedEvent.events.map(e=>{
                                const eventType = Object.keys(e?.event)[0];
                                if (eventType === "audioInput" || eventType === "audioOutput")
                                    e.event[eventType].content = e.event[eventType].content.substr(0,10) + "...";
                                const ts = new Date(e.timestamp).toLocaleString(undefined, {
                                    year: "numeric",
                                    month: "2-digit",
                                    day: "2-digit",
                                    hour: "2-digit",
                                    minute: "2-digit",
                                    second: "2-digit",
                                    fractionalSecondDigits: 3, // Show milliseconds
                                    hour12: false // 24-hour format
                                });
                                var displayJson = { ...e };
                                delete displayJson.timestamp;
                                return ts + "\n" + JSON.stringify(displayJson,null,2) + "\n";
                            })}
                        </pre>
                        </div>
                    </Modal>
                </div>
            </div>
        );
    }
}

export default S2sEventDisplay;