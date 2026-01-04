FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create uploads directory (if not exists) and set permissions
RUN mkdir -p instance/uploads && chmod 777 instance/uploads

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "-k", "gevent", "--worker-connections", "1000", "--bind", "0.0.0.0:5000", "app:app"]
