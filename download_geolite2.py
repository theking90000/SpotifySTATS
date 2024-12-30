import os
import requests

# Create the directory if it doesn't exist
os.makedirs('databases', exist_ok=True)

# URLs for the GeoLite2 databases
urls = {
    "GeoLite2-ASN.mmdb": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb",
    "GeoLite2-Country.mmdb": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
}

# Download each file and save it to the databases directory
for filename, url in urls.items():
    response = requests.get(url)
    with open(os.path.join('databases', filename), 'wb') as file:
        file.write(response.content)

print("GeoLite2 databases downloaded successfully.")
