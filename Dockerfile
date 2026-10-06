FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY config ./config
COPY scripts ./scripts
ENV ELI_LEGAL_ENV=container ELI_LEGAL_NETWORK_DEFAULT=deny
CMD ["uvicorn", "eli_legal.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
