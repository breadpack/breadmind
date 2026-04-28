package bus

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

type CoreClient struct {
	baseURL string
	token   string
	hc      *http.Client
}

func NewCoreClient(baseURL, token string) *CoreClient {
	return &CoreClient{baseURL: baseURL, token: token, hc: http.DefaultClient}
}

func (c *CoreClient) BackfillSince(ctx context.Context, workspaceID, channelID string, sinceTsSeq int64, limit int) ([][]byte, error) {
	u := fmt.Sprintf("%s/api/v1/workspaces/%s/channels/%s/messages?since_ts_seq=%d&limit=%d",
		c.baseURL, url.PathEscape(workspaceID), url.PathEscape(channelID), sinceTsSeq, limit)
	req, err := http.NewRequestWithContext(ctx, "GET", u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("backfill: status %d", resp.StatusCode)
	}
	var body struct {
		Messages []json.RawMessage `json:"messages"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	out := make([][]byte, len(body.Messages))
	for i, m := range body.Messages {
		out[i] = []byte(m)
	}
	return out, nil
}

func (c *CoreClient) VisibleChannels(ctx context.Context, workspaceID, userID string) ([]string, error) {
	u := fmt.Sprintf("%s/api/v1/workspaces/%s/users/%s/visible-channels",
		c.baseURL, url.PathEscape(workspaceID), url.PathEscape(userID))
	req, err := http.NewRequestWithContext(ctx, "GET", u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("visible-channels: status %d", resp.StatusCode)
	}
	var body struct {
		ChannelIDs []string `json:"channel_ids"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	return body.ChannelIDs, nil
}

// WithTimeoutSec returns a copy of the client with a custom HTTP timeout.
func (c *CoreClient) WithTimeoutSec(sec int) *CoreClient {
	return &CoreClient{
		baseURL: c.baseURL,
		token:   c.token,
		hc:      &http.Client{Timeout: time.Duration(sec) * time.Second},
	}
}
