FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY labellab ./labellab
RUN pip install ".[anthropic]"
COPY data ./data
COPY web ./web
EXPOSE 8000
CMD ["uvicorn", "labellab.api:app", "--host", "0.0.0.0", "--port", "8000"]
