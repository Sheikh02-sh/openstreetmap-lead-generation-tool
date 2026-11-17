import requests
urls = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]
query = "[out:json][timeout:10];node(31.55,74.25,31.551,74.251);out 1;"
headers = {"User-Agent": "OSMLeadFinder/1.0"}
for url in urls:
    try:
        response = requests.post(
            url,
            data={"data": query},
            headers=headers,
            timeout=(10, 15)
        )
        print("\nSERVER:", url)
        print("STATUS:", response.status_code)
        print("RESPONSE:", response.text[:250])
    except Exception as error:
        print("\nSERVER:", url)
        print("ERROR:", type(error).__name__, str(error)[:200])
