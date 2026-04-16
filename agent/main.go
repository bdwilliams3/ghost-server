package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"google.golang.org/genai"
)

var mcpURL = func() string {
	if u := os.Getenv("MCP_SERVER_URL"); u != "" {
		return u
	}
	return "http://mcp-server.workload.svc.cluster.local:8000/mcp"
}()

type mcpReq struct {
	JSONRPC string         `json:"jsonrpc"`
	ID      int            `json:"id"`
	Method  string         `json:"method"`
	Params  map[string]any `json:"params,omitempty"`
}

type mcpResp struct {
	Result json.RawMessage `json:"result"`
	Error  *struct {
		Message string `json:"message"`
	} `json:"error"`
}

var sessionID string
var reqID int

func nextID() int {
	reqID++
	return reqID
}

func post(body mcpReq) (mcpResp, error) {
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", mcpURL, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	if sessionID != "" {
		req.Header.Set("Mcp-Session-Id", sessionID)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return mcpResp{}, err
	}
	defer resp.Body.Close()
	if sid := resp.Header.Get("Mcp-Session-Id"); sid != "" {
		sessionID = sid
	}
	data, _ := io.ReadAll(resp.Body)
	raw := string(data)
	if strings.Contains(raw, "data:") {
		for _, line := range strings.Split(raw, "\n") {
			line = strings.TrimSpace(line)
			if strings.HasPrefix(line, "data:") {
				raw = strings.TrimPrefix(line, "data:")
				break
			}
		}
	}
	var r mcpResp
	json.Unmarshal([]byte(raw), &r)
	return r, nil
}

func initSession() error {
	r, err := post(mcpReq{
		JSONRPC: "2.0",
		ID:      nextID(),
		Method:  "initialize",
		Params: map[string]any{
			"protocolVersion": "2024-11-05",
			"clientInfo":      map[string]any{"name": "ghost-agent", "version": "1.0"},
			"capabilities":    map[string]any{},
		},
	})
	if err != nil {
		return err
	}
	if r.Error != nil {
		return fmt.Errorf(r.Error.Message)
	}
	return nil
}

func listTools() ([]*genai.FunctionDeclaration, error) {
	r, err := post(mcpReq{JSONRPC: "2.0", ID: nextID(), Method: "tools/list"})
	if err != nil {
		return nil, err
	}
	var result struct {
		Tools []struct {
			Name        string          `json:"name"`
			Description string          `json:"description"`
			InputSchema json.RawMessage `json:"inputSchema"`
		} `json:"tools"`
	}
	json.Unmarshal(r.Result, &result)

	var decls []*genai.FunctionDeclaration
	for _, t := range result.Tools {
		var schema genai.Schema
		json.Unmarshal(t.InputSchema, &schema)
		decls = append(decls, &genai.FunctionDeclaration{
			Name:        t.Name,
			Description: t.Description,
			Parameters:  &schema,
		})
	}
	return decls, nil
}

func callTool(name string, args map[string]any) (string, error) {
	r, err := post(mcpReq{
		JSONRPC: "2.0",
		ID:      nextID(),
		Method:  "tools/call",
		Params:  map[string]any{"name": name, "arguments": args},
	})
	if err != nil {
		return "", err
	}
	var result struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
	}
	json.Unmarshal(r.Result, &result)
	if len(result.Content) > 0 {
		return result.Content[0].Text, nil
	}
	return "", nil
}

func printResp(resp *genai.GenerateContentResponse) {
	if resp == nil || len(resp.Candidates) == 0 || resp.Candidates[0].Content == nil {
		return
	}
	for _, part := range resp.Candidates[0].Content.Parts {
		if part.Text != "" {
			fmt.Printf("\nAgent: %s\n\n", part.Text)
		}
	}
}

func main() {
	ctx := context.Background()

	if err := initSession(); err != nil {
		fmt.Println("MCP init error:", err)
		os.Exit(1)
	}

	tools, err := listTools()
	if err != nil {
		fmt.Println("Tool list error:", err)
		os.Exit(1)
	}

	client, err := genai.NewClient(ctx, &genai.ClientConfig{
		APIKey:  os.Getenv("GEMINI_API_KEY"),
		Backend: genai.BackendGeminiAPI,
	})
	if err != nil {
		fmt.Println("Gemini client error:", err)
		os.Exit(1)
	}

	chat, err := client.Chats.Create(ctx, "gemini-2.5-flash", &genai.GenerateContentConfig{
		SystemInstruction: genai.NewContentFromText("You are a Kubernetes cluster assistant for a KIND cluster. Use tools to answer questions about cluster state, logs, and events. Be concise.", genai.RoleUser),
		Tools: []*genai.Tool{
			{FunctionDeclarations: tools},
		},
	}, nil)
	if err != nil {
		fmt.Println("Chat error:", err)
		os.Exit(1)
	}

	scanner := bufio.NewScanner(os.Stdin)
	fmt.Println("Ghost Cluster Agent ready. Type 'exit' to quit.\n")

	for {
		fmt.Print("You: ")
		if !scanner.Scan() {
			break
		}
		input := strings.TrimSpace(scanner.Text())
		if input == "exit" || input == "quit" {
			break
		}
		if input == "" {
			continue
		}

		resp, err := chat.SendMessage(ctx, genai.Part{Text: input})
		if err != nil {
			fmt.Println("Error:", err)
			continue
		}

		for resp != nil && len(resp.Candidates) > 0 {
			var toolParts []genai.Part
			for _, part := range resp.Candidates[0].Content.Parts {
				if part.FunctionCall != nil {
					fc := part.FunctionCall
					result, err := callTool(fc.Name, fc.Args)
					if err != nil {
						result = "error: " + err.Error()
					}
					toolParts = append(toolParts, genai.Part{
						FunctionResponse: &genai.FunctionResponse{
							Name:     fc.Name,
							Response: map[string]any{"result": result},
						},
					})
				}
			}
			if len(toolParts) == 0 {
				break
			}
			resp, err = chat.SendMessage(ctx, toolParts...)
			if err != nil {
				fmt.Println("Error:", err)
				resp = nil
			}
		}

		printResp(resp)
	}
}
