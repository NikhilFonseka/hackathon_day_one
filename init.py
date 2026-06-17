from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime
import json
from dotenv import load_dotenv
from groq import Groq

# 1. Load the hidden secrets from your .env file
load_dotenv()

# 2. Initialize the Groq terminal uplink
client = Groq(api_key="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")

# Set up paths for the database and image uploads
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'Database', 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

def get_db_connection():
    """Helper function to open a connection to the SQLite database with timeout handling."""
    # timeout=30 tells SQLite to wait up to 30 seconds for a lock to clear before throwing an error
    conn = sqlite3.connect(DB_PATH, timeout=30)
    
    # Enable WAL mode for better concurrent read/write handling across multiple concurrent traffic threads
    conn.execute('PRAGMA journal_mode=WAL;')
    
    conn.row_factory = sqlite3.Row  # Allows us to access columns by name
    return conn

def init_db():
    """Ensures directories and all four tables exist before the app runs."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    conn = get_db_connection()
    
    # 1. Create User Table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS User (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profile_image TEXT NOT NULL
        )
    ''')
    
    # 2. Create Event Table
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

    # 3. Create Selected_Event Table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS Selected_Event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            password TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES Event(event_id)
        )
    ''')

    # 4. Create friendreqs Table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS friendreqs (
            interactionid INTEGER PRIMARY KEY AUTOINCREMENT,
            sendinguser INTEGER NOT NULL,
            recievinguser INTEGER NOT NULL,
            accepted_rejected_waiting TEXT NOT NULL DEFAULT 'waiting',
            FOREIGN KEY(sendinguser) REFERENCES User(id),
            FOREIGN KEY(recievinguser) REFERENCES User(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    
    # REQUIRED: A secret key is needed to sign the cookies securely
    app.secret_key = 'super_secret_hackathon_key' 
    
    # Initialize database when the app is created
    init_db()

    @app.route('/')
    def index():
        return render_template('index.html.jinja', current_year=datetime.now().year)

    @app.route('/profile')
    def profile():
        if 'user_id' not in session:
            return render_template('signinsignup.html.jinja')

        user_id = session['user_id']
        conn = get_db_connection()

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
        
        conn.close()

        return render_template('signinsignup.html.jinja', pending_reqs=pending_reqs, friends=friends)

    @app.route('/send_request', methods=['POST'])
    def send_request():
        if 'user_id' not in session:
            return redirect('/')
            
        target_email = request.form.get('friend_email')
        sender_id = session['user_id']

        conn = get_db_connection()
        target_user = conn.execute('SELECT id FROM User WHERE email = ?', (target_email,)).fetchone()

        if target_user and target_user['id'] != sender_id:
            conn.execute('''
                INSERT INTO friendreqs (sendinguser, recievinguser, accepted_rejected_waiting)
                VALUES (?, ?, 'waiting')
            ''', (sender_id, target_user['id']))
            conn.commit()
            
        conn.close()
        return redirect('/profile')

    @app.route('/handle_request/<int:interactionid>', methods=['POST'])
    def handle_request(interactionid):
        if 'user_id' not in session:
            return redirect('/')
            
        action = request.form.get('action')

        if action in ['accepted', 'rejected']:
            conn = get_db_connection()
            conn.execute('''
                UPDATE friendreqs
                SET accepted_rejected_waiting = ?
                WHERE interactionid = ? AND recievinguser = ?
            ''', (action, interactionid, session['user_id']))
            conn.commit()
            conn.close()

        return redirect('/profile')

    @app.route('/home')
    def home():
        return "Home Page Coming Soon!"

    @app.route('/calendar')
    def calendar():
        conn = get_db_connection()
        events = conn.execute('SELECT * FROM Event ORDER BY event_date ASC, event_time ASC').fetchall()
        
        # Fallback tracking variables (available outside login scopes)
        interested_ids = []
        friends_attending = {}
        recommended_ids = []
        wildcard_ids = []

        if 'user_id' in session:
            user_id = session['user_id']
            
            # 1. Fetch user's tracked events
            rows = conn.execute('SELECT event_id FROM Selected_Event WHERE password = ?', (str(user_id),)).fetchall()
            interested_ids = [row['event_id'] for row in rows]
            
            # 2. Fetch allies' events
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

            # 3. --- GROQ AI RECOMMENDATION ENGINE ---
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

        conn.close()
        
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
            house_points = int(request.form.get('house_points', 0))
            event_date = request.form.get('event_date')
            event_time = request.form.get('event_time')
            image_file = request.files.get('image')

            filename = None
            if image_file and image_file.filename != '':
                filename = secure_filename(image_file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image_file.save(file_path)

            conn = get_db_connection()
            conn.execute('''
                INSERT INTO Event (name, house_points, event_date, event_time, image) 
                VALUES (?, ?, ?, ?, ?)
            ''', (name, house_points, event_date, event_time, filename))
            conn.commit()
            conn.close()

            return redirect(url_for('calendar'))

        return render_template('upload.html.jinja')
    
    @app.route('/interested/<int:event_id>', methods=['POST'])
    def mark_interested(event_id):
        if 'user_id' not in session:
            return redirect(url_for('calendar'))
        
        user_id = session['user_id']
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO Selected_Event (event_id, password)
            VALUES (?, ?)
        ''', (event_id, str(user_id)))
        conn.commit()
        conn.close()
        
        return redirect(url_for('calendar'))

    @app.route('/signup', methods=['POST'])
    def signup():
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        image_file = request.files.get('profile_image')

        if not (name and email and password and image_file):
            return "Missing required fields.", 400

        filename = secure_filename(image_file.filename)
        if filename:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(file_path)
        else:
            return "Invalid file.", 400

        hashed_password = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO User (name, email, password, profile_image) VALUES (?, ?, ?, ?)',
                (name, email, hashed_password, filename)
            )
            conn.commit()
            
            session['user_id'] = cursor.lastrowid
            session['user_name'] = name
            conn.close()
            
            return redirect(url_for('profile'))
        
        except sqlite3.IntegrityError:
            return "An account with that email already exists.", 400
        except Exception as e:
            return f"An error occurred: {e}", 500

    @app.route('/signin', methods=['POST'])
    def signin():
        email = request.form.get('email')
        password = request.form.get('password')

        if not (email and password):
            return "Missing required fields.", 400

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM User WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('profile'))
        else:
            return render_template('signinsignup.html.jinja', error="[AUTHORIZATION FAILED: INVALID CREDENTIALS]")

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('profile'))

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)