FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV ELI_LEGAL_ENV=container ELI_LEGAL_NETWORK_DEFAULT=deny
# Fails at start-up if the audit key is absent: no key, no governed runtime.
CMD ["uvicorn", "--factory", "eli_legal.api.app:create_app", "--host", "0.0.0.0", "--port", "8080"]
