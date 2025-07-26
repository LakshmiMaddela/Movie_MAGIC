from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import boto3, uuid, io, os, threading, webbrowser
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import datetime
from botocore.exceptions import ClientError # Import for better error handling

app = Flask(__name__)
# IMPORTANT: Change this to a strong, random key in production!
# For development, 'your-aws-secret-key' is okay, but never deploy with it.
app.secret_key = 'a_very_secret_and_random_key_that_you_should_change_for_production_!!!!'

# AWS configuration
REGION = 'us-east-1'
USER_TABLE = 'MovieMagicUsers' # Ensure this table exists in DynamoDB with 'email' as the primary key
BOOKING_TABLE = 'MovieMagicBookings' # Ensure this table exists in DynamoDB with 'booking_id' as the primary key
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:604665149129:fixitnow_Topic' # Ensure this SNS topic exists

dynamodb = boto3.resource('dynamodb', region_name=REGION)
sns = boto3.client('sns', region_name=REGION)

tbl_users = dynamodb.Table(USER_TABLE)
tbl_bookings = dynamodb.Table(BOOKING_TABLE)

# Helper function to get user from DynamoDB
def get_user_by_email(email):
    try:
        resp = tbl_users.get_item(Key={'email': email})
        return resp.get('Item')
    except ClientError as e:
        print(f"Error getting user from DynamoDB: {e.response['Error']['Message']}")
        return None
    except Exception as e:
        print(f"Unexpected error getting user: {e}")
        return None

# Helper function to get booking from DynamoDB
def get_booking_by_id(booking_id):
    try:
        resp = tbl_bookings.get_item(Key={'booking_id': booking_id})
        return resp.get('Item')
    except ClientError as e:
        print(f"Error getting booking from DynamoDB: {e.response['Error']['Message']}")
        return None
    except Exception as e:
        print(f"Unexpected error getting booking: {e}")
        return None

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
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        existing_user = get_user_by_email(email)

        if existing_user:
            flash('Email already registered.')
        else:
            try:
                tbl_users.put_item(
                    Item={
                        'email': email,
                        'name': name,
                        'password_hash': hashed_password
                    }
                )
                flash('Registration successful! Please log in.')
                return redirect(url_for('login'))
            except ClientError as e:
                flash(f'Registration failed: {e.response["Error"]["Message"]}')
                print(f"DynamoDB error during registration: {e}")
            except Exception as e:
                flash(f'Registration failed: An unexpected error occurred.')
                print(f"Unexpected error during registration: {e}")

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_input = request.form['password']

        user = get_user_by_email(email)

        if user and check_password_hash(user.get('password_hash', ''), password_input): # Use .get with default for safety
            session['email'] = user['email']
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

        user_email = session.get('email') # Get user email from session
        if not user_email: # Should ideally be caught by @app.route decorator, but good to double check
            flash("User session expired. Please log in again.")
            return redirect(url_for('login'))

        # No need to fetch the full user object here unless you need other user details for the booking item itself
        # For linking, just the email is sufficient.

        price_per_seat = movie['price']
        seat_count = len(selected_seats)
        total_price = price_per_seat * seat_count

        booking_id = str(uuid.uuid4()) # Generate a unique booking ID

        try:
            tbl_bookings.put_item(
                Item={
                    'booking_id': booking_id,
                    'user_email': user_email, # This is the crucial change: link by email
                    'movie': movie['title'],
                    'theater': session.get('theater', 'N/A'),
                    'time': session.get('show_time', 'N/A'),
                    'seats': ','.join(selected_seats),
                    'price': total_price,
                    'created_at': datetime.datetime.now().isoformat() # ISO format for easy sorting
                }
            )
            flash("Booking successful!")
            return redirect(url_for('payment', booking_id=booking_id))
        except ClientError as e:
            flash(f'Booking failed: {e.response["Error"]["Message"]}')
            print(f"DynamoDB error during booking: {e}")
            return redirect(url_for('home'))
        except Exception as e:
            flash(f'Booking failed: An unexpected error occurred.')
            print(f"Unexpected error during booking: {e}")
            return redirect(url_for('home'))

    return render_template('seating.html', movie=movie, seat_ids=seat_ids)

@app.route('/payment/<booking_id>', methods=['GET', 'POST'])
def payment(booking_id):
    if 'email' not in session:
        return redirect(url_for('login'))

    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Booking not found.")
        return redirect(url_for('home'))

    movie = next((m for m in MOVIES if m['title'] == booking.get('movie')), None)

    if request.method == 'POST':
        # In a real app, you'd process payment here (e.g., with Stripe, PayPal).
        # For now, we simulate success and redirect to confirmation.
        flash("Payment successful!")
        return redirect(url_for('ticket_confirmation', booking_id=booking['booking_id']))

    return render_template('payment.html', booking=booking, movie=movie)

@app.route('/tickets')
def ticket_confirmation():
    if 'email' not in session:
        return redirect(url_for('login'))

    booking_id = request.args.get('booking_id')
    if not booking_id:
        flash("No booking ID provided.")
        return redirect(url_for('home'))

    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Invalid booking.")
        return redirect(url_for('home'))

    movie = next((m for m in MOVIES if m['title'] == booking.get('movie')), None)
    return render_template('tickets.html', movie=movie, booking=booking)

@app.route('/dashboard')
def dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))

    user_email = session['email']
    user = get_user_by_email(user_email)

    if not user:
        flash("User not found or session invalid. Please log in again.")
        return redirect(url_for('login'))

    bookings = []
    try:
        # Query the GSI for bookings by user_email
        response = tbl_bookings.query(
            IndexName='UserEmailIndex', # IMPORTANT: This GSI must exist!
            KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(user_email),
            ScanIndexForward=False # Sorts by sort key of GSI (if any) or otherwise by scan order.
                                   # For chronological order, 'created_at' should be the GSI's sort key.
        )
        bookings = response.get('Items', [])

        # If created_at is not a sort key on the GSI, explicitly sort here
        bookings.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    except ClientError as e:
        flash(f"Error fetching bookings: {e.response['Error']['Message']}")
        print(f"DynamoDB error fetching bookings for dashboard: {e}")
    except Exception as e:
        flash(f"Error fetching bookings: An unexpected error occurred.")
        print(f"Unexpected error fetching bookings: {e}")

    total_bookings = len(bookings)
    return render_template('dashboard.html', bookings=bookings, user=user, total_bookings=total_bookings)

@app.route('/clear_history', methods=['POST'])
def clear_history():
    if 'email' not in session:
        return redirect(url_for('login'))

    user_email = session['email']
    try:
        response = tbl_bookings.query(
            IndexName='UserEmailIndex', # IMPORTANT: This GSI must exist!
            KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(user_email)
        )
        items_to_delete = response.get('Items', [])

        if not items_to_delete:
            flash('No booking history to clear.')
            return redirect(url_for('dashboard'))

        # Use batch_writer for efficient deletion of multiple items
        with tbl_bookings.batch_writer() as batch:
            for item in items_to_delete:
                batch.delete_item(
                    Key={
                        'booking_id': item['booking_id'] # Use the primary key of the table
                    }
                )
        flash('Booking history cleared.')
    except ClientError as e:
        flash(f'Error clearing history: {e.response["Error"]["Message"]}')
        print(f"DynamoDB error clearing history: {e}")
    except Exception as e:
        flash(f'Error clearing history: An unexpected error occurred.')
        print(f"Unexpected error clearing history: {e}")

    return redirect(url_for('dashboard'))

@app.route('/download_ticket/<booking_id>')
def download_ticket(booking_id):
    booking = get_booking_by_id(booking_id)
    if not booking:
        return "Booking not found", 404

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, 750, "\U0001F39F Booking Confirmation - Movie Ticket")

    p.setFont("Helvetica", 12)
    p.drawString(100, 720, f"Booking ID: {booking.get('booking_id', 'N/A')}")
    p.drawString(100, 700, f"Movie: {booking.get('movie', 'N/A')}")
    p.drawString(100, 680, f"Theater: {booking.get('theater', 'N/A')}")
    p.drawString(100, 660, f"Show Time: {booking.get('time', 'N/A')}")
    p.drawString(100, 640, f"Seats: {booking.get('seats', 'N/A')}")
    p.drawString(100, 620, f"Total Price: ₹{booking.get('price', 0)}")
    p.drawString(100, 590, "Thank you for booking with MovieMagic!")

    p.showPage()
    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f'ticket_{booking_id}.pdf', mimetype='application/pdf')

# -------------- Auto-launch Chrome --------------
def open_browser():
    # Only open browser if not in a production environment (e.g., EC2)
    # This is useful for local development.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        webbrowser.open("http://127.0.0.1:5000/")

if __name__ == '__main__':
    threading.Timer(1.5, open_browser).start()
    app.run(debug=True, host='0.0.0.0', port=5000)
