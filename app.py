import io
import os
import re
import time
import csv
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file
from openpyxl import Workbook


# =========================================================
# 1. FLASK CONFIGURATION
# =========================================================

load_dotenv()

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Server order: aaj ke test mein maps.mail.ru sabse tez tha.
# Servers parallel (stagger ke saath) try hote hain, to order zyada ahem nahi.
OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

USER_AGENT = os.getenv(
    "OSM_USER_AGENT",
    "OSMLeadFinder/1.0 (contact: your-email@example.com)"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

OVERPASS_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}

_last_geocode_at = 0.0
_geocode_cache = {}
_geocode_lock = threading.Lock()

# Search results cache (same keyword + location + radius)
_search_cache = {}
CACHE_TTL = 3600  # 1 ghanta


# =========================================================
# 2. BUSINESS CATEGORY ALIASES
# =========================================================

ALIASES = {
    "dentist": [("amenity", "dentist")],
    "dentists": [("amenity", "dentist")],
    "dental": [("amenity", "dentist")],

    "doctor": [
        ("amenity", "doctors"),
        ("healthcare", "doctor"),
        ("healthcare", "clinic"),
    ],
    "doctors": [
        ("amenity", "doctors"),
        ("healthcare", "doctor"),
        ("healthcare", "clinic"),
    ],
    "clinic": [
        ("amenity", "clinic"),
        ("healthcare", "clinic"),
    ],

    "restaurant": [("amenity", "restaurant")],
    "restaurants": [("amenity", "restaurant")],

    "cafe": [("amenity", "cafe")],
    "cafes": [("amenity", "cafe")],
    "coffee": [("amenity", "cafe")],

    "pharmacy": [("amenity", "pharmacy")],
    "pharmacies": [("amenity", "pharmacy")],

    "supermarket": [("shop", "supermarket")],
    "supermarkets": [("shop", "supermarket")],

    "grocery": [
        ("shop", "supermarket"),
        ("shop", "convenience"),
    ],

    "hotel": [("tourism", "hotel")],
    "hotels": [("tourism", "hotel")],

    "school": [("amenity", "school")],
    "schools": [("amenity", "school")],

    "bank": [("amenity", "bank")],
    "banks": [("amenity", "bank")],

    "salon": [
        ("shop", "beauty"),
        ("shop", "hairdresser"),
    ],
    "salons": [
        ("shop", "beauty"),
        ("shop", "hairdresser"),
    ],

    "lawyer": [("office", "lawyer")],
    "lawyers": [("office", "lawyer")],

    "gym": [("leisure", "fitness_centre")],
    "gyms": [("leisure", "fitness_centre")],

    "mechanic": [("shop", "car_repair")],
    "car repair": [("shop", "car_repair")],

    "real estate": [("office", "estate_agent")],
    "estate agent": [("office", "estate_agent")],

    "clothing": [("shop", "clothes")],
    "clothes": [("shop", "clothes")],

    "electronics": [("shop", "electronics")],

    "bakery": [("shop", "bakery")],
    "bakeries": [("shop", "bakery")],

    "pet shop": [("shop", "pet")],
    "florist": [("shop", "florist")],

    "gas station": [("amenity", "fuel")],
    "fuel": [("amenity", "fuel")],
}


# =========================================================
# 3. GEOCODING FUNCTION
# =========================================================

def geocode_location(location):
    """Convert a city or area into latitude and longitude."""

    global _last_geocode_at

    cache_key = location.strip().lower()

    if not cache_key:
        raise ValueError("Please enter a valid location.")

    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    with _geocode_lock:

        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]

        wait = 1.05 - (time.time() - _last_geocode_at)

        if wait > 0:
            time.sleep(wait)

        try:
            response = requests.get(
                NOMINATIM_URL,
                params={
                    "q": location,
                    "format": "jsonv2",
                    "limit": 1,
                },
                headers=HEADERS,
                timeout=(8, 18),
            )

            _last_geocode_at = time.time()

            response.raise_for_status()

            data = response.json()

            if not data:
                raise ValueError(
                    "Location not found. Enter a valid city or area."
                )

            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])

            result = (lat, lon)

            _geocode_cache[cache_key] = result

            return result

        except requests.exceptions.Timeout:
            app.logger.error("Nominatim API timeout.")
            raise Exception(
                "Location service timeout. Please try again."
            )

        except requests.exceptions.RequestException as e:
            app.logger.error(f"Nominatim API error: {e}")
            raise Exception(
                "Unable to connect to OpenStreetMap location service."
            )


# =========================================================
# 4. BUILD OVERPASS QUERY
# =========================================================

def bounding_box(lat, lon, radius):
    """Radius (meters) ko ek chhote box mein badalta hai (Overpass ke liye tez)."""

    dlat = radius / 111320.0
    dlon = radius / (111320.0 * max(math.cos(math.radians(lat)), 0.01))

    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def distance_meters(lat1, lon1, lat2, lon2):
    """Do points ke beech distance (haversine)."""

    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )

    return 2 * r * math.asin(math.sqrt(a))


def build_overpass_query(keyword, lat, lon, radius):

    normalized = keyword.strip().lower()

    filters = ALIASES.get(normalized)

    south, west, north, east = bounding_box(lat, lon, radius)

    bbox = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"

    query_parts = []

    if filters:

        for key, value in filters:

            safe_value = value.replace('"', '\\"')

            query_parts.append(
                f'nwr["{key}"="{safe_value}"]{bbox};'
            )

    else:

        # Generic keyword search across business names.

        safe_keyword = re.escape(keyword.strip())

        safe_keyword = safe_keyword.replace("/", r"\/")

        query_parts.append(
            f'nwr["name"~"{safe_keyword}",i]{bbox};'
        )

    query = (
        "[out:json][timeout:40];\n"
        "(\n"
        + "\n".join(query_parts)
        + "\n);\n"
        "out center tags qt;"
    )

    return query


# =========================================================
# 5. OVERPASS API WITH MULTIPLE SERVER FALLBACK
# =========================================================


STAGGER_SECONDS = 2  # har agla server itne seconds baad start hota hai


class _Cancelled(Exception):
    pass


def _query_server(api_url, query, delay, stop_event):
    """Ek Overpass server ko query bhejta hai (delay ke baad)."""

    if delay and stop_event.wait(delay):
        raise _Cancelled()

    if stop_event.is_set():
        raise _Cancelled()

    app.logger.info(f"Trying Overpass server: {api_url}")

    started = time.time()

    try:
        response = requests.post(
            api_url,
            data={"data": query},
            headers=OVERPASS_HEADERS,
            timeout=(5, 45),
        )

        response.raise_for_status()

        data = response.json()

    except requests.exceptions.Timeout as e:
        raise Exception(f"Timeout: {e}")

    except requests.exceptions.HTTPError as e:
        raise Exception(f"HTTP error: {e}")

    except requests.exceptions.RequestException as e:
        raise Exception(f"Connection error: {e}")

    except ValueError as e:
        raise Exception(f"Invalid response: {e}")

    if not isinstance(data, dict):
        raise Exception("Invalid response format from Overpass.")

    elements = data.get("elements")

    if not isinstance(elements, list):
        raise Exception("Overpass response has no valid elements list.")

    app.logger.info(
        f"Overpass server succeeded: {api_url} in "
        f"{time.time() - started:.1f}s. "
        f"Elements received: {len(elements)}"
    )

    return elements


def fetch_overpass_data(query):
    """Servers ko thori thori der baad start karta hai (parallel),
    aur jo sabse pehle kamyab jawab de wahi use karta hai."""

    stop_event = threading.Event()

    executor = ThreadPoolExecutor(max_workers=len(OVERPASS_URLS))

    futures = {
        executor.submit(
            _query_server, url, query, index * STAGGER_SECONDS, stop_event
        ): url
        for index, url in enumerate(OVERPASS_URLS)
    }

    errors = []

    try:
        for future in as_completed(futures):

            api_url = futures[future]

            try:
                elements = future.result()
                stop_event.set()
                return elements

            except _Cancelled:
                continue

            except Exception as e:
                errors.append(f"{api_url}: {e}")
                app.logger.warning(
                    f"Overpass server failed: {api_url} - {e}"
                )

        raise Exception(
            "All Overpass servers failed. Details: " + " | ".join(errors)
        )

    finally:
        stop_event.set()
        executor.shutdown(wait=False, cancel_futures=True)


def fetch_overpass_cached(keyword, lat, lon, radius):
    """Same search dobara aaye to Overpass ko dobara call nahi karta."""

    key = (keyword.strip().lower(), round(lat, 3), round(lon, 3), radius)

    hit = _search_cache.get(key)

    if hit and time.time() - hit[0] < CACHE_TTL:
        app.logger.info("Cache hit: returning saved results.")
        return hit[1]

    query = build_overpass_query(keyword, lat, lon, radius)

    elements = fetch_overpass_data(query)

    # Box ke corners circle se bahar hote hain, unhe hata do
    filtered = []

    for element in elements:

        e_lat = element.get("lat")
        e_lon = element.get("lon")

        if e_lat is None or e_lon is None:
            center = element.get("center") or {}
            e_lat = center.get("lat")
            e_lon = center.get("lon")

        if e_lat is None or e_lon is None:
            continue

        if distance_meters(lat, lon, e_lat, e_lon) <= radius:
            filtered.append(element)

    if filtered:
        _search_cache[key] = (time.time(), filtered)

    return filtered


# =========================================================
# 6. EXTRACT BUSINESS INFORMATION
# =========================================================

def extract_address(tags):

    address_parts = []

    street = tags.get("addr:street", "")
    house = tags.get("addr:housenumber", "")
    city = tags.get("addr:city", "")
    suburb = tags.get("addr:suburb", "")
    postcode = tags.get("addr:postcode", "")

    if house and street:
        address_parts.append(f"{house} {street}")

    elif street:
        address_parts.append(street)

    if suburb:
        address_parts.append(suburb)

    if city:
        address_parts.append(city)

    if postcode:
        address_parts.append(postcode)

    return ", ".join(address_parts) if address_parts else "Not listed"


def extract_business(element):

    tags = element.get("tags", {})

    name = (
        tags.get("name")
        or tags.get("brand")
        or tags.get("operator")
    )

    if not name:
        return None

    address = extract_address(tags)

    phone = (
        tags.get("contact:phone")
        or tags.get("phone")
        or tags.get("mobile")
        or tags.get("contact:mobile")
        or ""
    )

    website = (
        tags.get("contact:website")
        or tags.get("website")
        or tags.get("url")
        or ""
    )

    category = (
        tags.get("amenity")
        or tags.get("shop")
        or tags.get("office")
        or tags.get("healthcare")
        or tags.get("tourism")
        or tags.get("leisure")
        or tags.get("craft")
        or "Business"
    )

    element_type = element.get("type")
    element_id = element.get("id")

    map_url = (
        f"https://www.openstreetmap.org/"
        f"{element_type}/{element_id}"
    )

    return {
        "name": name,
        "address": address,
        "phone": phone,
        "website": website,
        "category": category.replace("_", " ").title(),
        "map_url": map_url,
    }


# =========================================================
# 7. HOMEPAGE
# =========================================================

@app.route("/")
def home():

    return render_template("index.html")


# =========================================================
# 8. BUSINESS SEARCH API
# =========================================================

@app.route("/api/search", methods=["POST"])
def search_businesses():

    try:

        data = request.get_json(silent=True) or {}

        keyword = str(data.get("keyword", "")).strip()

        location = str(data.get("location", "")).strip()

        try:
            radius = int(data.get("radius", 5000))
        except (ValueError, TypeError):
            return jsonify({
                "error": "Invalid search radius."
            }), 400

        if not keyword or not location:

            return jsonify({
                "error": "Business category and location are required."
            }), 400

        if radius not in (2000, 5000, 10000, 20000):

            return jsonify({
                "error": "Please select a valid search radius."
            }), 400

        app.logger.info(
            f"Business search: {keyword} in {location}, radius {radius}"
        )

        # Step 1: Convert location into coordinates

        lat, lon = geocode_location(location)

        # Step 2 and 3: Build query and search Overpass (with cache)

        elements = fetch_overpass_cached(keyword, lat, lon, radius)

        # Step 4: Extract business records

        places = []
        seen = set()

        for element in elements:

            business = extract_business(element)

            if not business:
                continue

            unique_key = (
                business["name"].lower(),
                business["map_url"]
            )

            if unique_key in seen:
                continue

            seen.add(unique_key)

            places.append(business)

            if len(places) >= 500:
                break

        app.logger.info(
            f"Search completed. Found {len(places)} businesses."
        )

        return jsonify({
            "success": True,
            "location": location,
            "radius": radius,
            "places": places,
            "total": len(places),
            "note": (
                f"Found {len(places)} businesses."
                if places
                else "No matching businesses found. Try another category or location."
            ),
        })

    except ValueError as e:

        return jsonify({
            "error": str(e)
        }), 400

    except Exception as e:

        app.logger.exception("Business search failed.")

        return jsonify({
            "error": str(e)
        }), 503


# =========================================================
# 9. EXPORT DATA VALIDATION
# =========================================================

EXPORT_FIELDS = [
    "name",
    "address",
    "phone",
    "website",
    "category",
    "map_url",
]


def get_export_places():

    data = request.get_json(silent=True) or {}

    places = data.get("places", [])

    if not isinstance(places, list):

        raise ValueError("Invalid export data.")

    if not places:

        raise ValueError("No business records available to export.")

    if len(places) > 500:

        raise ValueError("Maximum 500 records can be exported.")

    clean_places = []

    for place in places:

        if not isinstance(place, dict):
            continue

        clean_places.append({
            field: str(place.get(field, "") or "")
            for field in EXPORT_FIELDS
        })

    if not clean_places:

        raise ValueError("No valid business records found.")

    return clean_places


# =========================================================
# 10. CSV EXPORT API
# =========================================================

@app.route("/api/export/csv", methods=["POST"])
def export_csv():

    try:

        places = get_export_places()

        output = io.StringIO()

        writer = csv.DictWriter(
            output,
            fieldnames=EXPORT_FIELDS
        )

        writer.writeheader()

        writer.writerows(places)

        csv_bytes = io.BytesIO(
            output.getvalue().encode("utf-8-sig")
        )

        csv_bytes.seek(0)

        return send_file(
            csv_bytes,
            mimetype="text/csv",
            as_attachment=True,
            download_name="osm_business_leads.csv",
        )

    except ValueError as e:

        return jsonify({
            "error": str(e)
        }), 400

    except Exception:

        app.logger.exception("CSV export failed.")

        return jsonify({
            "error": "Unable to export CSV file."
        }), 500


# =========================================================
# 11. EXCEL EXPORT API
# =========================================================

@app.route("/api/export/xlsx", methods=["POST"])
def export_xlsx():

    try:

        places = get_export_places()

        workbook = Workbook()

        sheet = workbook.active

        sheet.title = "Business Leads"

        headers = [
            "Business Name",
            "Address",
            "Phone",
            "Website",
            "Category",
            "OpenStreetMap URL",
        ]

        sheet.append(headers)

        for place in places:

            sheet.append([
                place["name"],
                place["address"],
                place["phone"],
                place["website"],
                place["category"],
                place["map_url"],
            ])

        # Set readable column widths

        column_widths = {
            "A": 30,
            "B": 40,
            "C": 20,
            "D": 35,
            "E": 22,
            "F": 55,
        }

        for column, width in column_widths.items():

            sheet.column_dimensions[column].width = width

        output = io.BytesIO()

        workbook.save(output)

        output.seek(0)

        return send_file(
            output,
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name="osm_business_leads.xlsx",
        )

    except ValueError as e:

        return jsonify({
            "error": str(e)
        }), 400

    except Exception:

        app.logger.exception("Excel export failed.")

        return jsonify({
            "error": "Unable to export Excel file."
        }), 500


# =========================================================
# 12. RUN FLASK APPLICATION
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )