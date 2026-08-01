FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIANXIN_PHYSICAL_HOST=0.0.0.0 \
    LIANXIN_PHYSICAL_PORT=8765

WORKDIR /app

COPY requirements-simulator.txt ./
RUN pip install --no-cache-dir -r requirements-simulator.txt

# The container only needs the physical runtime and its Canvas static files.
COPY brain ./brain
COPY gui/physical_sim ./gui/physical_sim

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)"

CMD ["python", "-m", "brain.physical.service"]
