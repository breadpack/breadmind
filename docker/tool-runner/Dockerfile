FROM python:3.12-slim

LABEL maintainer="BreadMind" \
      description="BreadMind tool runner - isolated execution environment"

# Install common tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install breadmind (minimal)
RUN pip install --no-cache-dir breadmind || true

# Create non-root user
RUN useradd -m -s /bin/bash runner
USER runner
WORKDIR /home/runner

# Default command
CMD ["python", "-c", "print('BreadMind tool-runner ready')"]
