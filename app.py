from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import uuid, io, threading, os, webbrowser, subprocess
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-local-secret-key'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movie_magic.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    bookings = db.relationship('Booking', backref='user', lazy=True)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie = db.Column(db.String(100), nullable=False)
    theater = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    time = db.Column(db.String(20), nullable=False)
    seats = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# ---------- Movie List ----------
MOVIES = [
    {'title': 'RRR', 'price': 190, 'image': 'rrr.jpg'},
    {'title': 'OG', 'price': 220, 'image': 'og.jpg'},
    {'title': 'KUBERA', 'price': 300, 'image': 'kubera.jpg'},
    {'title': 'HIT 3', 'price': 250, 'image': 'hit3.jpg'},
    {'title': 'AMARAN', 'price': 210, 'image': 'amaran.jpg'},
    {'title': 'SITARAMAM', 'price': 180, 'image': 'sitaramam.jpg'},
    {'title': 'COURT', 'price': 160, 'image': 'court.jpg'},
    {'title': 'ELEVEN', 'price': 250, 'image': 'eleven.jpg'},
    {'title': '3', 'price': 200, 'image': '3.jpg'}
]

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
        else:
            user = User(name=name, email=email, password=password)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please log in.')
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_input = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password_input):
            session['email'] = user.email
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('index'))

@app.route('/home')
def home():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', movies=MOVIES)

@app.route('/booking/<title>', methods=['GET', 'POST'])
def booking(title):
    if 'email' not in session:
        return redirect(url_for('login'))

    movie = next((m for m in MOVIES if m['title'].lower() == title.lower()), None)
    if not movie:
        flash("Movie not found")
        return redirect(url_for('home'))

    if request.method == 'POST':
        selected = request.form['show_time']
        selected_theater, show_time = selected.split('|')
        session['theater'] = selected_theater.strip()
        session['show_time'] = show_time.strip()
        return redirect(url_for('seating', title=title))

    return render_template('booking.html', movie=movie)

@app.route('/seating/<title>', methods=['GET', 'POST'])
def seating(title):
    if 'email' not in session:
        return redirect(url_for('login'))

    movie = next((m for m in MOVIES if m['title'].lower() == title.lower()), None)
    if not movie:
        flash("Movie not found")
        return redirect(url_for('home'))

    seat_ids = [f"{r}{n}" for r in "ABCDEFGHIJ" for n in range(1, 21)]

    if request.method == 'POST':
        selected_seats_str = request.form.get('seats')
        selected_seats = selected_seats_str.split(',') if selected_seats_str else []

        if not selected_seats:
            flash("Please select at least one seat.")
            return redirect(url_for('seating', title=title))

        user = User.query.filter_by(email=session['email']).first()
        if not user:
            flash("User not found. Please log in again.")
            return redirect(url_for('login'))

        price_per_seat = movie['price']
        seat_count = len(selected_seats)
        total_price = price_per_seat * seat_count

        booking = Booking(
            booking_id=str(uuid.uuid4()),
            user_id=user.id,
            movie=movie['title'],
            theater=session.get('theater', 'N/A'),
            time=session.get('show_time', 'N/A'),
            seats=','.join(selected_seats),
            price=total_price
        )
        db.session.add(booking)
        db.session.commit()

        return redirect(url_for('payment', booking_id=booking.booking_id))

    return render_template('seating.html', movie=movie, seat_ids=seat_ids)

@app.route('/payment/<booking_id>', methods=['GET', 'POST'])
def payment(booking_id):
    if 'email' not in session:
        return redirect(url_for('login'))

    booking = Booking.query.filter_by(booking_id=booking_id).first()
    movie = next((m for m in MOVIES if m['title'] == booking.movie), None)

    if request.method == 'POST':
        return redirect(url_for('ticket_confirmation', booking_id=booking.booking_id))

    return render_template('payment.html', booking=booking, movie=movie)

@app.route('/tickets')
def ticket_confirmation():
    if 'email' not in session:
        return redirect(url_for('login'))

    booking_id = request.args.get('booking_id')
    if not booking_id:
        flash("No booking ID provided.")
        return redirect(url_for('home'))

    booking = Booking.query.filter_by(booking_id=booking_id).first()
    if not booking:
        flash("Invalid booking.")
        return redirect(url_for('home'))

    movie = next((m for m in MOVIES if m['title'] == booking.movie), None)
    return render_template('tickets.html', movie=movie, booking=booking)

@app.route('/dashboard')
def dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(email=session['email']).first()
    bookings = Booking.query.filter_by(user_id=user.id).order_by(Booking.created_at.desc()).all()
    total_bookings = len(bookings)  # 👈 Counter added
    return render_template('dashboard.html', bookings=bookings, user=user, total_bookings=total_bookings)

@app.route('/clear_history', methods=['POST'])
def clear_history():
    if 'email' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(email=session['email']).first()
    if user:
        Booking.query.filter_by(user_id=user.id).delete()
        db.session.commit()
        flash('Booking history cleared.')

    return redirect(url_for('dashboard'))

@app.route('/download_ticket/<booking_id>')
def download_ticket(booking_id):
    booking = Booking.query.filter_by(booking_id=booking_id).first()
    if not booking:
        return "Booking not found", 404

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, 750, "\U0001F39F Booking Confirmation - Movie Ticket")

    p.setFont("Helvetica", 12)
    p.drawString(100, 720, f"Booking ID: {booking.booking_id}")
    p.drawString(100, 700, f"Movie: {booking.movie}")
    p.drawString(100, 680, f"Theater: {booking.theater}")
    p.drawString(100, 660, f"Show Time: {booking.time}")
    p.drawString(100, 640, f"Seats: {booking.seats}")
    p.drawString(100, 620, f"Total Price: ₹{booking.price}")
    p.drawString(100, 590, "Thank you for booking with MovieMagic!")

    p.showPage()
    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name='ticket.pdf', mimetype='application/pdf')
# -------------- Auto-launch Chrome --------------
# Auto-open in browser
def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")

if __name__ == '__main__':
    threading.Timer(1.5, open_browser).start()
    app.run(debug=True)