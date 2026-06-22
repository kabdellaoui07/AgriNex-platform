from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import NullType
from sqlalchemy.orm import column_property
from sqlalchemy import func
from datetime import datetime, timezone
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os

os.environ['PGCLIENTENCODING'] = 'utf-8'
import numpy as np
from PIL import Image
import tensorflow as tf
import json
import base64
import io

app = Flask(__name__)

# Secret key for encrypting sessions
app.secret_key = 'agrocyber_secret_glass_key_2026'

# Secure cookie configuration
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ─────────────────────────────────────────────────────────────────────────
#  DATABASE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg://postgres:admin@localhost:5432/mygeoaidb'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─────────────────────────────────────────────────────────────────────────
#  MODELS
# ─────────────────────────────────────────────────────────────────────────
class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20), nullable=False) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Prediction(db.Model):
    __tablename__ = 'predictions'
    id              = db.Column(db.Integer, primary_key=True)
    image_path      = db.Column(db.String(255))
    predicted_class = db.Column(db.String(100))
    confidence      = db.Column(db.Float)
    latitude        = db.Column(db.Float)
    longitude       = db.Column(db.Float)
    timestamp       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes           = db.Column(db.Text)

    def to_dict(self):
        return {
            'id': self.id,
            'image_path': self.image_path,
            'predicted_class': self.predicted_class,
            'confidence': round(self.confidence * 100, 1) if self.confidence <= 1.0 else round(self.confidence, 1),
            'latitude': self.latitude,
            'longitude': self.longitude,
            'timestamp': self.timestamp.strftime('%d/%m/%Y %H:%M') if self.timestamp else '—',
            'notes': self.notes
        }

class Survey(db.Model):
    __tablename__ = 'Survey'
    __table_args__ = {'schema': 'public', 'extend_existing': True}
    
    fid            = db.Column(db.BigInteger, primary_key=True)
    geom           = db.Column(NullType)
    Date           = db.Column(db.DateTime)
    classe         = db.Column(db.String(100))
    Photo          = db.Column(db.String(255))
    
    latitude       = column_property(func.ST_Y(geom))
    longitude      = column_property(func.ST_X(geom))

    def to_dict(self):
        return {
            'id': self.fid,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'class_label': self.classe,
            'image_name': os.path.basename(self.Photo) if self.Photo else None,
            'acquisition_date': self.Date.strftime('%Y-%m-%d') if self.Date else None,
            'source': 'Mergin Map / QGIS',
            'notes': ''
        }

# ─────────────────────────────────────────────────────────────────────────
#  🎯 GLOBAL ROUTE GUARD & ROLE SECURITY
# ─────────────────────────────────────────────────────────────────────────
@app.before_request
def require_login():
    allowed_routes = ['login', 'static', 'serve_sw', 'serve_manifest', 'serve_favicon']
    if request.endpoint not in allowed_routes and not session.get('logged_in'):
        return redirect(url_for('login'))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ─────────────────────────────────────────────────────────────────────────
#  MOBILENET MODEL & PRE-PROCESSING VISUALIZER
# ─────────────────────────────────────────────────────────────────────────
CLASS_NAMES = ['cereal', 'potato', 'undefined']
IMG_SIZE    = 224

def load_model():
    model_path = 'model/best_model.h5'
    if os.path.exists(model_path):
        return tf.keras.models.load_model(model_path)
    
    base = tf.keras.applications.MobileNetV2(
        input_shape=(IMG_SIZE, IMG_SIZE, 3),
        include_top=False, weights='imagenet'
    )
    x = tf.keras.layers.GlobalAveragePooling2D()(base.output)
    x = tf.keras.layers.Dense(128, activation='relu')(x)
    out = tf.keras.layers.Dense(len(CLASS_NAMES), activation='softmax')(x)
    return tf.keras.Model(inputs=base.input, outputs=out)

model = None

def get_model():
    global model
    if model is None:
        model = load_model()
    return model

def predict_image(img_path):
    img = Image.open(img_path).convert('RGB')
    img_resized = img.resize((IMG_SIZE, IMG_SIZE))
    
    buffered = io.BytesIO()
    img_resized.save(buffered, format="JPEG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    arr = np.array(img_resized) / 255.0
    arr = np.expand_dims(arr, axis=0)
    preds = get_model().predict(arr)[0]
    idx = int(np.argmax(preds))
    
    return CLASS_NAMES[idx], float(preds[idx]), img_base64

# ─────────────────────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    if request.method == 'POST':
        role = request.form.get('role')
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.role == role:
            session['logged_in'] = True
            session['username'] = user.username
            session['role'] = user.role
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid credentials.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    file = request.files['image']
    lat = request.form.get('latitude', type=float)
    lon = request.form.get('longitude', type=float)
    notes = request.form.get('notes', '')
    captured_at_str = request.form.get('captured_at')
    
    if captured_at_str:
        try:
            timestamp_val = datetime.fromisoformat(captured_at_str.replace('Z', '+00:00'))
        except ValueError:
            timestamp_val = datetime.now(timezone.utc)
    else:
        timestamp_val = datetime.now(timezone.utc)

    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)
    predicted_class, confidence, img_base64 = predict_image(save_path)

    pred = Prediction(image_path=filename, predicted_class=predicted_class, confidence=confidence, 
                      latitude=lat, longitude=lon, timestamp=timestamp_val, notes=notes)
    db.session.add(pred)
    db.session.commit()
    response_data = pred.to_dict()
    response_data['image_base64'] = img_base64
    return jsonify({'success': True, 'prediction': response_data})

@app.route('/results')
@admin_required
def results():
    raw_predictions = Prediction.query.order_by(Prediction.timestamp.desc()).all()
    predictions_serialized = [p.to_dict() for p in raw_predictions]
    return render_template('results.html', predictions=predictions_serialized)

@app.route('/map')
@admin_required
def map_view():
    predictions = Prediction.query.all()
    survey_points = Survey.query.all()
    return render_template('map.html',
        predictions=json.dumps([p.to_dict() for p in predictions]),
        training_points=json.dumps([s.to_dict() for s in survey_points])
    )

@app.route('/statistics')
@admin_required
def statistics():
    total = Prediction.query.count()
    by_class = db.session.query(Prediction.predicted_class, func.count(Prediction.id).label('count'), 
                                func.avg(Prediction.confidence).label('avg_conf')).group_by(Prediction.predicted_class).all()
    by_class_serialized = []
    dashboard_stats = {}
    for row in by_class:
        calculated_conf = row.avg_conf if row.avg_conf > 1.0 else (row.avg_conf or 0) * 100
        by_class_serialized.append({'predicted_class': row.predicted_class, 'count': row.count, 'avg_conf': round(calculated_conf / 100, 4)})
        dashboard_stats[row.predicted_class] = {'count': row.count, 'avg_conf': round(calculated_conf, 1)}
    
    raw_recent = Prediction.query.order_by(Prediction.timestamp.desc()).limit(10).all()
    survey_count = Survey.query.count()
    survey_by_class = db.session.query(Survey.classe, func.count(Survey.fid).label('count')).group_by(Survey.classe).all()
    return render_template('statistics.html', total=total, by_class=by_class_serialized, dashboard_stats=json.dumps(dashboard_stats), 
                           recent=[p.to_dict() for p in raw_recent], train_count=survey_count, train_by_class=survey_by_class)

@app.route('/sampling')
@admin_required
def sampling():
    return render_template('sampling.html')
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # التأكد من أن الحقول ليست فارغة
        if not username or not password:
            return "Username and password are required", 400

        # التحقق مما إذا كان المستخدم موجوداً مسبقاً
        existing = User.query.filter_by(username=username).first()
        if existing:
            return "User already exists", 400

        # إنشاء مستخدم جديد بدور 'collector' دائماً كما طلبت
        new_user = User(
            username=username,
            role="collector"
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        return "Account created successfully! <a href='/login'>Login here</a>"

    return render_template('register.html')

# ─────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        # create admin only if not exists
        if User.query.filter_by(username='admin').first() is None:
            admin_user = User(username='admin', role='admin')
            admin_user.set_password('admin')
            db.session.add(admin_user)

        # create collector only if not exists
        if User.query.filter_by(username='collector').first() is None:
            collector_user = User(username='collector', role='collector')
            collector_user.set_password('admin')
            db.session.add(collector_user)

        db.session.commit()
            
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)