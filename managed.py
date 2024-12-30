"""
Managed environment hosting for the project
Requires docker.
"""

from flask import Flask, redirect, send_from_directory, session, request, g, session, render_template
import sqlite3
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from requests_oauthlib import OAuth2Session
from os import environ, path
import uuid
import docker
from flask_executor import Executor
import tarfile
import io


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
from api_server import app as api_app
import zipfile
app.register_blueprint(api_app)

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
    c.execute('SELECT container FROM instances WHERE user_id = ?', (session['user'],))
    res = c.fetchone() 

    return render_template('index.html', content='_index.html', user=session['user'],
                           is_running=res is not None)
    
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
    except docker.NotFound:
        pass

def start_instance(user_id, datafile):
    stop_instance(user_id)
    db = get_db()
    c = db.cursor()
    # TODO: add resource limits
    container = client.containers.run(image, detach=True, auto_remove=True) 
    ip = container.attrs['NetworkSettings']['IPAddress']
    id = str(uuid.uuid4())
    c.execute('INSERT INTO instances (id, user_id, container, container_ip, state) VALUES (?, ?, ?, ?, "init")', (id, user_id, container.id, ip))
    db.commit()

    # add task
    configure_instance(user_id, datafile)
    #executor.submit(configure_instance, user_id, datafile)

def configure_instance(user_id, datafile):
    db = get_db()
    c = db.cursor()
    print('Configuring instance...', user_id, datafile)
    c.execute('SELECT container, state FROM instances WHERE user_id = ?', (user_id,))
    res = c.fetchone()
    if res is None:
        return
    
    id, state = res
    # print(id, state, datafile, datafile.stream)
    container = client.containers.get(id) # configure the container

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

    # import 
    container.exec_run('python3 /app/import.py')
    


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')