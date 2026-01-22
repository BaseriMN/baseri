from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np
import io
import uuid
import re

# Import extensions
from extensions import db, bcrypt

app = Flask(__name__)

# PostgreSQL Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123456@localhost:1234/postgres'
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'csv', 'xlsx', 'xls'}

# Initialize extensions dengan app
db.init_app(app)
bcrypt.init_app(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Import models SETELAH db di-initialize
from models import User, TransaksiEod, TransaksiEmerchant, UploadHistory

# Create tables
with app.app_context():
    db.create_all()
    
    # Create admin user jika belum wujud
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@recon.com',
            role='admin',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created: admin / admin123")

# Helper Functions
def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# ==================== ROUTES ====================

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page"""
    # Jika user sudah login, redirect ke dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validation
        errors = []
        
        if not username:
            errors.append('Username diperlukan')
        elif len(username) < 3:
            errors.append('Username perlu sekurang-kurangnya 3 karakter')
        
        if not email:
            errors.append('Email diperlukan')
        elif not validate_email(email):
            errors.append('Format email tidak sah')
        
        if not password:
            errors.append('Password diperlukan')
        elif len(password) < 6:
            errors.append('Password perlu sekurang-kurangnya 6 karakter')
        
        if password != confirm_password:
            errors.append('Password tidak sama')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html', 
                                username=username, 
                                email=email)
        
        # Check if user/email already exists
        with app.app_context():
            existing_user = User.query.filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                if existing_user.username == username:
                    flash('Username sudah digunakan', 'danger')
                else:
                    flash('Email sudah digunakan', 'danger')
                return render_template('register.html', 
                                    username=username, 
                                    email=email)
            
            # Create new user
            try:
                new_user = User(
                    username=username,
                    email=email,
                    role='user',
                    is_active=True
                )
                new_user.set_password(password)
                
                db.session.add(new_user)
                db.session.commit()
                
                flash('Pendaftaran berjaya! Sila login.', 'success')
                return redirect(url_for('login'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error semasa pendaftaran: {str(e)}', 'danger')
                return render_template('register.html', 
                                    username=username, 
                                    email=email)
    
    # GET request - show registration form
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    # Jika user sudah login, redirect ke dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        # Validation
        if not username or not password:
            flash('Sila masukkan username dan password', 'warning')
            return render_template('login.html')
        
        # Find user
        with app.app_context():
            user = User.query.filter_by(username=username).first()
            
            if user:
                # Check password
                if user.check_password(password):
                    if user.is_active:
                        # Set session
                        session['user_id'] = user.id
                        session['username'] = user.username
                        session['role'] = user.role
                        
                        # Set session permanen jika remember checked
                        if remember:
                            session.permanent = True
                            app.permanent_session_lifetime = timedelta(days=7)
                        
                        flash(f'Selamat datang, {user.username}!', 'success')
                        
                        # Redirect berdasarkan role
                        if user.role == 'admin':
                            return redirect(url_for('admin_dashboard'))
                        else:
                            return redirect(url_for('dashboard'))
                    else:
                        flash('Akaun anda tidak aktif. Hubungi administrator.', 'warning')
                else:
                    flash('Password salah', 'danger')
            else:
                flash('Username tidak wujud', 'danger')
            
            return render_template('login.html', username=username)
    
    # GET request - show login form
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    """Main user dashboard"""
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    with app.app_context():
        user = User.query.get(session['user_id'])
        
        # Get statistics
        total_eod = TransaksiEod.query.filter_by(uploaded_by=user.id).count()
        total_emerchant = TransaksiEmerchant.query.filter_by(uploaded_by=user.id).count()
        
        # Recent uploads
        recent_uploads = UploadHistory.query.filter_by(user_id=user.id)\
            .order_by(UploadHistory.upload_date.desc())\
            .limit(5)\
            .all()
        
        # Recent transactions
        recent_eod = TransaksiEod.query.filter_by(uploaded_by=user.id)\
            .order_by(TransaksiEod.created_at.desc())\
            .limit(5)\
            .all()
    
    return render_template('dashboard.html',
                    user=user,
                    total_eod=total_eod,
                    total_emerchant=total_emerchant,
                    recent_uploads=recent_uploads,
                    recent_eod=recent_eod)

@app.route('/admin/dashboard')
def admin_dashboard():
    """Admin dashboard"""
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Akses ditolak. Admin sahaja.', 'danger')
        return redirect(url_for('login'))
    
    with app.app_context():
        # Admin statistics
        total_users = User.query.count()
        total_eod = TransaksiEod.query.count()
        total_emerchant = TransaksiEmerchant.query.count()
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    return render_template('admin_dashboard.html',
                        total_users=total_users,
                        total_eod=total_eod,
                        total_emerchant=total_emerchant,
                        recent_users=recent_users)

@app.route('/upload/eod', methods=['GET'])
def upload_eod_page():
    """EOD upload page"""
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    return render_template('upload_eod.html')


@app.route('/upload/emerchant', methods=['GET'])
def upload_emerchant_page():
    """E-Merchant upload page"""
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    return render_template('upload_emerchant.html')

@app.route('/api/upload/emerchant', methods=['POST'])
def upload_emerchant_api():
    """API endpoint for E-Merchant upload"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    # Implementation similar to previous upload function
    # ... (add your upload logic here)
    
    return jsonify({'success': True, 'message': 'Upload successful'})

@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash('Anda telah logout', 'info')
    return redirect(url_for('login'))

# ==================== TEMPLATE ROUTES ====================

@app.route('/templates/<template_name>')
def serve_template(template_name):
    """Serve template files for debugging"""
    try:
        return render_template(template_name)
    except:
        return f"Template '{template_name}' not found", 404

# ==================== ERROR HANDLERS ====================

# Add these routes to your app.py

from datetime import datetime, timedelta
from sqlalchemy import and_, or_

@app.route('/reconcile')
def reconcile_page():
    """Reconciliation page"""
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    # Calculate date defaults
    today = datetime.now().date()
    seven_days_ago = today - timedelta(days=7)
    
    return render_template('reconcile.html',
                        today=today,
                        today_minus_7=seven_days_ago)

@app.route('/api/reconcile/stats')
def get_reconcile_stats():
    """Get reconciliation statistics"""
    if 'user_id' not in session:
        return jsonify({}), 401
    
    user_id = session['user_id']
    today = datetime.now().date()
    
    # Get counts
    total_eod = TransaksiEod.query.filter_by(uploaded_by=user_id).count()
    total_emerchant = TransaksiEmerchant.query.filter_by(uploaded_by=user_id).count()
    
    # Count matched transactions (you need to implement this logic)
    matched_count = 0  # This should count from your reconciliation table
    partial_matches = 0
    
    # Count unmatched
    unmatched_eod = total_eod - matched_count
    unmatched_emerchant = total_emerchant - matched_count
    
    # Today's matches
    today_matches = 0  # Implement based on your logic
    
    # Pending reconciliation
    pending_count = unmatched_eod + unmatched_emerchant
    
    return jsonify({
        'total_eod': total_eod,
        'total_emerchant': total_emerchant,
        'matched': matched_count,
        'partial_matches': partial_matches,
        'unmatched_eod': unmatched_eod,
        'unmatched_emerchant': unmatched_emerchant,
        'today_matches': today_matches,
        'pending': pending_count,
        'discrepancies': 0  # Implement discrepancy counting
    })

@app.route('/api/reconcile/run', methods=['POST'])
def run_reconciliation():
    """Run reconciliation process"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        user_id = session['user_id']
        
        # Get parameters
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        merchant_filter = data.get('merchant_filter')
        threshold = data.get('threshold', 95)
        criteria = data.get('criteria', {})
        
        # Get transactions for the date range
        eod_transactions = TransaksiEod.query.filter(
            TransaksiEod.uploaded_by == user_id,
            TransaksiEod.transaction_date >= start_date,
            TransaksiEod.transaction_date <= end_date
        ).all()
        
        emerchant_orders = TransaksiEmerchant.query.filter(
            TransaksiEmerchant.uploaded_by == user_id,
            TransaksiEmerchant.transaction_date >= start_date,
            TransaksiEmerchant.transaction_date <= end_date
        ).all()
        
        # Filter by merchant if specified
        if merchant_filter:
            emerchant_orders = [o for o in emerchant_orders 
                                if o.merchant_code and merchant_filter in o.merchant_code.lower()]
        
        # Match transactions (simplified logic)
        matched = []
        unmatched_eod = []
        unmatched_emerchant = emerchant_orders.copy()
        
        for eod in eod_transactions:
            best_match = None
            best_score = 0
            
            for emerchant in emerchant_orders:
                # Calculate match score
                score = calculate_match_score(eod, emerchant, criteria)
                
                if score >= threshold and score > best_score:
                    best_match = emerchant
                    best_score = score
            
            if best_match:
                matched.append({
                    'eod_id': eod.id,
                    'eod_merchant_id': eod.merchant_id,
                    'eod_amount': float(eod.amount) if eod.amount else 0,
                    'eod_date': eod.transaction_date.strftime('%Y-%m-%d') if eod.transaction_date else None,
                    'eod_terminal_id': eod.terminal_id,
                    'emerchant_id': best_match.id,
                    'emerchant_order_id': best_match.order_id,
                    'emerchant_merchant_code': best_match.merchant_code,
                    'emerchant_amount': float(best_match.amount) if best_match.amount else 0,
                    'emerchant_date': best_match.transaction_date.strftime('%Y-%m-%d') if best_match.transaction_date else None,
                    'confidence': best_score,
                    'status': 'pending'
                })
                
                # Remove from unmatched
                if best_match in unmatched_emerchant:
                    unmatched_emerchant.remove(best_match)
            else:
                unmatched_eod.append({
                    'id': eod.id,
                    'merchant_id': eod.merchant_id,
                    'amount': float(eod.amount) if eod.amount else 0,
                    'transaction_date': eod.transaction_date.strftime('%Y-%m-%d') if eod.transaction_date else None,
                    'terminal_id': eod.terminal_id,
                    'card_number': eod.card_number
                })
        
        # Prepare unmatched emerchant data
        unmatched_emerchant_data = []
        for order in unmatched_emerchant:
            unmatched_emerchant_data.append({
                'id': order.id,
                'order_id': order.order_id,
                'merchant_code': order.merchant_code,
                'amount': float(order.amount) if order.amount else 0,
                'transaction_date': order.transaction_date.strftime('%Y-%m-%d') if order.transaction_date else None,
                'customer_email': order.customer_email,
                'payment_method': order.payment_method
            })
        
        return jsonify({
            'success': True,
            'message': f'Found {len(matched)} matches',
            'data': {
                'matched': matched,
                'unmatchedEod': unmatched_eod,
                'unmatchedEmerchant': unmatched_emerchant_data
            },
            'summary': {
                'total_eod': len(eod_transactions),
                'total_emerchant': len(emerchant_orders),
                'matched': len(matched),
                'unmatched_eod': len(unmatched_eod),
                'unmatched_emerchant': len(unmatched_emerchant)
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'details': 'Error during reconciliation'
        }), 500

def calculate_match_score(eod, emerchant, criteria):
    """Calculate match score between EOD and E-Merchant transactions"""
    score = 0
    max_score = 100
    
    # Amount match (40 points)
    if criteria.get('matchAmount', True):
        eod_amount = float(eod.amount) if eod.amount else 0
        emerchant_amount = float(emerchant.amount) if emerchant.amount else 0
        
        if abs(eod_amount - emerchant_amount) <= 0.10:  # Within 10 sen
            score += 40
        elif abs(eod_amount - emerchant_amount) <= 1.00:  # Within RM 1
            score += 20
        elif eod_amount > 0 and emerchant_amount > 0:
            # Partial match based on percentage difference
            diff_percentage = abs(eod_amount - emerchant_amount) / max(eod_amount, emerchant_amount)
            if diff_percentage <= 0.05:  # Within 5%
                score += 30
            elif diff_percentage <= 0.10:  # Within 10%
                score += 15
    
    # Date match (30 points)
    if criteria.get('matchDate', True):
        if eod.transaction_date and emerchant.transaction_date:
            date_diff = abs((eod.transaction_date - emerchant.transaction_date).days)
            if date_diff == 0:
                score += 30
            elif date_diff <= 1:
                score += 20
            elif date_diff <= 3:
                score += 10
    
    # Merchant match (30 points)
    if criteria.get('matchMerchant', False):
        if eod.merchant_id and emerchant.merchant_code:
            # Simple merchant matching logic
            # In reality, you'd have a merchant mapping table
            if str(eod.merchant_id).lower() in str(emerchant.merchant_code).lower() or \
                str(emerchant.merchant_code).lower() in str(eod.merchant_id).lower():
                score += 30
    
    return min(score, max_score)

# Create reconciliation table in models.py
# Add to models.py:
class ReconciliationMatch(db.Model):
    __tablename__ = 'reconciliation_matches'
    
    id = db.Column(db.Integer, primary_key=True)
    eod_transaction_id = db.Column(db.Integer, db.ForeignKey('transaksi_eod.id'))
    emerchant_transaction_id = db.Column(db.Integer, db.ForeignKey('transaksi_emerchant.id'))
    match_score = db.Column(db.Integer)
    match_status = db.Column(db.String(20), default='pending')  # pending, confirmed, rejected
    matched_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    matched_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    
    # Relationships
    eod_transaction = db.relationship('TransaksiEod', backref='matches')
    emerchant_transaction = db.relationship('TransaksiEmerchant', backref='matches')
    matched_user = db.relationship('User', backref='reconciliation_matches')
    
#=====================================RECONCILIATION ENDPOINTS=====================================#


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)