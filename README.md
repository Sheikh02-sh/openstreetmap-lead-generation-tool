# OpenStreetMap Lead Generation Tool

A beginner-friendly Flask app that searches nearby mapped businesses using OpenStreetMap data via Nominatim (location lookup) and Overpass API (business search). The app loads settings from `.env` and tries multiple public Overpass endpoints if one is busy. No Google API key, Google Cloud project, or payment card is required.

## Included features
- Search by business category/keyword and city or neighbourhood
- Search radius: 2, 5, 10, or 20 km
- Business name, mapped address, phone, website, category, coordinates and OSM map link
- Duplicate removal
- Results shown in pages of 50 (up to 500 returned per search)
- CSV and Excel (.xlsx) export
- Responsive dashboard and clear error messages
- Render deployment configuration

## Windows PowerShell setup
Open PowerShell in this project folder and run:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

In `.env`, replace `your-email@example.com` with a contact email you control in `OSM_USER_AGENT`. Save the file. Then run:

```powershell
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Render deployment
Push the project to GitHub and create a Render Web Service:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Add an environment variable named `OSM_USER_AGENT`, with a descriptive app name and contact email, for example:
`OSMLeadFinder/1.0 (contact: you@example.com)`

No Google API key is used.

## Important data and usage limitations
- OpenStreetMap is community-maintained. It does not guarantee complete or current business listings.
- Phone numbers, websites and street addresses appear only when contributors have added them.
- Google ratings, Google reviews and Google Place IDs are not available from OSM.
- Search is centred on the location returned by Nominatim and uses the selected radius. It returns up to 500 matching mapped objects per search.
- The public Nominatim service has a strict usage policy (including a maximum of one request per second, a valid identifying User-Agent, and attribution). Public Overpass instances are shared community services and may be busy or rate-limit requests. Do not use this starter for high-volume scraping or continuous bulk collection. For production-scale use, choose a suitable hosted OSM data provider or run your own service.
- Display attribution: “© OpenStreetMap contributors” and link to https://www.openstreetmap.org/copyright.

## Data source
- Nominatim: https://nominatim.org/release-docs/latest/api/Search/
- Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- Nominatim usage policy: https://operations.osmfoundation.org/policies/nominatim/
