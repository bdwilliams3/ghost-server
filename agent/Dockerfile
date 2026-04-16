FROM golang:1.24-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY main.go .
RUN go build -o ghost-agent .

FROM alpine:3.20
WORKDIR /app
COPY --from=builder /app/ghost-agent .
# Agent is event-driven; keep alive via sleep loop
CMD ["sh", "-c", "while true; do sleep 3600; done"]
