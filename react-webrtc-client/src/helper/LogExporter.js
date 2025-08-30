/**
 * LogExporter - Utility for exporting client-side logs to files
 * Provides correlation IDs and timestamp synchronization with server logs
 */

class LogExporter {
    constructor() {
        this.logs = [];
        this.maxLogs = 2000; // Keep last 2000 log entries (increased for console capture)
        this.sessionId = this.generateSessionId();
        this.startTime = Date.now();
        
        // Store original console methods
        this.originalConsole = {
            log: console.log,
            info: console.info,
            warn: console.warn,
            error: console.error,
            debug: console.debug
        };
        
        // Intercept console methods to capture all logs
        this.interceptConsole();
        
        console.log(`[LogExporter] Initialized with session ID: ${this.sessionId}`);
        console.log(`[LogExporter] Console interception enabled - capturing all console output`);
    }
    
    generateSessionId() {
        return `client-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }
    
    generateCorrelationId() {
        return `corr-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }
    
    interceptConsole() {
        const self = this;
        
        // Intercept console.log
        console.log = function(...args) {
            self.captureConsoleOutput('INFO', 'Console', args);
            self.originalConsole.log.apply(console, args);
        };
        
        // Intercept console.info
        console.info = function(...args) {
            self.captureConsoleOutput('INFO', 'Console', args);
            self.originalConsole.info.apply(console, args);
        };
        
        // Intercept console.warn
        console.warn = function(...args) {
            self.captureConsoleOutput('WARN', 'Console', args);
            self.originalConsole.warn.apply(console, args);
        };
        
        // Intercept console.error
        console.error = function(...args) {
            self.captureConsoleOutput('ERROR', 'Console', args);
            self.originalConsole.error.apply(console, args);
        };
        
        // Intercept console.debug
        console.debug = function(...args) {
            self.captureConsoleOutput('DEBUG', 'Console', args);
            self.originalConsole.debug.apply(console, args);
        };
    }
    
    captureConsoleOutput(level, component, args) {
        try {
            // Convert arguments to a readable format
            const message = args.map(arg => {
                if (typeof arg === 'string') {
                    return arg;
                } else if (typeof arg === 'object') {
                    try {
                        return JSON.stringify(arg, null, 2);
                    } catch (e) {
                        return '[Object]';
                    }
                } else {
                    return String(arg);
                }
            }).join(' ');
            
            // Extract component name from message if available
            let detectedComponent = component;
            const componentMatch = message.match(/\[([^\]]+)\]/);
            if (componentMatch) {
                detectedComponent = componentMatch[1];
            }
            
            // Store the log entry
            const timestamp = Date.now();
            const logEntry = {
                timestamp,
                sessionId: this.sessionId,
                correlationId: this.generateCorrelationId(),
                level,
                component: detectedComponent,
                message,
                data: args.length > 1 ? args.slice(1) : null,
                relativeTime: timestamp - this.startTime,
                source: 'console'
            };
            
            // Add to internal log storage
            this.logs.push(logEntry);
            
            // Keep only the last maxLogs entries
            if (this.logs.length > this.maxLogs) {
                this.logs = this.logs.slice(-this.maxLogs);
            }
        } catch (error) {
            // Avoid infinite recursion by using original console
            this.originalConsole.error('[LogExporter] Error capturing console output:', error);
        }
    }
    
    restoreConsole() {
        console.log = this.originalConsole.log;
        console.info = this.originalConsole.info;
        console.warn = this.originalConsole.warn;
        console.error = this.originalConsole.error;
        console.debug = this.originalConsole.debug;
    }
    
    log(level, component, message, data = null, correlationId = null) {
        const timestamp = Date.now();
        const logEntry = {
            timestamp,
            sessionId: this.sessionId,
            correlationId: correlationId || this.generateCorrelationId(),
            level,
            component,
            message,
            data,
            relativeTime: timestamp - this.startTime
        };
        
        // Add to internal log storage
        this.logs.push(logEntry);
        
        // Keep only the last maxLogs entries
        if (this.logs.length > this.maxLogs) {
            this.logs = this.logs.slice(-this.maxLogs);
        }
        
        // Also log to console with enhanced format
        const formattedMessage = `${new Date(timestamp).toISOString()} [${level}] [${component}] ${message}`;
        if (correlationId) {
            console.log(`${formattedMessage} (ID: ${correlationId})`, data || '');
        } else {
            console.log(formattedMessage, data || '');
        }
        
        return logEntry.correlationId;
    }
    
    info(component, message, data = null, correlationId = null) {
        return this.log('INFO', component, message, data, correlationId);
    }
    
    warn(component, message, data = null, correlationId = null) {
        return this.log('WARN', component, message, data, correlationId);
    }
    
    error(component, message, data = null, correlationId = null) {
        return this.log('ERROR', component, message, data, correlationId);
    }
    
    debug(component, message, data = null, correlationId = null) {
        return this.log('DEBUG', component, message, data, correlationId);
    }
    
    async exportToFile(filename = null) {
        if (!filename) {
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            filename = `webrtc-client-logs-${timestamp}.json`;
        }
        
        // Separate logs by source for better analysis
        const logExporterLogs = this.logs.filter(log => log.source !== 'console');
        const consoleLogs = this.logs.filter(log => log.source === 'console');
        
        const exportData = {
            sessionId: this.sessionId,
            exportTime: Date.now(),
            startTime: this.startTime,
            totalLogs: this.logs.length,
            logExporterLogs: logExporterLogs.length,
            consoleLogs: consoleLogs.length,
            logs: this.logs,
            logsBySource: {
                logExporter: logExporterLogs,
                console: consoleLogs
            },
            exportInfo: {
                note: "Complete client-side logs including console output and LogExporter entries",
                serverLogFile: "webrtc_server.log",
                analysisInstructions: "Compare correlation IDs between client and server logs",
                logSources: {
                    console: "All console.log/info/warn/error output from the browser",
                    logExporter: "Structured logs from LogExporter.info/warn/error methods"
                }
            }
        };
        
        const dataStr = JSON.stringify(exportData, null, 2);
        
        // Try to use File System Access API for automatic saving (Chrome/Edge)
        if (window.showSaveFilePicker) {
            try {
                const fileHandle = await window.showSaveFilePicker({
                    suggestedName: filename,
                    types: [{
                        description: 'JSON files',
                        accept: { 'application/json': ['.json'] }
                    }]
                });
                
                const writable = await fileHandle.createWritable();
                await writable.write(dataStr);
                await writable.close();
                
                console.log(`[LogExporter] Exported ${this.logs.length} log entries to ${filename} using File System Access API`);
                return filename;
            } catch (error) {
                if (error.name !== 'AbortError') {
                    console.warn('[LogExporter] File System Access API failed, falling back to download:', error);
                }
                // Fall through to download method
            }
        }
        
        // Fallback to download method
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(dataBlob);
        link.download = filename;
        link.click();
        
        console.log(`[LogExporter] Exported ${this.logs.length} log entries to ${filename}`);
        console.log(`[LogExporter] Save the downloaded file to nova-s2s-workshop/logs/ folder for analysis`);
        return filename;
    }
    
    exportToText(filename = null) {
        if (!filename) {
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            filename = `webrtc-client-logs-${timestamp}.txt`;
        }
        
        const logExporterLogs = this.logs.filter(log => log.source !== 'console');
        const consoleLogs = this.logs.filter(log => log.source === 'console');
        
        let textContent = `WebRTC Client Logs (Complete Capture)\n`;
        textContent += `Session ID: ${this.sessionId}\n`;
        textContent += `Export Time: ${new Date().toISOString()}\n`;
        textContent += `Total Logs: ${this.logs.length}\n`;
        textContent += `  - Console Logs: ${consoleLogs.length}\n`;
        textContent += `  - LogExporter Logs: ${logExporterLogs.length}\n`;
        textContent += `Server Log Location: nova-s2s-workshop/logs/webrtc_server.log\n`;
        textContent += `Analysis: Compare correlation IDs between this file and server log\n`;
        textContent += `${'='.repeat(80)}\n\n`;
        
        this.logs.forEach(log => {
            const timestamp = new Date(log.timestamp).toISOString();
            const source = log.source === 'console' ? 'CONSOLE' : 'LOGGER';
            textContent += `${timestamp} [${log.level}] [${source}] [${log.component}] ${log.message}`;
            if (log.correlationId && log.source !== 'console') {
                textContent += ` (ID: ${log.correlationId})`;
            }
            if (log.data && log.data.length > 0) {
                textContent += `\n  Data: ${JSON.stringify(log.data)}`;
            }
            textContent += '\n';
        });
        
        const dataBlob = new Blob([textContent], { type: 'text/plain' });
        
        const link = document.createElement('a');
        link.href = URL.createObjectURL(dataBlob);
        link.download = filename;
        link.click();
        
        console.log(`[LogExporter] Exported ${this.logs.length} log entries to ${filename}`);
        console.log(`[LogExporter] Save the downloaded file to nova-s2s-workshop/logs/ folder for analysis`);
        return filename;
    }
    
    getLogsForTimeRange(startTime, endTime) {
        return this.logs.filter(log => 
            log.timestamp >= startTime && log.timestamp <= endTime
        );
    }
    
    getLogsByCorrelationId(correlationId) {
        return this.logs.filter(log => log.correlationId === correlationId);
    }
    
    getLogsByComponent(component) {
        return this.logs.filter(log => log.component === component);
    }
    
    async autoExportToLogsFolder() {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const filename = `webrtc-client-logs-${timestamp}.json`;
        
        const exportData = {
            sessionId: this.sessionId,
            exportTime: Date.now(),
            startTime: this.startTime,
            totalLogs: this.logs.length,
            logs: this.logs,
            autoExport: true,
            exportInfo: {
                note: "Automatically exported to logs folder for analysis with server logs",
                serverLogFile: "webrtc_server.log",
                analysisInstructions: "Run 'python analyze_logs.py' in the logs folder"
            }
        };
        
        const dataStr = JSON.stringify(exportData, null, 2);
        
        // Try File System Access API with suggested directory
        if (window.showDirectoryPicker) {
            try {
                // Show directory picker with suggestion to select logs folder
                const dirHandle = await window.showDirectoryPicker({
                    id: 'logs-folder',
                    startIn: 'documents'
                });
                
                const fileHandle = await dirHandle.getFileHandle(filename, { create: true });
                const writable = await fileHandle.createWritable();
                await writable.write(dataStr);
                await writable.close();
                
                console.log(`[LogExporter] ✅ AUTO-EXPORTED to logs folder: ${filename}`);
                alert(`✅ Logs automatically exported to logs folder!\nFile: ${filename}\nRun 'python analyze_logs.py' to analyze.`);
                return filename;
            } catch (error) {
                if (error.name !== 'AbortError') {
                    console.warn('[LogExporter] Directory picker failed:', error);
                }
            }
        }
        
        // Fallback: Download with clear instructions
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(dataBlob);
        link.download = filename;
        link.click();
        
        console.log(`[LogExporter] Downloaded ${filename} - please save to nova-s2s-workshop/logs/ folder`);
        
        // Show helpful instructions
        const instructions = `
📁 SAVE LOCATION INSTRUCTIONS:
1. Move the downloaded file to: nova-s2s-workshop/logs/
2. Run analysis: cd logs && python analyze_logs.py
3. The script will automatically find and analyze both client and server logs

File downloaded: ${filename}
        `.trim();
        
        alert(instructions);
        return filename;
    }
    
    clearLogs() {
        this.logs = [];
        console.log('[LogExporter] Logs cleared');
    }
    
    getStats() {
        const logExporterLogs = this.logs.filter(log => log.source !== 'console');
        const consoleLogs = this.logs.filter(log => log.source === 'console');
        
        const stats = {
            totalLogs: this.logs.length,
            consoleLogs: consoleLogs.length,
            logExporterLogs: logExporterLogs.length,
            sessionId: this.sessionId,
            startTime: this.startTime,
            uptime: Date.now() - this.startTime,
            logsByLevel: {},
            logsByComponent: {},
            logsBySource: {
                console: consoleLogs.length,
                logExporter: logExporterLogs.length
            }
        };
        
        this.logs.forEach(log => {
            stats.logsByLevel[log.level] = (stats.logsByLevel[log.level] || 0) + 1;
            stats.logsByComponent[log.component] = (stats.logsByComponent[log.component] || 0) + 1;
        });
        
        return stats;
    }
}

// Create global instance
const logExporter = new LogExporter();

export default logExporter;