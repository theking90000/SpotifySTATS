"""
Managed environment hosting for the project
Requires docker.
"""

import docker.errors
from flask import Flask, redirect, send_from_directory, session, request, g, session, render_template, Response
import sqlite3
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from requests_oauthlib import OAuth2Session
from os import environ, path
import uuid
import docker
from flask_executor import Executor
import tarfile
import io
import requests


app = Flask(__name__, static_folder='managed_web', template_folder='managed_web')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1000 * 1000

executor = Executor(app)

try:
    client = docker.from_env()
    # Build the image
    if not environ.get('DOCKER_IMAGE'):
        print('No DOCKER_IMAGE specified. Building image from current directory...')
        client.images.build(path='.', tag='spotstats_dockerimage:latest')
        image = 'spotstats_dockerimage:latest'
    else:
        image = environ.get('DOCKER_IMAGE')
except:
    print('Docker not found. Please install docker and run the daemon.')
    exit(1)

if path.exists('.env'):
    with open('.env') as f:
        for line in f:
            k, v = line.strip().split('=')
            environ[k] = v
environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app.secret_key = environ.get('SECRET_KEY')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = '.login'

client_id = environ.get('CLIENT_ID')
client_secret = environ.get('CLIENT_SECRET')
authorization_base_url = environ.get('AUTHORIZATION_BASE_URL')
token_url = environ.get('TOKEN_URL')
redirect_uri = environ.get('REDIRECT_URI')
user_url = environ.get('USER_URL')
scope = []

# Include API
import api_server
import zipfile
app.register_blueprint(api_server.app, url_prefix='/api')

DATABASE = 'managed.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # setup DB
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (id VARCHAR(100) PRIMARY KEY, last_online TIMESTAMP);
            CREATE TABLE IF NOT EXISTS instances (id TEXT PRIMARY KEY, user_id VARCHAR(100), container TEXT, container_ip TEXT, state TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
        ''')
        db.execute('PRAGMA journal_mode=WAL')
        db.commit()
    return db

@app.after_request
def after_request(response):
    #print('X', session, 'user' in session, session.user)
    if 'user' in session and session['user'] is not None:
        db = get_db()
        print(session['user'])
        db.execute('UPDATE users SET last_online = current_timestamp WHERE id = ?', (session['user'],))
        db.commit()
    return response

class User(UserMixin):
    pass

@login_manager.user_loader
def load_user(user_id):
    user = User()
    user.id = user_id
    return user

@app.route('/res/<path:path>')
def serve_file(path):
    return send_from_directory(app.static_folder+"/res", path)

@app.route('/login')
def login():
    oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope)
    authorization_url, state = oauth.authorization_url(authorization_base_url, access_type='offline', prompt='select_account')
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('token', None)
    return redirect('/')

@app.route('/callback')
def callback():
    oauth = OAuth2Session(client_id, state=session['oauth_state'], redirect_uri=redirect_uri)
    token = oauth.fetch_token(token_url, client_secret=client_secret, authorization_response=request.url)
    session['token'] = token
    user_info = oauth.get(user_url).json()
    session['user'] = user_info['uri'] if 'uri' in user_info else user_info['email']
    # insert user if not in database
    db = get_db()
    db.execute('INSERT OR IGNORE INTO users (id) VALUES (?)', (session['user'],))
    db.commit()

    return redirect('/')

@app.route('/')
def index():
    if 'user' not in session:
        return render_template('index.html', content='_login.html')
    
    db = get_db()
    # check if instance is running
    c = db.cursor()
    c.execute('SELECT id, container, state FROM instances WHERE user_id = ?', (session['user'],))
    res = c.fetchone() 
    c_id, container, state = None, None, None
    if res:
        c_id, container, state = res
    print('Container:', container, state, c_id)
    return render_template('index.html', content='_index.html', user=session['user'],
                           container=container, state=state, container_id=c_id)
    
@app.post('/upload')
def upload():
    # get form data
    if 'user' not in session:
        return 'Unauthorized', 403
    
    if not 'file' in request.files:
        return 'No file uploaded', 400
    file = request.files['file']
    # attempt to unzip the file and validate its content
    if file.filename == '':
        return redirect(request.url)

    start_instance(session['user'], file)

    db = get_db()
    c = db.cursor()
    
    return redirect('/')

def stop_instance(user_id):
    db = get_db()
    c = db.cursor()
    c.execute('SELECT container FROM instances WHERE user_id = ?', (user_id,))
    res = c.fetchone()
    if res is None:
        return
    
    c.execute('DELETE FROM instances WHERE user_id = ?', (user_id,))
    db.commit()
    
    try:
        container = client.containers.get(res[0])
        container.remove(force=True)
    except docker.errors.NotFound:
        pass

def start_instance(user_id, datafile):
    stop_instance(user_id)
    db = get_db()
    c = db.cursor()
    # TODO: add resource limits
    id = str(uuid.uuid4())

    c.execute('INSERT INTO instances (id, user_id, state) VALUES (?, ?, "init")', (id, user_id))
    db.commit()

    container = client.containers.run(image, detach=True, auto_remove=True,environment={
        'SCRIPT_NAME': '/app/' + id,
        'APPLICATION_ROOT': '/app/' + id,
        'API_ENDPOINT': '/api',
    }) 
    container = client.containers.get(container.id)
    
    ip = container.attrs['NetworkSettings']['IPAddress']
    
    c.execute('UPDATE instances SET container = ?, container_ip = ?, state = "created" WHERE id = ?', (container.id, ip, id))
    db.commit()

    # add task
    configure_instance(id, datafile)
    #executor.submit(configure_instance, user_id, datafile)

def set_state(id, state):
    db = get_db()
    c = db.cursor()
    print('Setting state to', state, id)
    c.execute('UPDATE instances SET state = ? WHERE id = ?', (state, id))
    db.commit()

def configure_instance(id, datafile):
    db = get_db()
    c = db.cursor()
    print('Configuring instance...', id, datafile)
    c.execute('SELECT container, state FROM instances WHERE id = ?', (id,))
    res = c.fetchone()
    if res is None:
        return
    
    idc, state = res
    # print(id, state, datafile, datafile.stream)
    container = client.containers.get(idc) # configure the container
    
    # process the archive
    # we open the zip file and extract each json file (<20MB)

    zip_bytes = io.BytesIO(datafile.stream.read())
    
    b = io.BytesIO()
    i=0
    with tarfile.open(mode='w|', fileobj=b) as tar:
        with zipfile.ZipFile(zip_bytes) as zf:
            for name in zf.namelist():
                
                if name.endswith('.json'):
                    info = tarfile.TarInfo(name=f'{i}.json')
                    i += 1
                    info.size = zf.getinfo(name).file_size
                    file_bytes = zf.read(name)
                    tar.addfile(info, io.BytesIO(file_bytes))
    
    b.seek(0)
    container.exec_run('mkdir -p /app/Spotify\ Extended\ Streaming\ History')
    container.put_archive('/app/Spotify Extended Streaming History', b)

    set_state(id, 'importing')
    # import 
    container.exec_run('python3 /app/import.py')

    set_state(id, 'ready')
    
@app.route('/app/<id>', defaults={'path': ''})
@app.route('/app/<id>/', defaults={'path': ''})
@app.route('/app/<id>/<path:path>')
def instance_proxy(id, path):
    # check if id is UUID
    try:
        print('checking ID', id)
        uuid.UUID(id)
    except ValueError:
        return
    if 'user' not in session or session['user'] is None:
        return redirect('/')
    db = get_db()
    c = db.cursor()
    c.execute('SELECT container_ip, container, state FROM instances WHERE user_id = ? and id = ?', (session['user'], id))
    res = c.fetchone()
    
    if res is None:
        return redirect('/')
    
    ip, cid, state = res
    if state != 'ready':
        return redirect('/')
    
    # Reverse proxy to the container
    print('req', request.full_path)
    resp = requests.get(f'http://{ip}:5000/{request.full_path}')

    response = Response(resp.content, status=resp.status_code, headers=dict(resp.headers))
    response.headers['X-Proxy-To'] = cid
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')