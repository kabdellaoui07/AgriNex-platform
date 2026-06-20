from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory
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

# Secret key for encrypting sessions (essential for login security)
app.secret_key = 'agrocyber_secret_glass_key_2026'

# Secure cookie configuration
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ─────────────────────────────────────────────────────────────────────────
#  DATABASE & UPLOADS CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────
# Support custom upload directory for cloud platforms (e.g. persistent volume /data)
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db_url = os.environ.get('DATABASE_URL')
if db_url:
    # Standardize postgres:// to postgresql+psycopg:// for SQLAlchemy compatibility
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

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
    role          = db.Column(db.String(20), nullable=False) # 'admin' or 'collector'

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
    # حقل الوقت يستقبل التوقيت التلقائي كملاذ أخير إذا لم يرسله الموبايل
    timestamp       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes           = db.Column(db.Text)

    def to_dict(self):
        conf_val = self.confidence or 0.0
        return {
            'id': self.id,
            'image_path': self.image_path,
            'predicted_class': self.predicted_class,
            'confidence': round(conf_val * 100, 1) if conf_val <= 1.0 else round(conf_val, 1),
            'latitude': self.latitude,
            'longitude': self.longitude,
            'timestamp': self.timestamp.strftime('%d/%m/%Y %H:%M') if self.timestamp else '—',
            'notes': self.notes
        }

class Survey(db.Model):
    __tablename__ = 'Survey'
    
    fid       = db.Column(db.BigInteger, primary_key=True)
    geom      = db.Column(db.LargeBinary, nullable=True)
    latitude  = db.Column(db.Float)
    longitude = db.Column(db.Float)
    Date      = db.Column(db.DateTime)
    classe    = db.Column(db.String(100))
    Photo     = db.Column(db.String(255))

    def to_dict(self):
        return {
            'id': self.fid,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'class_label': self.classe,
            'image_name': os.path.basename(self.Photo) if self.Photo else None,
            'acquisition_date': self.Date.strftime('%Y-%m-%d') if self.Date else None,
            'source': 'Mergin Map / QGIS'
        }

# ─────────────────────────────────────────────────────────────────────────
#  DATABASE INITIALIZATION & SEEDING (Executed on startup)
# ─────────────────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        # Create all tables safely (users, predictions, Survey)
        db.create_all()

        # Seed default users if users table is empty
        if User.query.count() == 0:
            admin_user = User(
                username="admin",
                role="admin"
            )
            admin_user.set_password("admin")

            collector_user = User(
                username="collector",
                role="collector"
            )
            collector_user.set_password("admin")

            db.session.add(admin_user)
            db.session.add(collector_user)
            db.session.commit()
            print("Default users created successfully.")

# Run database initialization automatically at startup
init_db()

# ─────────────────────────────────────────────────────────────────────────
#  🎯 GLOBAL ROUTE GUARD & ROLE SECURITY
# ─────────────────────────────────────────────────────────────────────────
@app.before_request
def require_login():
    allowed_routes = ['login', 'static']
    if request.endpoint not in allowed_routes and not session.get('logged_in'):
        return redirect(url_for('login'))

# 🔒 دالة التحقق البرمجية لمنع الـ Collector وحماية لوحات التحكم الإدارية للأدمن
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
#  ROUTES: AUTHENTICATION (Login / Logout)
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

# ─────────────────────────────────────────────────────────────────────────
#  ROUTES: APPLICATION
# ─────────────────────────────────────────────────────────────────────────
@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    file = request.files['image']
    lat  = request.form.get('latitude',  type=float)
    lon  = request.form.get('longitude', type=float)
    notes = request.form.get('notes', '')
    
    # 🕒 استقبال الوقت الفعلي لالتقاط العينة من الهاتف وتحويل صيغته
    captured_at_str = request.form.get('captured_at')
    if captured_at_str:
        try:
            # تحويل صيغة ISO القادمة من المتصفح إلى كائن دات تايم متوافق مع البايثون
            timestamp_val = datetime.fromisoformat(captured_at_str.replace('Z', '+00:00'))
        except ValueError:
            timestamp_val = datetime.now(timezone.utc)
    else:
        timestamp_val = datetime.now(timezone.utc)

    filename  = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)
    
    predicted_class, confidence, img_base64 = predict_image(save_path)

    # إدخال البيانات المحدثة مع التوقيت الجغرافي الحقيقي الموثق
    pred = Prediction(
        image_path=filename,
        predicted_class=predicted_class,
        confidence=confidence,
        latitude=lat,
        longitude=lon,
        timestamp=timestamp_val, # التوقيت الفعلي الدقيق للعمل الميداني
        notes=notes
    )
    db.session.add(pred)
    db.session.commit()

    response_data = pred.to_dict()
    response_data['image_base64'] = img_base64

    return jsonify({'success': True, 'prediction': response_data})

@app.route('/results')
@admin_required  # 🔒 متاح للـ Admin فقط
def results():
    try:
        raw_predictions = Prediction.query.order_by(Prediction.timestamp.desc()).all()
        predictions_serialized = [p.to_dict() for p in raw_predictions]
    except Exception as e:
        print("Error fetching predictions for history:", e)
        predictions_serialized = []
    return render_template('results.html', predictions=predictions_serialized)

@app.route('/map')
@admin_required  # 🔒 متاح للـ Admin فقط
def map_view():
    try:
        predictions = Prediction.query.all()
        preds_serialized = [p.to_dict() for p in predictions]
    except Exception as e:
        print("Error fetching predictions for map:", e)
        preds_serialized = []

    try:
        survey_points = Survey.query.all()
        training = [s.to_dict() for s in survey_points]
    except Exception as e:
        print("Survey table not available:", e)
        training = []

    return render_template(
        'map.html',
        predictions=json.dumps(preds_serialized),
        training_points=json.dumps(training)
    )

@app.route('/statistics')
@admin_required  # 🔒 متاح للـ Admin فقط
def statistics():
    from sqlalchemy import func
    
    total = 0
    by_class_serialized = []
    dashboard_stats = {}
    recent_serialized = []
    survey_count = 0
    survey_by_class = []

    try:
        total = Prediction.query.count()
        by_class = db.session.query(
            Prediction.predicted_class,
            func.count(Prediction.id).label('count'),
            func.avg(Prediction.confidence).label('avg_conf')
        ).group_by(Prediction.predicted_class).all()

        for row in by_class:
            calculated_conf = row.avg_conf if row.avg_conf > 1.0 else (row.avg_conf or 0) * 100
            
            by_class_serialized.append({
                'predicted_class': row.predicted_class,
                'count': row.count,
                'avg_conf': round(calculated_conf / 100, 4)
            })
            dashboard_stats[row.predicted_class] = {
                'count': row.count,
                'avg_conf': round(calculated_conf, 1)
            }

        raw_recent = Prediction.query.order_by(Prediction.timestamp.desc()).limit(10).all()
        recent_serialized = [p.to_dict() for p in raw_recent]
    except Exception as e:
        print("Error fetching prediction statistics:", e)

    try:
        survey_count = Survey.query.count()
        survey_by_class = db.session.query(
            Survey.classe,
            func.count(Survey.fid).label('count')
        ).group_by(Survey.classe).all()
    except Exception as e:
        print("Error fetching survey statistics:", e)

    return render_template('statistics.html',
        total=total,
        by_class=by_class_serialized,
        dashboard_stats=json.dumps(dashboard_stats),
        recent=recent_serialized,
        train_count=survey_count,
        train_by_class=survey_by_class
    )

@app.route('/api/sampling-data')
@admin_required
def get_sampling_data():
    try:
        training = [s.to_dict() for s in Survey.query.all()]
    except Exception:
        training = []
        
    try:
        new_data = [p.to_dict() for p in Prediction.query.all()]
    except Exception:
        new_data = []
    
    return jsonify({
        'training_data': training,
        'new_data': new_data
    })

@app.route('/sampling')
@admin_required  # لضمان حماية الصفحة
def sampling():
    return render_template('sampling.html')

# ─────────────────────────────────────────────────────────────────────────
#  API JSON ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────
@app.route('/api/predictions')
@admin_required  # 🔒 متاح للـ Admin فقط
def api_predictions():
    try:
        preds = Prediction.query.order_by(Prediction.timestamp.desc()).all()
        return jsonify([p.to_dict() for p in preds])
    except Exception:
        return jsonify([])

@app.route('/api/training_points')
@admin_required  # 🔒 متاح للـ Admin فقط
def api_training_points():
    try:
        points = Survey.query.all()
        return jsonify([t.to_dict() for t in points])
    except Exception:
        return jsonify([])

@app.route('/api/import_training', methods=['POST'])
@admin_required  # 🔒 متاح للـ Admin فقط
def import_training():
    data = request.get_json()
    count = 0
    for row in data.get('features', []):
        props = row.get('properties', {})
        coords = row.get('geometry', {}).get('coordinates', [None, None])
        sv = Survey(
            longitude=coords[0],
            latitude=coords[1],
            classe=props.get('class_label'),
            Photo=props.get('image_name'),
            Date=datetime.strptime(props['date'], '%Y-%m-%d') if props.get('date') else None
        )
        db.session.add(sv)
        count += 1
    db.session.commit()
    return jsonify({'imported': count})

# Serve uploads from custom directory if defined outside of static
@app.route('/static/uploads/<path:filename>')
def custom_uploads(filename):
    # This route only gets called if Flask's static handler doesn't catch it
    # or if UPLOAD_FOLDER is located outside the static directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─────────────────────────────────────────────────────────────────────────
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )