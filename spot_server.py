import sqlite3
from flask import Flask, send_from_directory, render_template, g, request, url_for
import geoip2.database
from datetime import datetime
import uuid
from os import environ

DATABASE = 'streaming_history.db'
COUNTRY = 'databases/GeoLite2-Country.mmdb'
ASN = 'databases/GeoLite2-ASN.mmdb'

app = Flask(__name__, static_folder='web', template_folder='web')
app.config['APPLICATION_ROOT'] = environ.get('APPLICATION_ROOT', '/')
BASE_URL = app.config['APPLICATION_ROOT'].rstrip('/')
API_ENDPOINT= environ.get('API_ENDPOINT', BASE_URL+'/api')


no_api = environ.get('SPOT_NO_API', False)
if not no_api:
    import api_server
    API_ENDPOINT = '/api'
    print(api_server.app)
    app.register_blueprint(api_server.app, url_prefix='/api')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

def get_geoip(name):
    geoip = getattr(g, '_geoip/'+name, None)
    if geoip is None:
        geoip = g._geoip = geoip2.database.Reader(name)
    return geoip

def get_years():
    years = getattr(g, '_years', None)
    if years is None:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT strftime('%Y', ts) as year from history GROUP BY year")
        years = [int(a[0]) for a in c.fetchall()]
        g._years = years
    return years

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

    geoip = getattr(g, '_geoip', None)
    if geoip is not None:
        geoip.close()

@app.context_processor
def get_api_endpoint():
    return dict(api_endpoint=API_ENDPOINT,
                generate_uuid=lambda: str(uuid.uuid4()),
                base_url=BASE_URL)

def format_duration(duration, max_unit='d'):
    u, m = ['d', 'h', 'm', 's'], [86400, 3600, 60, 1]

    s = ''
    for i in range(u.index(max_unit), len(u)):
        if duration >= m[i]:
            s += f"{int(duration // m[i])}{u[i]}"
            duration %= m[i]
    return s

def get_minmax_ts():
    m, M = getattr(g, '_minmax_ts', (None, None))
    if m is None or M is None:
        db = get_db()
        c = db.cursor()
        c.execute('SELECT min(ts), max(ts) FROM history')
        m, M = c.fetchone()
        m, M = g._minmax_ts = datetime.fromisoformat(m[:-1]), datetime.fromisoformat(M[:-1])

    return m, M

def get_full_year(f, t):
    if f is None or t is None:
        return None
    if f.endswith('-01-01T00:00:00Z') and t.endswith('-12-31T23:59:59Z'):
        a = f.split('-')[0]
        b = t.split('-')[0]

        return int(a) if a == b else None
    
def get_ft():
    f = request.args.get('from', None)
    t = request.args.get('to', None)
    is_year = get_full_year(f, t)
    m, M = get_minmax_ts()
    if f is None:
        f = m
    if t is None:
        t = M

    return f, t

def get_ft_y():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT strftime('%Y', ts) as year from history GROUP BY year")
    years = [int(a[0]) for a in c.fetchall()]

    f = request.args.get('from', None)
    t = request.args.get('to', None)
    is_year = get_full_year(f, t)
    if f is None or t is None:
        m, M = get_minmax_ts()
    if f is None:
        f = m
    if t is None:
        t = M

    return f, t, is_year, years



@app.route('/')
def serve_index():
    return render_template('index.html', content='_index.html')

@app.route('/res/<path:path>')
def serve_file(path):
    return send_from_directory(app.static_folder+"/res", path)

@app.route('/ip')
def get_ip():
    db = get_db()
    years = get_years()

    f = request.args.get('from', None)
    t = request.args.get('to', None)
    is_year = get_full_year(f, t)
    m, M = get_minmax_ts()
    if f is None:
        f = m
    if t is None:
        t = M

    c = db.cursor()
    c.execute('SELECT count(distinct ip_addr) FROM history WHERE ts >= ? AND ts <= ?', (f, t))
    count2 = c.fetchone()[0]

    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 100))
    c = db.cursor()
    c.execute('SELECT ip_addr, count(ip_addr) as c, max(ts) as ts, sum(ms_played) play_time FROM history WHERE ts >= ? AND ts <= ? GROUP BY ip_addr ORDER BY c DESC LIMIT ? OFFSET ?', (f, t, limit, offset))

    ips = c.fetchall()

    country = get_geoip(COUNTRY)
    asn = get_geoip(ASN)

    ips2 = []

    for ip, count, ts, play_time in ips:
        try:
            cnt = country.country(ip)
            cnt = cnt.country.iso_code.lower()
        except:
            cnt = 'unknwown'
        
        try:
            asnn = asn.asn(ip)
            asnn = asnn.autonomous_system_organization
        except Exception as e:
            asnn = "unknown"
        ips2.append((
            ip,
            count,
            ts,
            cnt,
            asnn,
            format_duration(play_time/1000)
        ))
    
    return render_template('index.html', content='_ip.html', ips=ips2, count=count2,
                           offset=offset, limit=limit, years=years, year=is_year, f=f, t=t)

@app.route('/ip/<ip>')
def get_ip_details(ip):
    db = get_db()

    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 100))

    c = db.cursor()
    c.execute('SELECT min(ts), max(ts), count(*), ip_addr, SUM(ms_played) FROM history WHERE ip_addr=?', (ip,))
    start, end, count, ip, playtime = c.fetchone()
    # parse datetime ISO with "Z" at the end
    start = datetime.fromisoformat(start[:-1])
    end = datetime.fromisoformat(end[:-1])
    playtime = format_duration(playtime/1000)

    country = get_geoip(COUNTRY)
    asn = get_geoip(ASN)

    try:
        cnt = country.country(ip)
        cnt = cnt.country.iso_code.lower()
    except:
        cnt = 'unknwown'
        
    try:
        asnn = asn.asn(ip)
        asnn = asnn.autonomous_system_organization
    except Exception as e:
        asnn = "unknown"
    
    c = db.cursor()
    c.execute('SELECT ts, platform, ms_played, master_metadata_track_name, spotify_track_uri, offline FROM history WHERE ip_addr=? ORDER BY ts DESC LIMIT ? OFFSET ?', (ip, limit, offset))
    history = c.fetchall()

    hs = []
    for h in history:
        hs.append((
            datetime.fromisoformat(h[0][:-1]),
            h[1],
            format_duration(h[2]/1000, 'm'),
            h[3],
            h[4],
            h[5]
        ))

    return render_template('index.html', content='_byip.html', ip=ip, history=hs,
                           start=start, end=end, count=count, offset=offset, limit=limit,
                           country=cnt, asn=asnn, playtime=playtime)


@app.route('/insights')
def insights():
    db = get_db()

    table = request.args.get('table', None)
    tc = int(request.args.get('top', 10))

    
    if table is None:
        f, t, is_year, years = get_ft_y()

        c = db.cursor()
        c.execute('SELECT count(*), sum(ms_played) FROM history WHERE ts >= ? AND ts <= ?', (f, t))
        count, playtime_raw = c.fetchone()
        playtime = format_duration(playtime_raw/1000, 'm')

        return render_template('index.html', content='_insights.html',
                           years=years, year=is_year, f=f, t=t,
                           count=count, playtime=playtime, playtime_raw=playtime_raw,
                           tc=tc)
    
    f, t = get_ft()

    if table == 'ttrackplaycount':
        c = db.cursor()
        c.execute('SELECT master_metadata_track_name, count(*) as c, sum(ms_played), master_metadata_album_artist_name, spotify_track_uri FROM history WHERE ts >= ? AND ts <= ? GROUP BY spotify_track_uri ORDER BY c DESC LIMIT ?', (f, t, tc))
        top_playcount = c.fetchall()

        t_playcount = []
        for tt in top_playcount:
            t_playcount.append((
                {"name": tt[0], "track": tt[4]},
                tt[1],
                format_duration(tt[2]/1000, 'm'),
                { "name": tt[3], "artist": tt[4]},
            ))

        return render_template('_components/table.html', rows=t_playcount, 
                               columns=['Track', 'Playcount', 'Playtime', 'Artist'])
    
    if table == 'ttrackplaytime':
        c = db.cursor()
        c.execute('SELECT master_metadata_track_name, count(*), sum(ms_played) as c, master_metadata_album_artist_name, spotify_track_uri FROM history WHERE ts >= ? AND ts <= ? GROUP BY spotify_track_uri ORDER BY c DESC LIMIT ?', (f, t, tc))
        top_playtime = c.fetchall()

        t_playtime = []
        for tt in top_playtime:
            t_playtime.append((
                { "name": tt[0], "track": tt[4]},
                tt[1],
                format_duration(tt[2]/1000, 'm'),
                { "name": tt[3], "artist": tt[4]},
            ))


        return render_template('_components/table.html', rows=t_playtime, 
                               columns=['Track', 'Playcount', 'Playtime', 'Artist'])
    
    if table == "tartistplaycount":
        c = db.cursor()
        c.execute('SELECT master_metadata_album_artist_name, count(*) as c, sum(ms_played), spotify_track_uri FROM history WHERE ts >= ? AND ts <= ? GROUP BY master_metadata_album_artist_name ORDER BY c DESC LIMIT ?', (f, t, tc))

        a_playcount = []
        for tt in c.fetchall():
            a_playcount.append((
                {"name": tt[0], "artist": tt[3]},
                tt[1],
                format_duration(tt[2]/1000, 'm'),
            ))

        return render_template('_components/table.html', rows=a_playcount, 
                               columns=['Artist', 'Playcount', 'Playtime'])
    
    if table == "tartistplaytime":

    # top X artists by play count
        c = db.cursor()
        c.execute('SELECT master_metadata_album_artist_name, count(*) , sum(ms_played) as c, spotify_track_uri FROM history WHERE ts >= ? AND ts <= ? GROUP BY master_metadata_album_artist_name ORDER BY c DESC LIMIT ?', (f, t, tc))

        a_playcount = []
        for tt in c.fetchall():
            a_playcount.append((
                {"name": tt[0], "artist": tt[3]},
                tt[1],
                format_duration(tt[2]/1000, 'm'),
            ))

        return render_template('_components/table.html', rows=a_playcount, 
                            columns=['Artist', 'Playcount', 'Playtime'])

    return "Unknown table"

@app.route('/track/<id>')
def gettrack(id):
    db = get_db()
    c = db.cursor()
    c.execute('SELECT ts, master_metadata_track_name, master_metadata_album_artist_name, count(*), spotify_track_uri FROM history WHERE spotify_track_uri=?', (id,))

    history = []
    for h in c.fetchall():
        history.append((
            datetime.fromisoformat(h[0][:-1]),
            h[1],
            h[2],
            h[3],
            #format_duration(h[4]/1000, 'm'),
            h[4]
        ))

    title = history[0][1]

    c.execute('SELECT count(*), sum(ms_played) FROM history WHERE spotify_track_uri=?', (id,))
    tcount, played = c.fetchone()

    return render_template('index.html', content='_track.html', history=history, id=id, title=title,
                           count=tcount, played=format_duration(played/1000, 'm'))


@app.route('/search')
def search():
    query = request.args.get('query', '')
    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 100))

    is_result = 'fetchtable' in request.args
    db = get_db()

    if is_result:
        f, t = get_ft()
        c = db.cursor()
        c.execute('SELECT  master_metadata_track_name, master_metadata_album_artist_name, count(*) as c, spotify_track_uri FROM history WHERE (master_metadata_track_name LIKE "%" || ? || "%" OR master_metadata_album_artist_name LIKE "%" || ? || "%") AND ts >= ? AND ts <= ? GROUP BY spotify_track_uri ORDER BY c DESC LIMIT ? OFFSET ?', (query, query, f, t, limit, offset))
        results = []
        
        for r in c.fetchall():
            results.append((
                { 'name': r[0], 'track': r[3]},
                r[1],
                r[2],
            ))
        return render_template('_components/table.html', rows=results, columns=['Track', 'Artist', 'Playcount'])
    
    f, t, is_year, years = get_ft_y()        

    return render_template('index.html', content='_search.html', query=query,
                           years=years, year=is_year, f=f, t=t,
                           offset=offset, limit=limit)

if __name__ == '__main__':
    # Check if the no-api flag is set
    app.run(debug=True)