# FritzMux

**RTSP → HTTP IPTV Relay für AVM Fritzbox** (DVB-C) mit bis zu 4 parallelen Streams, EPG-Unterstützung und Logo-Proxy.

Fritzbox generiert M3U-Playlisten mit `rtsp://` URLs – moderne IPTV Player wie **TiviMate** oder **VLC** können damit nichts anfangen. FritzMux importiert die Playlist, wandelt RTSP-URLs auf HTTP-Streams um, relayt diese on-demand via ffmpeg als MPEG-TS und stellt EPG-Daten als XMLTV bereit.

## Features

- **M3U Import** – per Datei-Upload, URL oder Fritzbox-Scan; mehrere Playlisten zusammenführbar (Duplikaterkennung)
- **On-Demand Streaming** – ffmpeg relayt RTSP → HTTP (stream copy, kein Transcoding), max. 4 parallele Streams
- **Fritzbox-Scanner** – durchsucht Fritzbox nach M3U-Pfaden (`/dvb/m3u/`, TR-064, Legacy)
- **EPG Proxy** – mehrere XMLTV-Quellen (Fritzbox intern + extern, auch `.xml.gz`) → gemergte XMLTV
- **Logo Proxy** – externe Logos werden gecached und lokal ausgeliefert; AVM-Logos per Knopfdruck abrufbar
- **Web UI** – Kanalverwaltung (editieren, löschen, gruppieren, filtern), EPG-Konfiguration, Logo-Upload
- **Docker** – einfaches Setup via docker-compose

## Quickstart

```bash
git clone https://github.com/ElectronicResearch/fritzmux.git
cd fritzmux
docker compose up -d
```

`http://<docker-host-ip>:8181` im Browser → M3U importieren → Playlist/EPG-URLs in TiviMate eintragen.

> **Hinweis:** `network_mode: host` wird verwendet, damit der Container auf Geräte im Heimnetz (Fritzbox) zugreifen kann.

## TiviMate Einrichtung

1. **Playlist:** `http://<fritzmux-ip>:8181/api/channels.m3u` als neue Playlist
2. **EPG:** `http://<fritzmux-ip>:8181/api/epg.xml` als EPG-Quelle

## Web UI

### M3U Import

| Methode | Beschreibung |
|---|---|
| **Fritzbox scannen** | Durchsucht Fritzbox nach M3U-Pfaden (`/dvb/m3u/tvhd.m3u`, `/dvb/m3u/tvsd.m3u`, TR-064, Legacy) |
| **Von URL importieren** | M3U von beliebiger URL (z.B. `http://192.168.2.1/dvb/m3u/tvhd.m3u`) |
| **Datei-Upload** | M3U-Datei von Festplatte hochladen (Download aus Fritzbox-Webinterface) |

**Checkbox "Vorhandene Kanäle ersetzen"**: Ohne Haken werden neue Kanäle angehängt (Duplikate erkannt), mit Haken werden alle bisherigen gelöscht.

### EPG Quellen

1. Name + URL eingeben → **Hinzufügen** (unterstützt `.xml` und `.xml.gz`)
2. **EPG jetzt aktualisieren** – manueller Refresh
3. Automatischer Background-Refresh alle 60 Minuten
4. Quellen werden in `data/epg_sources.json` gespeichert und bleiben nach Neustart erhalten

### Logos

- **AVM Logos laden** – Holt passende Kanallogos von `https://download.avm.de/tv/logos/` (matched anhand Kanalname)
- **Einzel-Upload** – Im Edit-Modal pro Kanal: Logo-Datei hochladen
- **Logo-URL** – Externes Logo per URL setzen (wird gecached)

### Kanalverwaltung

- **Gruppenansicht** – Kanäle werden nach Gruppe sortiert
- **Filter/Suche** – nach Name oder Gruppe filtern
- **Multi-Select** – mehrere Kanäle auswählen, löschen oder "Nur Auswahl behalten"
- **Edit-Modal** – Kanal bearbeiten: Titel, tvg-id, tvg-name, Gruppe, RTSP-URL, Logo, EPG-Zuordnung

## Architektur

```
Fritzbox (RTSP + DVB-C Tuner)
       │
       ▼
   FritzMux (Port 8181, host network)
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
| `/api/status` | GET | Server-Status |
| `/api/channels` | GET | Kanalliste als JSON |
| `/api/channels/{id}` | GET/PUT/DELETE | Kanal Detail/Bearbeiten/Löschen |
| `/api/channels/clear` | POST | Alle Kanäle löschen |
| `/api/channels.m3u` | GET | **Generierte M3U** für TiviMate |
| `/api/import/url` | POST | M3U von URL importieren |
| `/api/import/upload` | POST | M3U-Datei hochladen |
| `/api/scan/fritzbox` | POST | Fritzbox nach M3U durchsuchen |
| `/api/epg.xml` | GET | **XMLTV EPG** für TiviMate |
| `/api/epg/refresh` | GET | EPG manuell neu laden |
| `/api/epg/source` | POST | EPG-Quelle hinzufügen |
| `/api/epg/sources` | GET | EPG-Quellen auflisten |
| `/api/epg/channels` | GET | EPG-Kanäle (aus XMLTV) |
| `/api/logos/avm` | POST | AVM-Logos abrufen |
| `/api/logo/{id}` | GET | Gecachtes Kanallogo |
| `/api/logo/{id}/upload` | POST | Logo hochladen |
| `/stream/{id}` | GET | **Live-Stream** (ffmpeg relayt RTSP → MPEG-TS) |

## Konfiguration

`app/config.py`:

| Variable | Standard | Beschreibung |
|---|---|---|
| `MAX_STREAMS` | 4 | Maximale parallele Streams |
| `STREAM_TIMEOUT` | 15 | Sekunden ohne Client → Stream wird beendet |
| `EPG_FETCH_INTERVAL` | 3600 | Background EPG-Refresh in Sekunden |

## Docker

```yaml
services:
  fritzmux:
    build: .
    container_name: fritzmux
    network_mode: host
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

Daten (Kanäle, EPG-Cache, Logos) liegen im Volume `./data`.

## Development

```bash
# Mit Hot-Reload
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8181
```
