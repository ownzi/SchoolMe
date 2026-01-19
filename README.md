# Plovdiv School News Bot 🏫

A Viber bot that monitors the Plovdiv municipality website for kindergarten and school-related news, and notifies parents in a group chat.

## Features

- Scrapes `dz-priem.plovdiv.bg/news` for new articles
- Tracks seen articles to avoid duplicate notifications
- Sends formatted messages via Viber Bot API
- Designed to run once daily at 15:00 (configurable)
- Docker-based for easy deployment on unRAID or any server

## Quick Start

### 1. Create a Viber Bot

1. Go to [Viber Admin Panel](https://partners.viber.com/)
2. Create a new bot account
3. Copy the authentication token

### 2. Get the Chat ID

For **group chats**, the bot needs to be added to the group first. When someone sends a message while the bot is present, the group ID will appear in webhook events.

For **1:1 messages**, use the Viber user ID of the recipient.

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Run

**Test run (dry run, no messages sent):**
```bash
docker compose run --rm -e DRY_RUN=true plovdiv-school-news-bot
```

**Production run:**
```bash
docker compose run --rm plovdiv-school-news-bot
```

## unRAID Setup

### Option 1: User Scripts Plugin

1. Install "User Scripts" from Community Applications
2. Create a new script with:

```bash
#!/bin/bash
cd /mnt/user/appdata/plovdiv-school-news-bot
docker compose run --rm plovdiv-school-news-bot
```

3. Set schedule to "Custom" with cron: `0 15 * * *` (15:00 daily)

### Option 2: Cron Job

Add to `/boot/config/go` or use the cron manager:

```bash
0 15 * * * docker run --rm \
  -e VIBER_BOT_TOKEN=xxx \
  -e VIBER_CHAT_ID=xxx \
  -v /mnt/user/appdata/plovdiv-school-news-bot/data:/data \
  ghcr.io/ownzi/plovdiv-school-news-bot:latest
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `VIBER_BOT_TOKEN` | Viber Bot API token (required) | - |
| `VIBER_CHAT_ID` | Viber chat/user ID to notify (required) | - |
| `NEWS_URL` | URL to scrape for news | `https://dz-priem.plovdiv.bg/news` |
| `STATE_FILE` | Path to persistence file | `/data/seen_articles.json` |
| `DRY_RUN` | If `true`, don't send messages | `false` |
| `TZ` | Timezone for logging | `Europe/Sofia` |

## Data Persistence

The bot stores seen article IDs in `/data/seen_articles.json`. Mount this as a volume to persist across container restarts.

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python -m src.main

# Run tests
pytest tests/
```

## Viber Bot API Notes

- Viber bots require a webhook for receiving messages, but this bot only **sends** notifications
- For group chats, the bot must be added as a member
- Rate limits: 20 requests/second for messages
- Messages support text, URLs, and rich media

### Getting Group Chat ID

1. Set up a webhook endpoint (even temporarily)
2. Add the bot to your group
3. Send any message in the group
4. The webhook will receive an event with `chat_id` in the payload

Alternatively, use this minimal webhook to capture the ID:

```python
from flask import Flask, request
app = Flask(__name__)

@app.route('/viber', methods=['POST'])
def viber_webhook():
    data = request.json
    print(f"Event: {data}")
    if 'chat' in data:
        print(f"Chat ID: {data['chat']['id']}")
    return 'ok'

if __name__ == '__main__':
    app.run(port=8080)
```

## License

MIT
