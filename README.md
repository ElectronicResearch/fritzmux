# FritzMux

**RTSP → HTTP IPTV Relay für Fritzbox 6591** mit 4 Tunern und EPG-Unterstützung.

Fritzbox generiert M3U-Playlisten mit `rtsp://` URLs – moderne IPTV Player wie **TiviMate** können damit nichts anfangen. FritzMux wandelt die Playlist um, relayt RTSP-Streams on-demand via ffmpeg als HTTP MPEG-TS und stellt EPG-Daten als XMLTV bereit.

## Features

- **M3U Konverter** – Importiert Fritzbox-M3U (Upload oder URL), schreibt RTSP-URLs auf `http://.../stream/{id}` um
- **On-Demand Streaming** – ffmpeg relayt RTSP → HTTP (MPEG-TS, stream copy, kein Transcoding)
- **EPG Proxing** – Mehrere EPG-Quellen (Fritzbox intern + extern) → XMLTV
- **Logo Proxy** – Externe Logos werden gecached und lokal ausgeliefert (TiviMate muss nicht raus ins Internet)
- **Web UI** – Kanalverwaltung, Import, Status-Übersicht
- **Docker** – Port 8181, einfaches Setup via docker-compose

## Quickstart

```bash
docker compose up -d
```

`http://<docker-host-ip>:8181` im Browser öffnen → M3U importieren → M3U/EPG-URLs in TiviMate eintragen.

> **Hinweis:** `network_mode: host` wird verwendet, damit der Container auf Geräte im Heimnetz (Fritzbox) zugreifen kann.
> Die Fritzbox-IP im Browser eingeben – Standard ist meist `192.168.178.1` oder `192.168.0.1`.

## Architektur

```
Fritzbox (RTSP + M3U + EPG)
       │
       ▼
   FritzMux (Port 8181)
       │
       ├── M3U Rewrite   → http://app:8181/api/channels.m3u
       ├── EPG Proxy     → http://app:8181/api/epg.xml
       ├── Logo Proxy    → http://app:8181/api/logo/{id}
       └── Stream Relay  → http://app:8181/stream/{id}
                                │
                                ▼
                         IPTV Player (TiviMate, …)
```

## API Endpoints

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/` | GET | Web UI |
| `/api/status` | GET | Server-Status (aktive Streams, Kanäle) |
| `/api/channels` | GET | Kanalliste als JSON |
| `/api/channels/{id}` | GET | Kanal-Detail |
| `/api/channels/{id}` | PUT | Kanal bearbeiten |
| `/api/channels/{id}` | DELETE | Kanal löschen |
| `/api/channels/clear` | POST | Alle Kanäle löschen |
| `/api/channels.m3u` | GET | **Generierte M3U** – in TiviMate als Playlist einfügen |
| `/api/import/url` | POST | M3U von URL importieren |
| `/api/import/upload` | POST | M3U-Datei hochladen |
| `/api/epg.xml` | GET | **XMLTV EPG** – in TiviMate als EPG-Quelle einfügen |
| `/api/epg/refresh` | GET | EPG neu laden (alle Quellen) |
| `/api/epg/source` | POST | EPG-Quelle hinzufügen |
| `/api/logo/{id}` | GET | Gecachtes Kanallogo |
| `/stream/{id}` | GET | **Live-Stream** (ffmpeg relayt RTSP → MPEG-TS) |

## Konfiguration

Alle relevanten Einstellungen in `app/config.py`:

| Variable | Standard | Beschreibung |
|---|---|---|
| `MAX_STREAMS` | 4 | Maximale parallele Streams (Fritzbox hat 4 Tuner) |
| `EPG_FETCH_INTERVAL` | 3600 | EPG-Aktualisierungsintervall in Sekunden |

## Development

```bash
# Mit Hot-Reload (Code-Änderungen ohne Neubauen)
docker run -d --name fritzmux -p 8181:8181 \
  -v "$(pwd)/app:/app/app" \
  -v "$(pwd)/data:/app/data" \
  fritzmux:latest

# Oder direkt ohne Docker
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8181
```

## Docker

```yaml
services:
  fritzmux:
    build: .
    container_name: fritzmux
    ports:
      - "8181:8181"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

## TiviMate Einrichtung

1. **Playlist:** `http://<fritzmux-ip>:8181/api/channels.m3u` als neue Playlist hinzufügen
2. **EPG:** `http://<fritzmux-ip>:8181/api/epg.xml` als EPG-Quelle hinterlegen
3. Fertig – Kanäle werden mit Logos und EPG-Daten angezeigt
