# Base image
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

# CPU-only PyTorch keeps the image small (embeddings + reranker run on CPU).
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt /app/
RUN grep -v "^torch==" requirements.txt > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# Application code and knowledge base
COPY customer_support_chat /app/customer_support_chat
COPY vectorizer /app/vectorizer
COPY knowledge_base /app/knowledge_base
COPY scripts /app/scripts
COPY streamlit_app.py /app/
COPY .streamlit /app/.streamlit

# Run as an unprivileged user
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000 8501

# Default: the API. docker-compose overrides this for the UI and ingestion.
CMD ["uvicorn", "customer_support_chat.app.api:app", "--host", "0.0.0.0", "--port", "8000"]
