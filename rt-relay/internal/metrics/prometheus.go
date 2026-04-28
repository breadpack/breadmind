package metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	ActiveConnections = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "breadmind_relay_active_connections",
		Help: "Active WebSocket connections",
	})
	FanOutLatency = prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:    "breadmind_relay_fan_out_latency_seconds",
		Help:    "Time from Redis publish to client send",
		Buckets: []float64{0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5},
	})
	DroppedEvents = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "breadmind_relay_dropped_events_total",
		Help: "Events dropped due to slow consumer or send failure",
	})
)

func init() {
	prometheus.MustRegister(ActiveConnections, FanOutLatency, DroppedEvents)
}

func Handler() http.Handler {
	return promhttp.Handler()
}
