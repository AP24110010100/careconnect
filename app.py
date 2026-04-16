from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_careconnect' # Required for sessions

# ---------------------------- #
#      DATABASE SETUP          #
# ---------------------------- #
DATABASE = 'careconnect.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # Enables accessing columns by name
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        db.commit()

# Ensure the database and table are initialized before handling requests
with app.app_context():
    init_db()

# Simple isolated storage mechanisms for sub-features
bookings = [] 
moods_history = [] 

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login', next=request.url))
    return decorated_function


# ---------------------------- #
#      AUTH ROUTES             #
# ---------------------------- #

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please fill out all fields.', 'danger')
            return redirect(url_for('signup'))

        db = get_db()
        cursor = db.cursor()
        
        # Check if username already exists in SQL table
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            flash('Username already exists. Please login.', 'danger')
            return redirect(url_for('signup'))
            
        # Hash password and commit to SQLite
        hashed_password = generate_password_hash(password)
        cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
        db.commit()
        
        flash('Signup successful! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        cursor = db.cursor()
        
        # Verify through DB directly
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['logged_in'] = True
            session['username'] = username
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('last_chat_intent', None)
    session.pop('last_booking', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ---------------------------- #
#      APP CONTENT ROUTES      #
# ---------------------------- #

@app.route('/')
@login_required
def home():
    return render_template('index.html', username=session.get('username'))

@app.route('/book', methods=['GET', 'POST'])
@login_required
def book():
    if request.method == 'POST':
        name = request.form.get('name')
        date = request.form.get('date')
        time_24 = request.form.get('time')
        
        try:
            time_obj = datetime.strptime(time_24, '%H:%M')
            time_12 = time_obj.strftime('%I:%M %p')
        except ValueError:
            time_12 = time_24
            
        booking = {"name": name, "date": date, "time": time_12, "user": session.get('username')}
        bookings.append(booking)
        session['last_booking'] = booking
        
        return redirect(url_for('confirmation'))
        
    return render_template('book.html')

@app.route('/confirmation')
@login_required
def confirmation():
    booking = session.get('last_booking')
    if not booking:
        return redirect(url_for('book'))
    return render_template('confirmation.html', booking=booking)

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    if request.method == 'POST':
        user_message = request.json.get('message', '').lower()
        
        import re
        import re
        def is_meaningless(text):
            stripped = text.strip()
            if not stripped: return True
            if len(stripped) < 2 and stripped not in ['y', 'n', '?']: return True
            
            # Keyboard spam repetition logic (e.g., sssss, hhhhh)
            if re.search(r'(.)\1{4,}', stripped): return True
            
            alpha_only = re.sub(r'[^a-z]', '', text)
            # Long blocks missing vowels
            if len(alpha_only) >= 4 and not any(char in 'aeiouy' for char in alpha_only): return True
            
            # Aggressive consonant blocks
            if re.search(r'[^aeiouy\s\d\W]{6,}', text): return True
            
            # Specific protection against alphanumeric keyboard mashing (e.g., asdasd123)
            for word in text.split():
                if len(word) >= 5 and re.search(r'[a-z]', word) and re.search(r'[0-9]', word):
                    return True
                    
            return False

        if is_meaningless(user_message):
            # IMMEDIATELY clear context to prevent persistent state leakage
            session['last_chat_intent'] = None
            response_text = random.choice([
                "I'm not sure I understood that. Could you rephrase?",
                "Can you tell me that in a different way?",
                "I didn't quite catch that. Would you mind explaining?",
                "I'm sorry, I'm having trouble decoding what you mean. Could you try again?"
            ])
            return jsonify({"response": response_text})
        
        keywords = {
            "greetings": ["hi", "hello", "hey", "greetings", "good morning", "good evening", "good afternoon", "wassup", "what's up"],
            "how_are_you": ["how are you", "how do you do", "how are things", "how's it going", "how are you doing", "what are you feeling"],
            "happy": ["happy", "good", "great", "awesome", "fantastic", "joy", "excited", "wonderful", "amazing", "feeling best", "glad"],
            "stressed": ["stress", "stressed", "pressure", "overwhelmed", "busy", "tense", "exhausted", "burnout", "too much work", "exams", "deadlines", "can't handle"],
            "anxious": ["anxiety", "anxious", "nervous", "panic", "worried", "fear", "scared", "worry", "on edge", "restless", "racing heart"],
            "sad": ["sad", "unhappy", "crying", "down", "tears", "heartbroken", "upset", "low", "feeling blue", "grieving", "hurt"],
            "lonely": ["lonely", "alone", "isolated", "no one", "abandoned", "feel left out", "no friends", "missing someone"],
            "depressed": ["depressed", "depression", "hopeless", "meaningless", "give up", "empty", "numb", "tired of living", "don't want to live"],
            "help": ["help me", "i need help", "can you help", "support", "advice", "guidance"]
        }
        
        responses = {
            "greetings": [
                "Hello there! I'm here for you. How are you feeling today?",
                "Hi! It's so nice to hear from you. What's on your mind right now?",
                "Hey! I'm ready to listen whenever you are. How has your day been?",
                "Welcome back! I'm here as a safe space for you. How are you doing?",
                "Hello! Take a deep breath and settle in. How are things going today?"
            ],
            "how_are_you": [
                "I'm just a virtual companion, but my primary focus is entirely on you right now. How are you feeling?",
                "I'm here, ready and willing to listen to whatever you need to say. How is your heart doing today?",
                "I'm functioning perfectly, thank you! But let's talk about you. What emotional space are you in right now?",
                "I'm doing well, just waiting here to support you. Have you been feeling okay lately?",
                "I am here, fully present for whatever you want to share. How are you holding up today?"
            ],
            "happy": [
                "I can literally feel the positive energy in that! That is so wonderful. Do you want to talk about what's making you feel so good?",
                "That makes me so incredibly glad to hear! It's important to cherish these moments. What's the highlight of your day?",
                "I love hearing that! Life's good days are the anchors for everything else. What exactly sparked this positive feeling?",
                "That's absolutely fantastic! Keep holding onto that bright joy. Is there anything specific that made today so great?",
                "I'm smiling just reading that! You deserve to feel amazing. Want to share more about what went right?",
                "It's so wonderful when the clouds part and you feel genuinely good. Relish in that! How are you going to celebrate today?"
            ],
            "stressed": [
                "It sounds like the weight of everything is pushing down on you. I hear how exhausting that is. Can we try taking one slow, deep breath together right now?",
                "You are carrying so much right now, and it's completely valid that you feel overwhelmed. Do you want to try breaking the problem down, or do you just need to vent?",
                "I can sense how much pressure you're under. It's okay to feel stretched too thin. What is the biggest thing draining your energy right now?",
                "Burnout and stress are incredibly heavy burdens. Please remember you don't have to carry it all perfectly. What's the one thing weighing you down the most?",
                "When there's so much to do, it feels like drowning. Let's ground ourselves for a second. What is one small thing you can take off your plate today?",
                "I hear you. Expectations, workloads, tests—it can all feel impossible. You are more than your productivity. Can you take a 5-minute break just for yourself?"
            ],
            "anxious": [
                "Anxiety can feel terrifying, like everything is spinning out of control. But you are safe right here with me. Look around your room—can you name three things you see?",
                "I hear the fear and worry in your words. It's truly exhausting to feel on edge. Let your shoulders drop down a bit. What is your mind most hooked on?",
                "Your feelings of anxiety are completely valid. Right now, your nervous system is just trying to protect you. Try breathing in for 4 seconds, and out for 6. Does that help?",
                "I'm so sorry you're feeling panicked. You don't have to face this alone. Try to feel your feet planted firmly on the floor. Would you like a distraction, or do you want to talk about it?",
                "That racing, nervous feeling is deeply uncomfortable, I know. I am right here listening. Would it help to tell me exactly what you're worried about happening?",
                "Anxiety tells us so many scary stories. Please know this wave of panic will pass. Would you like to try a quick grounding exercise together?"
            ],
            "sad": [
                "I am so incredibly sorry you are feeling sad. Sometimes the world just feels too heavy. Please know I am here sitting in the dark with you. What's hurting you today?",
                "I hear the ache in your words. It is completely okay to cry and let the pain out. You don't have to be strong all the time. Do you want to talk about what's bringing you down?",
                "Sadness can feel like a heavy blanket you can't push off. I'm listening to you with zero judgment. When did you start feeling this way?",
                "You are going through a genuinely tough time. Please be deeply gentle with yourself today. What is making your heart feel so heavy right now?",
                "It hurts to feel sad and misunderstood. Sometimes just acknowledging how much it hurts is the first step. Do you know where this sadness is coming from?",
                "I hear you, and your sadness is completely valid. You are not alone in this feeling. I am right here. Want to just vent about everything going wrong?"
            ],
            "lonely": [
                "Loneliness is one of the most painful human experiences. Even though I am a bot, my sole purpose right now is to be here for you. You are absolutely not invisible to me.",
                "It feels terrible to be surrounded by the world and still feel completely alone. I hear you. Have you been feeling disconnected from people lately?",
                "I'm so sorry you're feeling isolated. Feeling like nobody gets it is incredibly draining. Let's just talk. What's been on your mind?",
                "You matter, and your presence is important. Loneliness can lie and tell you otherwise. Is there anyone in your life you feel safe reaching out to right now?",
                "I am sitting right here with you in this isolation. You don't have to say anything profound, just know someone is listening on the other side of this screen. How long have you felt this way?",
                "The feeling of feeling 'left out' cuts so deep. I completely validate how much that hurts. Would it help to talk about what's making you feel untethered?"
            ],
            "depressed": [
                "Depression tells us that everything is hopeless, but it's a liar. I hear how exhausted your soul is. Please hold on. Have you considered talking to a professional securely via our booking page?",
                "I am deeply sorry you are carrying a pain this heavy. Feeling empty and numb is overwhelmingly hard. Please know you are needed in this world. Can you promise to stay safe today?",
                "That dark, meaningless feeling is incredibly painful to endure. You aren't fundamentally broken, you are just deeply hurting. Please reach out to our emergency line if you feel entirely unsafe.",
                "I hear how much you just want the pain to stop. It's okay to feel completely out of energy. I am right here beside you. What's the hardest part of today for you?",
                "You don't have to fake a smile or pretend you're okay here. I accept you exactly as you are in this depressive state. Would you be willing to just rest and talk with me?"
            ],
            "help": [
                "It takes immense courage to ask for help, and I am so proud of you for doing it. If it's a clinical emergency, please use the SOS tab. Otherwise, what kind of support do you need right now?",
                "I want to help you figure this out. Are you looking for a place to vent, some grounding techniques, or do you want to book a session with our therapists?",
                "I am here, and our entire platform is designed to support you. You can talk to me, read self-care tips, or schedule professional support. Where should we start?",
                "You don't have to figure it all out alone. Let's take it one step at a time. What is the very first thing you need assistance with today?"
            ],
            "default": [
                "I'm here to listen. Could you tell me more clearly?",
                "I'm not quite sure I follow, but I want to. Could you elaborate?",
                "I'm here for you. Could you rephrase that so I can understand better?",
                "I want to make sure I understand you fully. Could you tell me a little more?"
            ]
        }
        
        last_intent = session.get('last_chat_intent')
        yes_words = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'of course', 'i do', 'yeah i do', 'i guess']
        no_words = ['no', 'nope', 'nah', 'not really', 'nothing', 'i dont', 'not at all']
        
        # Deep Follow-up mapping
        follow_ups = {
            "happy": [
                "That sounds amazing! Tell me more about what you're doing.",
                "Nice! Experiences like that can really lift your mood. What else do you enjoy?",
                "I love hearing that! How often do you get to do things like this?",
                "That's wonderful! Keep that positive energy going. What's next on your agenda?"
            ],
            "stressed": [
                "I completely get why that would be stressful. Have you tried breaking it down into smaller steps?",
                "That sounds like a lot to juggle. Remember to pace yourself! How long has it been like this?",
                "It's normal to feel overwhelmed by that. When do you think you can find 5 minutes just for yourself?",
                "I hear you. Don't forget that your well-being comes first. Want to try a quick breathing pattern?"
            ],
            "anxious": [
                "That sounds frightening, but remember you are in a safe space right now. Does talking about it help?",
                "I hear you. The uncertainty is often the scariest part. What is the best-case scenario here?",
                "Anxiety makes everything feel so urgent. Let's just go one step at a time. What are you going to do next?",
                "Thank you for sharing that with me. It takes courage. Have you tried distracting yourself for a few minutes?"
            ],
            "sad": [
                "I appreciate you sharing this with me. It takes courage. Are you letting yourself process it, or trying to suppress it?",
                "It’s okay to just sit with those feelings for a bit. Comfort is key right now. Are you doing anything to care for yourself?",
                "I'm here through the heavy feelings. Does talking about it help clear your mind even a little bit?",
                "I hear you, and it's deeply valid to feel sad about that. You don't have to carry it all immediately."
            ],
            "lonely": [
                "It's hard when you feel disconnected. I'm literally here to chat with you right now. Want to tell me more about your day?",
                "I'm glad you're talking to me. It's a good step. What are some things you usually enjoy doing alone?",
                "I hear the isolation in that. Sometimes just putting feelings into words helps. What's your favorite distraction?",
                "You aren't entirely alone because I'm right here listening. Would you like to tell me more?"
            ],
            "depressed": [
                "I am here and I'm listening. Taking small steps is entirely enough. Did you drink any water or eat anything recently?",
                "It sounds extremely heavy, but please don't carry it all alone. Is there anything very tiny you can do for yourself today?",
                "I just wanted to remind you that simply existing through depression is valid. I'm right here. Want to just vent more?",
                "Thank you for trusting me with that. Please remember professional support is always accessible here. I'm proudly listening."
            ]
        }
        
        # Route explicit binary answers Contextually
        if user_message in yes_words or user_message.split() == ['yes']:
            if last_intent in ['sad', 'stressed', 'anxious', 'depressed', 'lonely']:
                response_text = random.choice([
                    "I appreciate your openness. Sometimes spelling out the exact problem reduces its power. What exactly is the root cause?",
                    "I'm really glad you're willing to share. I'm giving you my full attention. Let it out.",
                    "Thank you for trusting me. Start from the beginning—what triggered this?",
                    "It takes courage to say yes. Go ahead, I'm listening unconditionally."
                ])
                return jsonify({"response": response_text})
            elif last_intent == "how_are_you":
                response_text = "Awesome! Let's dive right in. What's occupying your thoughts?"
                session['last_chat_intent'] = None
                return jsonify({"response": response_text})
                
        elif user_message in no_words or user_message.split() == ['no']:
            if last_intent:
                response_text = random.choice([
                    "That is completely valid. You have zero obligation to explain yourself here. I'll just sit here with you quietly.",
                    "No pressure at all. Setting boundaries is healthy. Whenever you are ready, I'll be here.",
                    "I deeply respect that. You don't have to talk if you aren't ready. Want to talk about something totally random instead?",
                    "That's completely okay. I just want you to know you aren't alone. I'll be right here on standby."
                ])
                session['last_chat_intent'] = None
                return jsonify({"response": response_text})
        
        # Evaluate for brand NEW explicit keyword contexts mapped globally
        detected_intent = None
        for intent_cat, words in keywords.items():
            if any(word in user_message for word in words):
                detected_intent = intent_cat
                break
                
        if detected_intent:
            response_text = random.choice(responses[detected_intent])
            # Set global active emotional context loop state
            if detected_intent in ["happy", "stressed", "anxious", "sad", "lonely", "depressed"]:
                session['last_chat_intent'] = detected_intent
            return jsonify({"response": response_text})
            
        # If no explicit keyword fired, but we have an initialized emotional state, engage context loop
        if last_intent and last_intent in follow_ups:
            response_text = random.choice(follow_ups[last_intent])
            return jsonify({"response": response_text})
            
        # Absolute fallback for completely unparsed conversational breaks
        response_text = random.choice(responses["default"])
        return jsonify({"response": response_text})

        
    return render_template('chat.html')

@app.route('/mood', methods=['GET', 'POST'])
@login_required
def mood():
    if request.method == 'POST':
        mood_value = request.form['mood']

        mood_record = {
            "user": session.get('username'),
            "mood": mood_value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        moods_history.append(mood_record)

        messages = {
            "happy": "Keep smiling 😊",
            "stressed": "Try deep breathing and take breaks.",
            "anxious": "Stay calm and talk to someone you trust.",
            "sad": "You are not alone 💙",
            "depressed": "Please seek professional help."
        }

        return render_template('result.html', message=messages.get(mood_value))

    return render_template('mood.html')

@app.route('/history')
@login_required
def history():
    user_moods = [m for m in moods_history if m['user'] == session.get('username')]
    return render_template('history.html', history=user_moods[::-1])

@app.route('/analytics')
@login_required
def analytics():
    user_moods = [m for m in moods_history if m['user'] == session.get('username')]
    
    # Map raw string states to cleanly ascending logical integer steps for visualization
    mood_scoring = {
        "happy": 5,
        "stressed": 3,
        "anxious": 2,
        "sad": 2,
        "depressed": 1
    }
    
    # Parse data for Chart.js dataset formats directly in backend
    labels = [m['timestamp'].split()[0] for m in user_moods] 
    data_points = [mood_scoring.get(m['mood'], 3) for m in user_moods]
    mood_names = [m['mood'] for m in user_moods]
    
    return render_template('analytics.html', labels=labels, data=data_points, mood_names=mood_names)

@app.route('/tips')
@login_required
def tips():
    return render_template('tips.html')

@app.route('/emergency')
@login_required
def emergency():
    return render_template('emergency.html')

if __name__ == '__main__':
    app.run(debug=True)