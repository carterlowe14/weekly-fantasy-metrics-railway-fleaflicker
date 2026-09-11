FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY main.py ./
COPY ffmwr ./ffmwr
COPY resources ./resources

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py", "--use-default"]
