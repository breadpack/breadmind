.PHONY: build test lint run docker

build:
	go build -o bin/relay ./cmd/relay

test:
	go test ./... -race -count=1

lint:
	golangci-lint run

run:
	go run ./cmd/relay

docker:
	docker build -t breadmind/rt-relay:dev -f Dockerfile .
