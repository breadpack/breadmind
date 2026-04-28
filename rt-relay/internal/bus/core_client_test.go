package bus

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestCoreClient_BackfillSince(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/api/v1/workspaces/ws-1/channels/ch-1/messages", r.URL.Path)
		assert.Equal(t, "12345", r.URL.Query().Get("since_ts_seq"))
		_ = json.NewEncoder(w).Encode(map[string]any{
			"messages": []map[string]any{
				{"id": "m1", "ts_seq": 12346, "body": "hi"},
				{"id": "m2", "ts_seq": 12347, "body": "bye"},
			},
		})
	}))
	defer srv.Close()

	c := NewCoreClient(srv.URL, "service-token")
	msgs, err := c.BackfillSince(context.Background(), "ws-1", "ch-1", 12345, 200)
	require.NoError(t, err)
	assert.Len(t, msgs, 2)
}

func TestCoreClient_VisibleChannels(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/api/v1/workspaces/ws-1/users/u-1/visible-channels", r.URL.Path)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"channel_ids": []string{"ch-1", "ch-2"},
		})
	}))
	defer srv.Close()

	c := NewCoreClient(srv.URL, "service-token")
	got, err := c.VisibleChannels(context.Background(), "ws-1", "u-1")
	require.NoError(t, err)
	assert.Equal(t, []string{"ch-1", "ch-2"}, got)
}
