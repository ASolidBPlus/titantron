# Titantron

Pro wrestling video organizer/player powered by Jellyfin + Cagematch.net.

Connects to your Jellyfin server, matches wrestling video files to events/matches from Cagematch via web scraping, and lets you browse, chapter, and play them.

## Docker (recommended)

Create a `docker-compose.yml`:

```yaml
services:
  titantron:
    image: ghcr.io/asolidbplus/titantron:latest
    ports:
      - "8765:8765"
    volumes:
      - titantron-config:/config
      - /path/to/wrestling/library:/media:ro
    environment:
      - TITANTRON_LOG_LEVEL=info
      # - TITANTRON_ADMIN_PASSWORD=your-password-here
    restart: unless-stopped

volumes:
  titantron-config:
```

Replace `/path/to/wrestling/library` with the path to your Jellyfin wrestling library on the host.

Then run:

```bash
docker compose up -d
```

The app runs on port **8765**. Open `http://your-server:8765` and follow the setup wizard.

The SQLite database is stored in a Docker volume at `/config/titantron.db` and persists across container restarts.

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the API server:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765 --reload
```

API docs at http://localhost:8765/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at http://localhost:5173 (proxies `/api` requests to the backend).

### Both at once

Run these in two terminals:

```bash
# Terminal 1
cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8765 --reload

# Terminal 2
cd frontend && npm run dev
```

Then go to http://localhost:5173 — you'll be redirected to the setup wizard.

## Setup Wizard

1. Enter your Jellyfin server URL, username, and password
2. Select a library and assign it a Cagematch promotion ID
   - Find the ID in the Cagematch URL: `cagematch.net/?id=8&nr=` **`ID`**
   - Common IDs: WWE = 1, AEW = 2287, NJPW = 7, ROH = 9, CMLL = 5, CHIKARA = 64
3. Click Sync to pull video items and extract dates

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, SQLite, BeautifulSoup, aiohttp
- **Frontend:** SvelteKit, TypeScript, Tailwind CSS
- **Video source:** Jellyfin (HLS streaming)
- **Wrestling data:** Cagematch.net (web scraping)
