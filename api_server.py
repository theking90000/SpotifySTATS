"""
The API server is the bridge allowing to get spotify metadatas,
such as artist, album, track, playlist, images, etc.

It can be either started on itself or included withing the spot_server.py
"""

import sqlite3
from datetime import datetime
import json
from flask import Blueprint, Flask, request, jsonify, g
from os import environ, path
import sys
from threading import Semaphore, Lock
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth, CacheFileHandler

DATABASE = 'spot_api.db'
app = Blueprint('api_server', __name__)

if path.exists('.env'):
    with open('.env') as f:
        for line in f:
            k, v = line.strip().split('=')
            environ[k] = v

CLIENT_ID = environ.get('SPOTIFY_CLIENT_ID')
CLIENT_SECRET = environ.get('SPOTIFY_CLIENT_SECRET')

if not CLIENT_ID or not CLIENT_SECRET:
    raise Exception('Missing Spotify client ID or secret')
SCOPES=''
auth_manager = SpotifyOAuth(scope=SCOPES, client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                             redirect_uri='http://localhost:8888/callback',
                             open_browser=False, cache_handler=CacheFileHandler(cache_path='.spotipy_cache'))

if not auth_manager.get_cached_token():
    print('Auth token not found! or expired')
    print('Please refresh it')
    if '--no-token' in sys.argv:
        print('--no-token passed, exiting')
        exit(1)
    auth_manager.get_access_token()

sp = spotipy.Spotify(auth_manager=auth_manager)

# Concurrency and related Locks
concurrent_limit = Semaphore(2)
per_second_rate_limit = 2

rate_limit_lock = Lock()
last_execution_times = []

def acquire_resource(work):
    global last_execution_times

    with concurrent_limit:  # Limit concurrency to 2 requests
        with rate_limit_lock:  # Ensure thread-safe access to rate limiting logic
            # Enforce rate limiting
            current_time = time.time()
            # Remove timestamps older than 1 second
            last_execution_times = [t for t in last_execution_times if current_time - t < 1]
            
            if len(last_execution_times) >= per_second_rate_limit:
                # Wait until the oldest request is 1 second old
                time_to_wait = 1 - (current_time - last_execution_times[0])
                time.sleep(time_to_wait)
                current_time = time.time()
                # Remove outdated timestamps again
                last_execution_times = [t for t in last_execution_times if current_time - t < 1]
            
            # Record the current request's timestamp
            last_execution_times.append(current_time)

        # Perform the computation
        result = work()
    
    return result

def get_db():
    db = getattr(g, '_database_api', None)
    if db is None:
        db = g._database_api = sqlite3.connect(DATABASE)
        c=db.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS query (id TEXT PRIMARY KEY, response TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, expires DATETIME)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS query_id ON query (id)")
        db.commit()
    return db

def get_query(id):
    db = get_db()
    c = db.cursor()
    c.execute('SELECT response, timestamp, expires FROM query WHERE id = ?', (id,))
    r = c.fetchone()
    if not r:
        return None, None
    res, ts, exp = r
    print(ts, exp)
    ts, exp = datetime.fromisoformat(ts), datetime.fromisoformat(exp) if exp else None
    if exp and exp < datetime.now():
        return None, None
    return res, ts

def get_or(id, fn, args, exp=None):
    res, ts = get_query(id)
    if res:
        return res
    res = acquire_resource(lambda: fn(*args))
    db = get_db()
    c = db.cursor()
    c.execute('INSERT INTO query (id, response, expires) VALUES (?, ?, ?) ON CONFLICT REPLACE SET response = ? SET expires = ? SET timestamp = NOW()', (id, res, exp, res, exp))
    db.commit()
    return res

def get_or_json(id, fn, args, exp=None):
    res, ts = get_query(id)
    if res:
        return json.loads(res)
    res = acquire_resource(lambda: fn(*args))
    db = get_db()
    c = db.cursor()
    c.execute('INSERT INTO query (id, response, expires) VALUES (?, ?, ?)', (id, json.dumps(res), exp))
    db.commit()
    return res

@app.get('/track/<id>')
def track(id):
    market = request.args.get('market', 'BE')
    return get_or_json('track'+id+market, lambda: sp.track(id, market=market), [])

@app.get('/tracks/<id>')
def tracks(id):
    market = request.args.get('market', 'BE')
    ids = id.split(',')
    return get_or_json('tracks'+id+market, lambda: sp.tracks(ids, market=market), [])


@app.get('/artist/<id>')
def artist(id):
    market = request.args.get('market', 'BE')
    return get_or_json('artist'+id+market, lambda: sp.artist(id, market=market), [])

if __name__ == '__main__':
    app2 = Flask(__name__)
    app2.register_blueprint(app) 
    app2.run(debug=True) 