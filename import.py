import os
import json
import sqlite3

# Directory containing the JSON files
DATA_DIRECTORY = "Spotify Extended Streaming History"

# SQLite database file
DATABASE_FILE = "streaming_history.db"

# Table name
TABLE_NAME = "history"

# Define the SQLite schema
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    ts DATETIME,
    platform TEXT,
    ms_played INTEGER,
    conn_country TEXT,
    ip_addr TEXT,
    master_metadata_track_name TEXT,
    master_metadata_album_artist_name TEXT,
    master_metadata_album_album_name TEXT,
    spotify_track_uri TEXT,
    episode_name TEXT,
    episode_show_name TEXT,
    spotify_episode_uri TEXT,
    reason_start TEXT,
    reason_end TEXT,
    shuffle BOOLEAN,
    skipped BOOLEAN,
    offline BOOLEAN,
    offline_timestamp INTEGER,
    incognito_mode BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_ip_addr ON {TABLE_NAME} (ip_addr);
CREATE INDEX IF NOT EXISTS idx_platform ON {TABLE_NAME} (platform);
CREATE INDEX IF NOT EXISTS idx_artist ON {TABLE_NAME} (master_metadata_album_artist_name);
CREATE INDEX IF NOT EXISTS idx_track_name ON {TABLE_NAME} (master_metadata_track_name);
CREATE INDEX IF NOT EXISTS idx_id ON {TABLE_NAME} (spotify_track_uri);
"""

def create_database_schema(cursor):
    """Create the database schema."""
    cursor.executescript(SCHEMA)

def insert_data(cursor, data):
    """Insert a list of JSON records into the database."""
    placeholders = ", ".join(["?" for _ in data[0]])
    columns = ", ".join(data[0].keys())
    query = f"INSERT INTO {TABLE_NAME} ({columns}) VALUES ({placeholders})"
    cursor.executemany(query, [tuple(record.values()) for record in data])

def load_json_files(directory):
    """Load and parse all JSON files in the specified directory."""
    records = []
    for filename in os.listdir(directory):
        if filename.endswith(".json"):
            file_path = os.path.join(directory, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                try:
                    records.extend(json.load(file))
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON in {filename}: {e}")
    return records

def main():
    # Connect to the SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Create the schema
    create_database_schema(cursor)

    # Load JSON data from files
    json_data = load_json_files(DATA_DIRECTORY)

    # Insert the data into the database
    if json_data:
        insert_data(cursor, json_data)

    # Commit and close the connection
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
