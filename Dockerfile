# Sandbox for --run-tests: migrated projects' tests execute untrusted code, so run them in a container.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends default-jdk-headless maven git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
WORKDIR /work
ENTRYPOINT ["modernizer"]
