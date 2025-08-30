"""
PerformanceMonitor - Monitors WebRTC performance and resource usage for Python server
Tracks connection metrics, audio processing performance, and system resources
"""

import asyncio
import logging
import psutil
import time
from typing import Dict, List, Optional, Callable, Any
from collections import deque
import json
import threading
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetrics:
    """Performance metrics data structure"""
    timestamp: float
    
    # Connection metrics
    active_connections: int = 0
    total_connections: int = 0
    connection_failures: int = 0
    
    # Audio processing metrics
    audio_frames_processed: int = 0
    audio_bytes_processed: int = 0
    audio_processing_latency: float = 0.0
    audio_conversion_errors: int = 0
    
    # Event processing metrics
    events_received: int = 0
    events_sent: int = 0
    event_processing_errors: int = 0
    
    # System resource metrics
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    memory_usage_mb: float = 0.0
    
    # Network metrics
    bytes_received: int = 0
    bytes_sent: int = 0
    
    # Quality metrics
    packet_loss_rate: float = 0.0
    jitter: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)

class PerformanceMonitor:
    """
    Monitors WebRTC server performance and resource usage
    Provides metrics collection, analysis, and optimization recommendations
    """
    
    def __init__(self):
        self.is_monitoring = False
        self.monitoring_task = None
        self.metrics_history: deque = deque(maxlen=1000)  # Keep last 1000 measurements
        
        # Current metrics
        self.current_metrics = PerformanceMetrics(timestamp=time.time())
        
        # Baseline metrics for comparison
        self.baseline_metrics: Optional[PerformanceMetrics] = None
        
        # Performance thresholds
        self.thresholds = {
            'cpu_usage': 80.0,           # %
            'memory_usage': 80.0,        # %
            'audio_latency': 100.0,      # ms
            'packet_loss_rate': 5.0,     # %
            'jitter': 50.0,              # ms
            'connection_failures': 10,    # count per minute
            'processing_errors': 5        # count per minute
        }
        
        # Monitoring configuration
        self.monitoring_interval = 1.0  # seconds
        self.collection_lock = threading.Lock()
        
        # Callbacks
        self.on_metrics_update: Optional[Callable] = None
        self.on_threshold_exceeded: Optional[Callable] = None
        
        # Component references for metrics collection
        self.kvs_master = None
        self.audio_processor = None
        self.event_bridge = None
        
        # Counters for rate calculations
        self.last_metrics_time = time.time()
        self.rate_counters = {
            'connection_failures': 0,
            'processing_errors': 0,
            'audio_frames': 0,
            'events_processed': 0
        }
        
    def set_components(self, kvs_master=None, audio_processor=None, event_bridge=None):
        """
        Set component references for metrics collection
        
        Args:
            kvs_master: KVSWebRTCMaster instance
            audio_processor: AudioProcessor instance
            event_bridge: EventBridge instance
        """
        self.kvs_master = kvs_master
        self.audio_processor = audio_processor
        self.event_bridge = event_bridge
        logger.debug("[PerformanceMonitor] Component references set")
        
    async def start_monitoring(self, interval: float = 1.0):
        """
        Start performance monitoring
        
        Args:
            interval: Monitoring interval in seconds
        """
        if self.is_monitoring:
            logger.warning("[PerformanceMonitor] Already monitoring")
            return
            
        self.monitoring_interval = interval
        self.is_monitoring = True
        
        logger.info(f"[PerformanceMonitor] Starting performance monitoring (interval: {interval}s)")
        
        # Start monitoring task
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
    async def stop_monitoring(self):
        """Stop performance monitoring"""
        if not self.is_monitoring:
            return
            
        logger.debug("[PerformanceMonitor] Stopping performance monitoring")
        
        self.is_monitoring = False
        
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
                
        logger.debug("[PerformanceMonitor] Performance monitoring stopped")
        
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        try:
            while self.is_monitoring:
                await self.collect_metrics()
                await asyncio.sleep(self.monitoring_interval)
                
        except asyncio.CancelledError:
            logger.debug("[PerformanceMonitor] Monitoring loop cancelled")
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error in monitoring loop: {e}")
            
    async def collect_metrics(self):
        """Collect all performance metrics"""
        try:
            with self.collection_lock:
                current_time = time.time()
                
                # Create new metrics instance
                metrics = PerformanceMetrics(timestamp=current_time)
                
                # Collect system metrics
                self._collect_system_metrics(metrics)
                
                # Collect WebRTC metrics
                await self._collect_webrtc_metrics(metrics)
                
                # Collect audio processing metrics
                self._collect_audio_metrics(metrics)
                
                # Collect event processing metrics
                self._collect_event_metrics(metrics)
                
                # Calculate rates
                self._calculate_rates(metrics, current_time)
                
                # Update current metrics
                self.current_metrics = metrics
                
                # Store in history
                self.metrics_history.append(metrics)
                
                # Check thresholds
                self._check_thresholds(metrics)
                
                # Notify listeners
                if self.on_metrics_update:
                    await self._safe_callback(self.on_metrics_update, metrics)
                    
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error collecting metrics: {e}")
            
    def _collect_system_metrics(self, metrics: PerformanceMetrics):
        """Collect system resource metrics"""
        try:
            # CPU usage
            metrics.cpu_usage = psutil.cpu_percent(interval=None)
            
            # Memory usage
            memory = psutil.virtual_memory()
            metrics.memory_usage = memory.percent
            metrics.memory_usage_mb = memory.used / 1024 / 1024
            
            # Network I/O (if available)
            try:
                net_io = psutil.net_io_counters()
                metrics.bytes_received = net_io.bytes_recv
                metrics.bytes_sent = net_io.bytes_sent
            except Exception:
                # Network stats may not be available in all environments
                pass
                
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error collecting system metrics: {e}")
            
    async def _collect_webrtc_metrics(self, metrics: PerformanceMetrics):
        """Collect WebRTC connection metrics"""
        try:
            if self.kvs_master:
                # Connection metrics
                metrics.active_connections = len(self.kvs_master.get_connected_clients())
                metrics.total_connections = len(self.kvs_master.peer_connections)
                
                # Get connection statistics from KVS master
                # Note: Detailed WebRTC stats would require aiortc peer connection stats
                # This is a simplified implementation
                
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error collecting WebRTC metrics: {e}")
            
    def _collect_audio_metrics(self, metrics: PerformanceMetrics):
        """Collect audio processing metrics"""
        try:
            if self.audio_processor:
                stats = self.audio_processor.get_processing_stats()
                
                metrics.audio_frames_processed = stats.get('frames_processed', 0)
                metrics.audio_bytes_processed = stats.get('bytes_processed', 0)
                metrics.audio_conversion_errors = stats.get('conversion_errors', 0)
                
                # Calculate processing latency (simplified)
                if stats.get('last_activity'):
                    processing_delay = time.time() - stats['last_activity']
                    metrics.audio_processing_latency = processing_delay * 1000  # Convert to ms
                    
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error collecting audio metrics: {e}")
            
    def _collect_event_metrics(self, metrics: PerformanceMetrics):
        """Collect event processing metrics"""
        try:
            if self.event_bridge:
                stats = self.event_bridge.get_statistics()
                
                metrics.events_received = stats.get('messages_received', 0)
                metrics.events_sent = stats.get('messages_sent', 0)
                metrics.event_processing_errors = stats.get('processing_errors', 0)
                
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error collecting event metrics: {e}")
            
    def _calculate_rates(self, metrics: PerformanceMetrics, current_time: float):
        """Calculate rate-based metrics"""
        try:
            time_delta = current_time - self.last_metrics_time
            
            if time_delta > 0:
                # Calculate rates per second
                # Note: This is a simplified rate calculation
                # In production, you might want more sophisticated rate tracking
                pass
                
            self.last_metrics_time = current_time
            
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error calculating rates: {e}")
            
    def _check_thresholds(self, metrics: PerformanceMetrics):
        """Check if metrics exceed thresholds"""
        violations = []
        
        # Check CPU usage
        if metrics.cpu_usage > self.thresholds['cpu_usage']:
            violations.append({
                'metric': 'cpu_usage',
                'value': metrics.cpu_usage,
                'threshold': self.thresholds['cpu_usage'],
                'severity': 'warning'
            })
            
        # Check memory usage
        if metrics.memory_usage > self.thresholds['memory_usage']:
            violations.append({
                'metric': 'memory_usage',
                'value': metrics.memory_usage,
                'threshold': self.thresholds['memory_usage'],
                'severity': 'warning'
            })
            
        # Check audio processing latency
        if metrics.audio_processing_latency > self.thresholds['audio_latency']:
            violations.append({
                'metric': 'audio_latency',
                'value': metrics.audio_processing_latency,
                'threshold': self.thresholds['audio_latency'],
                'severity': 'warning'
            })
            
        # Check conversion errors
        if metrics.audio_conversion_errors > self.thresholds['processing_errors']:
            violations.append({
                'metric': 'processing_errors',
                'value': metrics.audio_conversion_errors,
                'threshold': self.thresholds['processing_errors'],
                'severity': 'error'
            })
            
        if violations and self.on_threshold_exceeded:
            asyncio.create_task(self._safe_callback(self.on_threshold_exceeded, violations))
            
    async def _safe_callback(self, callback: Callable, *args):
        """Safely invoke callback"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"[PerformanceMonitor] Error in callback: {e}")
            
    def set_baseline(self):
        """Set current metrics as baseline for comparison"""
        self.baseline_metrics = PerformanceMetrics(**asdict(self.current_metrics))
        logger.debug("[PerformanceMonitor] Baseline metrics set")
        
    def compare_with_baseline(self) -> Optional[Dict]:
        """
        Compare current metrics with baseline
        
        Returns:
            Dictionary with comparison results or None if no baseline
        """
        if not self.baseline_metrics:
            return None
            
        comparison = {}
        current_dict = asdict(self.current_metrics)
        baseline_dict = asdict(self.baseline_metrics)
        
        for key, current_value in current_dict.items():
            if isinstance(current_value, (int, float)) and key in baseline_dict:
                baseline_value = baseline_dict[key]
                if baseline_value != 0:
                    difference = current_value - baseline_value
                    percent_change = (difference / baseline_value) * 100
                    
                    comparison[key] = {
                        'current': current_value,
                        'baseline': baseline_value,
                        'difference': difference,
                        'percent_change': round(percent_change, 2)
                    }
                    
        return comparison
        
    def get_metrics_summary(self) -> Dict:
        """
        Get comprehensive metrics summary
        
        Returns:
            Dictionary with metrics summary
        """
        # Calculate averages over last 30 seconds
        recent_time = time.time() - 30
        recent_metrics = [m for m in self.metrics_history if m.timestamp >= recent_time]
        
        averages = {}
        if recent_metrics:
            metrics_dicts = [asdict(m) for m in recent_metrics]
            for key in asdict(self.current_metrics).keys():
                if key != 'timestamp':
                    values = [m[key] for m in metrics_dicts if isinstance(m[key], (int, float))]
                    if values:
                        averages[key] = sum(values) / len(values)
                        
        return {
            'current': asdict(self.current_metrics),
            'baseline': asdict(self.baseline_metrics) if self.baseline_metrics else None,
            'comparison': self.compare_with_baseline(),
            'averages': averages,
            'history_size': len(self.metrics_history),
            'is_monitoring': self.is_monitoring,
            'thresholds': self.thresholds
        }
        
    def get_performance_report(self) -> Dict:
        """
        Get detailed performance report with recommendations
        
        Returns:
            Comprehensive performance report
        """
        summary = self.get_metrics_summary()
        
        return {
            **summary,
            'health_score': self.calculate_health_score(),
            'recommendations': self.get_recommendations(),
            'optimization_suggestions': self.get_optimization_suggestions()
        }
        
    def calculate_health_score(self) -> float:
        """
        Calculate overall system health score (0-100)
        
        Returns:
            Health score as percentage
        """
        score = 100.0
        
        # Deduct points for threshold violations
        if self.current_metrics.cpu_usage > self.thresholds['cpu_usage']:
            score -= 20
            
        if self.current_metrics.memory_usage > self.thresholds['memory_usage']:
            score -= 15
            
        if self.current_metrics.audio_processing_latency > self.thresholds['audio_latency']:
            score -= 25
            
        if self.current_metrics.audio_conversion_errors > self.thresholds['processing_errors']:
            score -= 30
            
        if self.current_metrics.event_processing_errors > self.thresholds['processing_errors']:
            score -= 20
            
        # Connection health
        if self.current_metrics.active_connections == 0 and self.current_metrics.total_connections > 0:
            score -= 40  # Connections exist but none are active
            
        return max(0.0, min(100.0, score))
        
    def get_recommendations(self) -> List[Dict]:
        """
        Get performance recommendations based on current metrics
        
        Returns:
            List of recommendation dictionaries
        """
        recommendations = []
        
        if self.current_metrics.cpu_usage > self.thresholds['cpu_usage']:
            recommendations.append({
                'type': 'cpu',
                'severity': 'warning',
                'message': f'High CPU usage: {self.current_metrics.cpu_usage:.1f}%',
                'action': 'Consider optimizing audio processing or reducing concurrent connections'
            })
            
        if self.current_metrics.memory_usage > self.thresholds['memory_usage']:
            recommendations.append({
                'type': 'memory',
                'severity': 'warning',
                'message': f'High memory usage: {self.current_metrics.memory_usage:.1f}%',
                'action': 'Check for memory leaks and optimize buffer management'
            })
            
        if self.current_metrics.audio_processing_latency > self.thresholds['audio_latency']:
            recommendations.append({
                'type': 'latency',
                'severity': 'error',
                'message': f'High audio processing latency: {self.current_metrics.audio_processing_latency:.1f}ms',
                'action': 'Optimize audio processing pipeline and check system load'
            })
            
        if self.current_metrics.audio_conversion_errors > 0:
            recommendations.append({
                'type': 'audio_errors',
                'severity': 'error',
                'message': f'Audio conversion errors detected: {self.current_metrics.audio_conversion_errors}',
                'action': 'Check audio format compatibility and error handling'
            })
            
        return recommendations
        
    def get_optimization_suggestions(self) -> List[Dict]:
        """
        Get optimization suggestions based on performance analysis
        
        Returns:
            List of optimization suggestion dictionaries
        """
        suggestions = []
        
        # Analyze connection patterns
        if self.current_metrics.active_connections > 10:
            suggestions.append({
                'category': 'scaling',
                'suggestion': 'Consider implementing connection pooling for high concurrent usage',
                'impact': 'medium',
                'effort': 'high'
            })
            
        # Analyze audio processing
        if self.current_metrics.audio_processing_latency > 50:
            suggestions.append({
                'category': 'audio',
                'suggestion': 'Implement audio processing optimization or use hardware acceleration',
                'impact': 'high',
                'effort': 'medium'
            })
            
        # Analyze error rates
        if self.current_metrics.audio_conversion_errors > 0:
            suggestions.append({
                'category': 'reliability',
                'suggestion': 'Implement better error handling and recovery mechanisms',
                'impact': 'high',
                'effort': 'low'
            })
            
        # Memory optimization
        if self.current_metrics.memory_usage_mb > 500:
            suggestions.append({
                'category': 'memory',
                'suggestion': 'Implement memory optimization and garbage collection tuning',
                'impact': 'medium',
                'effort': 'medium'
            })
            
        return suggestions
        
    def export_metrics(self, format: str = 'json') -> str:
        """
        Export metrics data for analysis
        
        Args:
            format: Export format ('json' or 'csv')
            
        Returns:
            Exported data as string
        """
        if format == 'json':
            export_data = {
                'summary': self.get_metrics_summary(),
                'full_history': [asdict(m) for m in self.metrics_history],
                'export_time': time.time()
            }
            return json.dumps(export_data, indent=2)
        else:
            raise ValueError(f"Unsupported export format: {format}")
            
    def set_thresholds(self, new_thresholds: Dict):
        """
        Update performance thresholds
        
        Args:
            new_thresholds: Dictionary with new threshold values
        """
        self.thresholds.update(new_thresholds)
        logger.debug(f"[PerformanceMonitor] Updated thresholds: {self.thresholds}")
        
    def record_connection_failure(self):
        """Record a connection failure for metrics"""
        self.rate_counters['connection_failures'] += 1
        
    def record_processing_error(self):
        """Record a processing error for metrics"""
        self.rate_counters['processing_errors'] += 1
        
    async def cleanup(self):
        """Clean up monitoring resources"""
        await self.stop_monitoring()
        self.metrics_history.clear()
        logger.debug("[PerformanceMonitor] Cleanup completed")