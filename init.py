from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime

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
    """Ensures directories and the User table exist before the app runs."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS User (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profile_image TEXT NOT NULL
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
        # The Jinja template can now check if session['user_name'] exists 
        # to decide whether to show the forms or a "Welcome [Name]" message.
        return render_template('signinsignup.html.jinja')

    @app.route('/calendar')
    def calendar():
        return render_template('calendar.html.jinja')

    # Placeholder routes for your navbar to prevent 500 errors
    @app.route('/home')
    def home():
        return "Home Page Coming Soon!"

    @app.route('/events')
    def events():
        return "Events Page Coming Soon!"

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
            return "Invalid email or password.", 401

    # --- NEW ROUTE TO CLEAR THE COOKIE ---
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('profile'))

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)