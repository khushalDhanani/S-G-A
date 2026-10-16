FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY prompts ./prompts
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 app \
    && mkdir -p /app/logs && chown -R app:app /app
USER app
CMD ["sap-agent"]
