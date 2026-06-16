from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime
import os
import json
from dotenv import load_dotenv
from groq import Groq

# 1. Load the hidden secrets from your .env file
load_dotenv()

# 2. Initialize the Groq terminal uplink
# It automatically hunts for the GROQ_API_KEY in your .env file
client = Groq()

# Set up paths for the database and image uploads
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'Database', 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

def get_db_connection():
    """Helper function to open a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allows us to access columns by name
    return conn

def init_db():
    """Ensures directories and the tables exist before the app runs."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    conn = get_db_connection()
    
    # Create User Table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS User (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profile_image TEXT NOT NULL
        )
    ''')
    
    # Create Event Table (Matching your provided schema)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS Event (
            event_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            house_points INTEGER NOT NULL DEFAULT 0,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            image TEXT
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
        # 1. If the user is NOT signed in, just show the login/signup forms safely
        if 'user_id' not in session:
            # We don't query the database, we just serve the raw template
            return render_template('signinsignup.html.jinja')

        # 2. If the user IS signed in, proceed with fetching their network data
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

        # Render the profile interface with the datalink info
        return render_template('signinsignup.html.jinja', pending_reqs=pending_reqs, friends=friends)

    
    @app.route('/send_request', methods=['POST'])
    def send_request():
        if 'user_id' not in session:
            return redirect('/')
            
        target_email = request.form.get('friend_email')
        sender_id = session['user_id']

        conn = get_db_connection()
        # Find the target user by their email
        target_user = conn.execute('SELECT id FROM User WHERE email = ?', (target_email,)).fetchone()

        # Ensure target exists and user isn't adding themselves
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
            
        action = request.form.get('action') # Will be 'accepted' or 'rejected'

        if action in ['accepted', 'rejected']:
            conn = get_db_connection()
            # Verify the current user is the one receiving the request before updating!
            conn.execute('''
                UPDATE friendreqs
                SET accepted_rejected_waiting = ?
                WHERE interactionid = ? AND recievinguser = ?
            ''', (action, interactionid, session['user_id']))
            conn.commit()
            conn.close()

        return redirect('/profile')

    # Placeholder routes for your navbar to prevent 500 errors
    @app.route('/home')
    def home():
        return "Home Page Coming Soon!"

    # Ensure this route matches the href="/calendar" in your navbar
    @app.route('/calendar')
    def calendar():
        conn = get_db_connection()
        events = conn.execute('SELECT * FROM Event ORDER BY event_date ASC, event_time ASC').fetchall()
        
        interested_ids = []
        friends_attending = {}
        recommended_ids = []

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
                You are a recommendation engine. Analyze the following data to recommend 2 upcoming events the user might like.
                - User is already attending these events: {user_history_names}
                - User's friends are attending these event IDs: {friends_attending}
                - All available events: {all_events_data}
                
                Based on what the user and their friends like, return ONLY a valid, raw JSON array of the 2 most recommended event IDs that the user is NOT already attending.
                Example output: [2, 5]
                """
                
                try:
                    # Establish uplink to Groq using Llama 3
                    chat_completion = client.chat.completions.create(
                        messages=[
                            {
                                "role": "system",
                                "content": "You output ONLY raw JSON arrays. Do not include markdown, backticks, or any conversational text."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        model="llama3-8b-8192",
                        temperature=0.2, # Low temperature keeps the AI focused on formatting correctly
                    )
                    
                    # Clean the datastream and convert to Python list
                    clean_text = chat_completion.choices[0].message.content.strip().strip('`').replace('json\n', '')
                    recommended_ids = json.loads(clean_text)
                    
                except Exception as e:
                    print(f"RobCo Groq Uplink Failure: {e}")
                    recommended_ids = []

        conn.close()
        
        # Transmit all data, including AI recommendations, to the terminal
        return render_template('calendar.html.jinja', 
                               events=events, 
                               interested_ids=interested_ids, 
                               friends_attending=friends_attending,
                               recommended_ids=recommended_ids)
    
    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
        # (Optional) Restrict access to logged-in users
        # if not session.get('user_name'):
        #     return redirect(url_for('profile'))

        if request.method == 'POST':
            # 1. Grab data from the terminal form
            name = request.form.get('name')
            house_points = int(request.form.get('house_points', 0))
            event_date = request.form.get('event_date')
            event_time = request.form.get('event_time')
            image_file = request.files.get('image')

            # 2. Handle optional image upload
            filename = None
            if image_file and image_file.filename != '':
                filename = secure_filename(image_file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image_file.save(file_path)

            # 3. Inject into the Event databank
            conn = get_db_connection()
            conn.execute('''
                INSERT INTO Event (name, house_points, event_date, event_time, image) 
                VALUES (?, ?, ?, ?, ?)
            ''', (name, house_points, event_date, event_time, filename))
            conn.commit()
            conn.close()

            # 4. Route back to the feed to see the new tile
            return redirect(url_for('calendar'))

        # If it's a GET request, just show the form
        return render_template('upload.html.jinja')
    
    @app.route('/interested/<int:event_id>', methods=['POST'])
    def mark_interested(event_id):
        # 1. Check if the user is actually logged in
        if 'user_id' not in session:
            # If not logged in, you could redirect to a login page. 
            # For now, we'll just send them back to the calendar.
            return redirect(url_for('calendar'))
        
        user_id = session['user_id']
        
        # 2. Connect to the databanks
        conn = get_db_connection()
        
        # 3. Log the interaction into Selected_Event
        # NOTE: We are inserting the user_id into your 'password' column based on your schema!
        conn.execute('''
            INSERT INTO Selected_Event (event_id, password)
            VALUES (?, ?)
        ''', (event_id, str(user_id)))
        
        conn.commit()
        conn.close()
        
        # 4. Refresh the terminal feed
        return redirect(url_for('calendar'))

    @app.route('/signup', methods=['POST'])
    def signup():
        # 1. Grab data from the HTML form
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        image_file = request.files.get('profile_image')

        # Basic validation
        if not (name and email and password and image_file):
            return "Missing required fields.", 400

        # 2. Secure the filename and save the uploaded image
        filename = secure_filename(image_file.filename)
        if filename:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(file_path)
        else:
            return "Invalid file.", 400

        # 3. Hash the password
        hashed_password = generate_password_hash(password)

        # 4. Save to the database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO User (name, email, password, profile_image) VALUES (?, ?, ?, ?)',
                (name, email, hashed_password, filename)
            )
            conn.commit()
            
            # 5. Save the new user to the session cookie
            session['user_id'] = cursor.lastrowid
            session['user_name'] = name
            
            conn.close()
            
            # 6. Redirect to the profile page
            return redirect(url_for('profile'))
        
        except sqlite3.IntegrityError:
            return "An account with that email already exists.", 400
        except Exception as e:
            return f"An error occurred: {e}", 500

    @app.route('/signin', methods=['POST'])
    def signin():
        # 1. Grab data from the HTML form
        email = request.form.get('email')
        password = request.form.get('password')

        if not (email and password):
            return "Missing required fields.", 400

        # 2. Look up the user in the database
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM User WHERE email = ?', (email,)).fetchone()
        conn.close()

        # 3. Verify the user exists AND the password matches the hash
        if user and check_password_hash(user['password'], password):
            
            # 4. Save the user to the session cookie
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            
            # 5. Redirect to the profile page
            return redirect(url_for('profile'))
        else:
            return render_template('signinsignup.html.jinja', error="[AUTHORIZATION FAILED: INVALID CREDENTIALS]")

    # --- NEW ROUTE TO CLEAR THE COOKIE ---
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('profile'))

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)