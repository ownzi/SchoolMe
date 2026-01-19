FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ownzi/plovdiv-school-news-bot"
LABEL org.opencontainers.image.description="Viber bot for Plovdiv kindergarten/school news notifications"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Create data directory for state persistence
RUN mkdir -p /data

# Set timezone for correct scheduling
ENV TZ=Europe/Sofia
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Run as non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app /data
USER appuser

ENV PYTHONUNBUFFERED=1
ENV STATE_FILE=/data/seen_articles.json

CMD ["python", "-m", "src.main"]
