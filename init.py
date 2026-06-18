from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime
import json
from dotenv import load_dotenv
from groq import Groq

# 1. Load environment configurations
load_dotenv()

# 2. Initialize the Groq core uplink
client = Groq(api_key="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")

# Path bindings for database state and assets
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'Database', 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

def get_db_connection():
    """Opens a connection with explicit timeout configurations and WAL optimizations."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row  
    return conn

def init_db():
    """Initializes schema blueprints using context managers to prevent initialization lockups."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    with get_db_connection() as conn:
        # User blueprint: Enforces lowercase integrity, handles optional images
        conn.execute('''
            CREATE TABLE IF NOT EXISTS User (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                profile_image TEXT
            )
        ''')
        
        # Event blueprint
        conn.execute('''
            CREATE TABLE IF NOT EXISTS Event (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                house_points INTEGER NOT NULL DEFAULT 0,
                event_date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                image TEXT
            )
        ''')

        # Selected_Event blueprint: Added composite UNIQUE constraint to protect table space
        conn.execute('''
            CREATE TABLE IF NOT EXISTS Selected_Event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                password TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES Event(event_id),
                UNIQUE(event_id, password)
            )
        ''')

        # friendreqs blueprint: Added composite UNIQUE constraint to stop tracking redundant spam
        conn.execute('''
            CREATE TABLE IF NOT EXISTS friendreqs (
                interactionid INTEGER PRIMARY KEY AUTOINCREMENT,
                sendinguser INTEGER NOT NULL,
                recievinguser INTEGER NOT NULL,
                accepted_rejected_waiting TEXT NOT NULL DEFAULT 'waiting',
                FOREIGN KEY(sendinguser) REFERENCES User(id),
                FOREIGN KEY(recievinguser) REFERENCES User(id),
                UNIQUE(sendinguser, recievinguser)
            )
        ''')
        conn.commit()

def render_profile_page_with_data(error=None, signup_error=None):
    """Safely extracts interface datasets through explicit context isolation."""
    if 'user_id' not in session:
        return render_template('signinsignup.html.jinja', error=error, signup_error=signup_error, pending_reqs=[], friends=[])

    user_id = session['user_id']
    
    with get_db_connection() as conn:
        pending_reqs = conn.execute('''
            SELECT f.interactionid, u.name as sender_name
            FROM friendreqs f
            JOIN User u ON f.sendinguser = u.id
            WHERE f.recievinguser = ? AND f.accepted_rejected_waiting = 'waiting'
        ''', (user_id,)).fetchall()

        friends = conn.execute('''
            SELECT u.name
            FROM friendreqs f
            JOIN User u ON (u.id = f.sendinguser OR u.id = f.recievinguser)
            WHERE (f.sendinguser = ? OR f.recievinguser = ?)
              AND f.accepted_rejected_waiting = 'accepted'
              AND u.id != ?
        ''', (user_id, user_id, user_id)).fetchall()
        
    return render_template('signinsignup.html.jinja', pending_reqs=pending_reqs, friends=friends, error=error, signup_error=signup_error)

def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.secret_key = 'super_secret_hackathon_key' 
    
    init_db()

    @app.route('/')
    def index():
        return render_template('index.html.jinja', current_year=datetime.now().year)

    @app.route('/profile')
    def profile():
        return render_profile_page_with_data()

    @app.route('/send_request', methods=['POST'])
    def send_request():
        if 'user_id' not in session:
            return redirect('/')
            
        target_email = request.form.get('friend_email', '').strip().lower()
        sender_id = session['user_id']

        with get_db_connection() as conn:
            target_user = conn.execute('SELECT id FROM User WHERE email = ?', (target_email,)).fetchone()

            if target_user and target_user['id'] != sender_id:
                # Direct mitigation against duplicate tracking constraints using SQLite fallback logic
                conn.execute('''
                    INSERT OR IGNORE INTO friendreqs (sendinguser, recievinguser, accepted_rejected_waiting)
                    VALUES (?, ?, 'waiting')
                ''', (sender_id, target_user['id']))
                conn.commit()
            
        return redirect('/profile')

    @app.route('/handle_request/<int:interactionid>', methods=['POST'])
    def handle_request(interactionid):
        if 'user_id' not in session:
            return redirect('/')
            
        action = request.form.get('action')

        if action in ['accepted', 'rejected']:
            with get_db_connection() as conn:
                conn.execute('''
                    UPDATE friendreqs
                    SET accepted_rejected_waiting = ?
                    WHERE interactionid = ? AND recievinguser = ?
                ''', (action, interactionid, session['user_id']))
                conn.commit()

        return redirect('/profile')

    @app.route('/home')
    def home():
        return "Home Page Coming Soon!"

    @app.route('/calendar')
    def calendar():
        interested_ids = []
        friends_attending = {}
        recommended_ids = []
        wildcard_ids = []

        with get_db_connection() as conn:
            events = conn.execute('SELECT * FROM Event ORDER BY event_date ASC, event_time ASC').fetchall()
            
            if 'user_id' in session:
                user_id = session['user_id']
                
                rows = conn.execute('SELECT event_id FROM Selected_Event WHERE password = ?', (str(user_id),)).fetchall()
                interested_ids = [row['event_id'] for row in rows]
                
                attending_query = '''
                    SELECT se.event_id, u.name
                    FROM Selected_Event se
                    JOIN User u ON se.password = CAST(u.id AS TEXT)
                    JOIN friendreqs f ON (
                        (f.sendinguser = ? AND f.recievinguser = u.id) OR
                        (f.recievinguser = ? AND f.sendinguser = u.id)
                    )
                    WHERE f.accepted_rejected_waiting = 'accepted'
                '''
                attending_rows = conn.execute(attending_query, (user_id, user_id)).fetchall()
                
                for row in attending_rows:
                    eid = row['event_id']
                    if eid not in friends_attending:
                        friends_attending[eid] = []
                    if row['name'] not in friends_attending[eid]:
                        friends_attending[eid].append(row['name'])

                if interested_ids or friends_attending:
                    user_history_names = [e['name'] for e in events if e['event_id'] in interested_ids]
                    all_events_data = [{'id': e['event_id'], 'name': e['name']} for e in events]
                    
                    prompt = f"""
                    You are an academic event recommendation engine. Analyze the student's data and recommend 4 upcoming events.
                    - Student's current interests: {user_history_names}
                    - Student's friends are attending: {friends_attending}
                    - Available events: {all_events_data}

                    Rules:
                    1. Recommend 2 events that align with the student's current interests and friend network.
                    2. Recommend 2 "discovery" events that are outside the student's typical interests to encourage campus social integration.
                    3. Do not recommend events the student is already attending.

                    Return a JSON object: {{"recommended": [id1, id2], "wildcard": [id3, id4]}}
                    """
                    
                    try:
                        chat_completion = client.chat.completions.create(
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You output ONLY raw JSON objects. Do not write markdown, backticks, or conversational text. Start your response with '{' and end it with '}'."
                                },
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ],
                            model="openai/gpt-oss-20b",
                            temperature=0.3,
                        )
                        
                        raw_content = chat_completion.choices[0].message.content.strip()
                        
                        import re
                        json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                        clean_text = json_match.group(0) if json_match else raw_content
                        
                        ai_data = json.loads(clean_text)
                        recommended_ids = ai_data.get("recommended", [])
                        wildcard_ids = ai_data.get("wildcard", [])
                        
                    except Exception as e:
                        print(f"RobCo Groq Uplink Failure: {e}")
                        recommended_ids = []
                        wildcard_ids = []
        
        return render_template('calendar.html.jinja', 
                               events=events, 
                               interested_ids=interested_ids, 
                               friends_attending=friends_attending,
                               recommended_ids=recommended_ids,
                               wildcard_ids=wildcard_ids)
    
    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
        if request.method == 'POST':
            name = request.form.get('name')
            # FIX: Validates presence using an OR fallback strategy against blank forms
            house_points = int(request.form.get('house_points') or 0)
            event_date = request.form.get('event_date')
            event_time = request.form.get('event_time')
            image_file = request.files.get('image')

            filename = None
            if image_file and image_file.filename != '':
                filename = secure_filename(image_file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image_file.save(file_path)

            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO Event (name, house_points, event_date, event_time, image) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, house_points, event_date, event_time, filename))
                conn.commit()

            return redirect(url_for('calendar'))

        return render_template('upload.html.jinja')
    
    @app.route('/interested/<int:event_id>', methods=['POST'])
    def mark_interested(event_id):
        if 'user_id' not in session:
            return redirect(url_for('calendar'))
        
        user_id = session['user_id']
        with get_db_connection() as conn:
            # FIX: Protects schema with an INSERT OR IGNORE logic rule against track spamming
            conn.execute('''
                INSERT OR IGNORE INTO Selected_Event (event_id, password)
                VALUES (?, ?)
            ''', (event_id, str(user_id)))
            conn.commit()
        
        return redirect(url_for('calendar'))

    @app.route('/signup', methods=['POST'])
    def signup():
        name = request.form.get('name')
        # FIX: Enforce uniform sanitization across strings
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        image_file = request.files.get('profile_image')

        if not (name and email and password):
            return render_profile_page_with_data(signup_error="Missing required fields.")

        if not email.endswith('@rosmini.school.nz'):
            return render_profile_page_with_data(signup_error="Registration restricted! Must be a @rosmini.school.nz email address.")

        filename = None
        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            if filename:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image_file.save(file_path)

        hashed_password = generate_password_hash(password)

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO User (name, email, password, profile_image) VALUES (?, ?, ?, ?)',
                    (name, email, hashed_password, filename)
                )
                conn.commit()
                
                session['user_id'] = cursor.lastrowid
                session['user_name'] = name
                session['profile_image'] = filename
            
            return redirect(url_for('profile'))
        
        except sqlite3.IntegrityError:
            return render_profile_page_with_data(signup_error="An account with that email already exists.")
        except Exception as e:
            return render_profile_page_with_data(signup_error=f"An infrastructure error occurred: {e}")

    @app.route('/signin', methods=['POST'])
    def signin():
        # FIX: Enforce matching baseline casings during credential checking
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')

        if not (email and password):
            return render_profile_page_with_data(error="Missing credentials.")

        with get_db_connection() as conn:
            user = conn.execute('SELECT * FROM User WHERE email = ?', (email,)).fetchone()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['profile_image'] = user['profile_image']
            return redirect(url_for('profile'))
        else:
            return render_profile_page_with_data(error="Invalid email or password.")

    @app.route('/logout')
    def logout():
        """Cleanly wipes active session metrics to prevent stale access headers."""
        session.clear()
        return redirect(url_for('index'))
            
    return app

# GUNICORN BINDING INTERFACE FOR PRODUCTION RUNTIMES:
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)