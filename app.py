from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np
import io
import uuid
import re
import glob
from sqlalchemy import text, insert
import logging

# Import extensions
from extensions import db, bcrypt

app = Flask(__name__)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123456@localhost:1234/postgres'
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'csv', 'xlsx', 'xls'}

# Initialize extensions with app
db.init_app(app)
bcrypt.init_app(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import models SETELAH db di-initialize
from models import User, TransaksiEod, TransaksiEmerchant, UploadHistory, ReconciliationMatch



# ==================== PROCESSOR CLASSES ====================

class EODProcessor:
    def __init__(self, db_engine, folder_path=None, file_content=None, filename=None, user_id=None):
        self.engine = db_engine
        self.folder_path = folder_path
        self.file_content = file_content
        self.filename = filename
        self.user_id = user_id
        self.batch_id = f"EOD_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
    def _insert_on_conflict_nothing(self, table, conn, keys, data_iter):
        """Internal helper: Handle Upsert logic."""
        data = [dict(zip(keys, row)) for row in data_iter]
        stmt = insert(table.table).values(data)
        
        # Define unique constraint for EOD
        on_conflict_stmt = stmt.on_conflict_do_nothing(
            index_elements=['tid', 'ref_number', 'date_of_transaction', 'amount_rm']
        )
        conn.execute(on_conflict_stmt)
    
    def process_from_file_content(self):
        """Process EOD from uploaded file content."""
        try:
            print(f"🚀 [EOD] Processing file: {self.filename}")
            
            # Determine file type and read
            if self.filename.endswith('.csv'):
                df = pd.read_csv(io.StringIO(self.file_content.decode('utf-8')), header=None)
            elif self.filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(io.BytesIO(self.file_content), header=None)
            else:
                return {'success': False, 'error': 'Unsupported file format'}
            
            # Clean and process the data
            processed_df = self._clean_eod_data(df)
            
            if processed_df.empty:
                return {'success': False, 'error': 'No valid data found in file'}
            
            # Save to database
            records_saved = self._save_to_database(processed_df)
            
            # Save upload history
            self._save_upload_history(records_saved)
            
            return {
                'success': True,
                'records_processed': len(processed_df),
                'records_saved': records_saved,
                'batch_id': self.batch_id,
                'filename': self.filename,
                'total_amount': float(processed_df['amount_rm'].sum()) if 'amount_rm' in processed_df.columns else 0
            }
            
        except Exception as e:
            logger.error(f"Error processing EOD file: {e}")
            return {'success': False, 'error': str(e)}
    
    def _clean_eod_data(self, df):
        """Clean and process EOD data."""
        try:
            # Logic cari header
            jumpa = []
            for i in range(min(len(df), 50)):  # Limit search to first 50 rows
                row_text = ' '.join(str(x) for x in df.iloc[i].values)
                if 'Terminal Name' in row_text or 'terminal name' in row_text.lower():
                    jumpa.append(i)
            
            if len(jumpa) < 2:
                logger.warning("Header tidak lengkap")
                return pd.DataFrame()
            
            # Set header
            new_header = [str(val).lower().replace(" ", "_").replace("(", "").replace(")", "").strip() 
                         for val in df.iloc[jumpa[1]]]
            df.columns = new_header
            
            # Remove nan columns
            df = df.loc[:, ~df.columns.str.contains('nan')]
            
            # Get data after header
            df = df.iloc[jumpa[1] + 1:].reset_index(drop=True)
            
            # Filter Visa transactions
            if 'card_type' in df.columns:
                df_visa = df[df['card_type'].astype(str).str.strip().str.lower() == 'visa'].copy()
            else:
                df_visa = df.copy()
            
            # Clean amount column
            if 'amount_rm' in df_visa.columns:
                df_visa['amount_rm'] = (
                    df_visa['amount_rm']
                    .astype(str)
                    .str.replace('RM', '', case=False)
                    .str.replace(',', '')
                    .str.replace('[^0-9.]', '', regex=True)
                )
                df_visa['amount_rm'] = pd.to_numeric(df_visa['amount_rm'], errors='coerce').fillna(0.00)
            
            # Clean receipt column
            if 'receipt' in df_visa.columns:
                df_visa['receipt'] = df_visa['receipt'].astype(str).str[:10]
            
            # Parse date
            if 'date_of_transaction' in df_visa.columns:
                f1 = pd.to_datetime(df_visa['date_of_transaction'], format='%d/%m/%Y %H:%M', errors='coerce')
                f2 = pd.to_datetime(df_visa['date_of_transaction'], format='%d %b %Y %H:%M:%S', errors='coerce')
                df_visa['date_of_transaction'] = f1.fillna(f2)
                df_visa = df_visa.dropna(subset=['date_of_transaction'])
            
            # Validate card numbers
            if 'card_number' in df_visa.columns:
                df_visa = df_visa[df_visa['card_number'].astype(str).str.len() == 16]
            
            # Add metadata columns
            df_visa['uploaded_by'] = self.user_id
            df_visa['batch_id'] = self.batch_id
            df_visa['file_name'] = self.filename
            df_visa['uploaded_at'] = datetime.now()
            
            return df_visa
            
        except Exception as e:
            logger.error(f"Error cleaning EOD data: {e}")
            return pd.DataFrame()
    
    def _save_to_database(self, df):
        """Save processed data to database."""
        try:
            # Ensure table exists
            self._init_table()
            
            # Save using pandas to_sql with custom insert method
            records_saved = len(df)
            
            # Convert to dictionary list for manual insertion
            records = df.to_dict('records')
            
            # Insert records one by one to handle conflicts
            with self.engine.connect() as conn:
                for record in records:
                    try:
                        # Convert date to string for SQL
                        if 'date_of_transaction' in record and pd.notna(record['date_of_transaction']):
                            if isinstance(record['date_of_transaction'], pd.Timestamp):
                                record['date_of_transaction'] = record['date_of_transaction'].to_pydatetime()
                        
                        # Insert into transaksi_eod table
                        stmt = text("""
                            INSERT INTO transaksi_eod (
                                terminal_name, tid, till_summary_no, till_closure_no,
                                date_of_transaction, card_type, card_number, receipt,
                                ref_number, stan_no, acquirer_mid, acquirer_tid,
                                approval_code, amount_rm, uploaded_by, batch_id, file_name
                            ) VALUES (
                                :terminal_name, :tid, :till_summary_no, :till_closure_no,
                                :date_of_transaction, :card_type, :card_number, :receipt,
                                :ref_number, :stan_no, :acquirer_mid, :acquirer_tid,
                                :approval_code, :amount_rm, :uploaded_by, :batch_id, :file_name
                            ) ON CONFLICT (tid, ref_number, date_of_transaction, amount_rm) DO NOTHING
                        """)
                        conn.execute(stmt, record)
                        
                    except Exception as e:
                        logger.warning(f"Failed to insert record: {e}")
                        records_saved -= 1
                        continue
                
                conn.commit()
            
            return records_saved
            
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            return 0
    
    def _init_table(self):
        """Initialize EOD table if not exists."""
        try:
            query = """
            CREATE TABLE IF NOT EXISTS transaksi_eod (
                id SERIAL PRIMARY KEY,
                terminal_name TEXT,
                tid VARCHAR(100),
                till_summary_no VARCHAR(100),
                till_closure_no VARCHAR(100),
                date_of_transaction TIMESTAMP,
                card_type VARCHAR(100),
                card_number VARCHAR(100),
                receipt VARCHAR(100),
                ref_number VARCHAR(100),
                stan_no VARCHAR(100),
                acquirer_mid VARCHAR(100),
                acquirer_tid VARCHAR(100),
                approval_code VARCHAR(100),
                amount_rm DECIMAL(12, 2),
                uploaded_by INTEGER,
                batch_id VARCHAR(100),
                file_name VARCHAR(255),
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_transaction_ref UNIQUE (tid, ref_number, date_of_transaction, amount_rm)
            );
            
            CREATE INDEX IF NOT EXISTS idx_ref_num ON transaksi_eod (ref_number);
            CREATE INDEX IF NOT EXISTS idx_eod_date ON transaksi_eod (date_of_transaction);
            CREATE INDEX IF NOT EXISTS idx_eod_batch ON transaksi_eod (batch_id);
            """
            
            with self.engine.connect() as conn:
                conn.execute(text(query))
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error initializing table: {e}")
    
    def _save_upload_history(self, record_count):
        """Save upload history."""
        try:
            history = UploadHistory(
                user_id=self.user_id,
                file_name=self.filename,
                file_type='eod',
                record_count=record_count,
                status='completed' if record_count > 0 else 'failed',
                batch_id=self.batch_id
            )
            db.session.add(history)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error saving upload history: {e}")


class EMerchantProcessor:
    def __init__(self, db_engine, file_content=None, filename=None, user_id=None, merchant_type='other'):
        self.engine = db_engine
        self.file_content = file_content
        self.filename = filename
        self.user_id = user_id
        self.merchant_type = merchant_type
        self.batch_id = f"EMERCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    def process_from_file_content(self):
        """Process E-Merchant from uploaded file content."""
        try:
            print(f"🚀 [E-MERCHANT] Processing file: {self.filename}")
            
            # Determine file type and read
            if self.filename.endswith('.csv'):
                df = pd.read_csv(io.StringIO(self.file_content.decode('utf-8')))
            elif self.filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(io.BytesIO(self.file_content))
            else:
                return {'success': False, 'error': 'Unsupported file format'}
            
            # Clean and process the data
            processed_df = self._clean_emerchant_data(df)
            
            if processed_df.empty:
                return {'success': False, 'error': 'No valid data found in file'}
            
            # Save to database
            records_saved = self._save_to_database(processed_df)
            
            # Save upload history
            self._save_upload_history(records_saved)
            
            # Calculate statistics
            total_amount = float(processed_df['amount'].sum()) if 'amount' in processed_df.columns else 0
            
            return {
                'success': True,
                'records_processed': len(processed_df),
                'records_saved': records_saved,
                'batch_id': self.batch_id,
                'filename': self.filename,
                'merchant_type': self.merchant_type,
                'total_amount': total_amount
            }
            
        except Exception as e:
            logger.error(f"Error processing E-Merchant file: {e}")
            return {'success': False, 'error': str(e)}
    
    def _clean_emerchant_data(self, df):
        """Clean and process E-Merchant data."""
        try:
            df_clean = df.copy()
            
            # Standardize column names
            df_clean.columns = [col.strip().lower().replace(' ', '_') for col in df_clean.columns]
            
            # Map common column names
            column_mapping = {
                'date': 'transaction_date',
                'order_date': 'transaction_date',
                'tran_date': 'transaction_date',
                'total': 'amount',
                'order_total': 'amount',
                'orderid': 'order_id',
                'order_id': 'order_id',
                'merchant': 'merchant_code',
                'store': 'store_id',
                'email': 'customer_email',
                'payment': 'payment_method',
                'fee_amount': 'fee',
                'net': 'net_amount'
            }
            
            for old_col, new_col in column_mapping.items():
                if old_col in df_clean.columns and new_col not in df_clean.columns:
                    df_clean[new_col] = df_clean[old_col]
            
            # Convert date columns
            if 'transaction_date' in df_clean.columns:
                try:
                    df_clean['transaction_date'] = pd.to_datetime(df_clean['transaction_date']).dt.date
                except:
                    # Try different date formats
                    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d', '%d-%b-%Y']:
                        try:
                            df_clean['transaction_date'] = pd.to_datetime(df_clean['transaction_date'], format=fmt).dt.date
                            break
                        except:
                            continue
            
            # Convert numeric columns
            numeric_cols = ['amount', 'fee', 'net_amount']
            for col in numeric_cols:
                if col in df_clean.columns:
                    # Remove currency symbols and commas
                    df_clean[col] = (
                        df_clean[col]
                        .astype(str)
                        .str.replace('RM', '', case=False)
                        .str.replace(',', '')
                        .str.replace('[^0-9.]', '', regex=True)
                    )
                    df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
            
            # Add merchant type if not present
            if 'merchant_code' not in df_clean.columns:
                df_clean['merchant_code'] = self.merchant_type
            
            # Remove rows with missing essential data
            essential_cols = ['transaction_date', 'amount', 'order_id']
            for col in essential_cols:
                if col in df_clean.columns:
                    df_clean = df_clean.dropna(subset=[col])
            
            # Add metadata columns
            df_clean['uploaded_by'] = self.user_id
            df_clean['batch_id'] = self.batch_id
            df_clean['file_name'] = self.filename
            df_clean['uploaded_at'] = datetime.now()
            df_clean['reconciliation_status'] = 'PENDING'
            
            return df_clean
            
        except Exception as e:
            logger.error(f"Error cleaning E-Merchant data: {e}")
            return pd.DataFrame()
    
    def _save_to_database(self, df):
        """Save processed data to database."""
        try:
            records_saved = 0
            
            # Convert to dictionary list
            records = df.to_dict('records')
            
            with self.engine.connect() as conn:
                for record in records:
                    try:
                        # Insert into transaksi_emerchant table
                        stmt = text("""
                            INSERT INTO transaksi_emerchant (
                                merchant_code, store_id, transaction_date, order_id,
                                payment_method, amount, fee, net_amount, customer_email,
                                status, settlement_date, uploaded_by, batch_id,
                                file_name, reconciliation_status
                            ) VALUES (
                                :merchant_code, :store_id, :transaction_date, :order_id,
                                :payment_method, :amount, :fee, :net_amount, :customer_email,
                                :status, :settlement_date, :uploaded_by, :batch_id,
                                :file_name, :reconciliation_status
                            ) ON CONFLICT (order_id, transaction_date, amount) DO NOTHING
                        """)
                        conn.execute(stmt, record)
                        records_saved += 1
                        
                    except Exception as e:
                        logger.warning(f"Failed to insert E-Merchant record: {e}")
                        continue
                
                conn.commit()
            
            return records_saved
            
        except Exception as e:
            logger.error(f"Error saving E-Merchant to database: {e}")
            return 0
    
    def _save_upload_history(self, record_count):
        """Save upload history."""
        try:
            history = UploadHistory(
                user_id=self.user_id,
                file_name=self.filename,
                file_type='emerchant',
                record_count=record_count,
                status='completed' if record_count > 0 else 'failed',
                batch_id=self.batch_id,
                merchant_type=self.merchant_type
            )
            db.session.add(history)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error saving upload history: {e}")

# ==================== HELPER FUNCTIONS ====================

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# ==================== ROUTES ====================

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validation
        if not username or not email or not password:
            flash('Semua field diperlukan', 'danger')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Password tidak sama', 'danger')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password minimum 6 karakter', 'danger')
            return render_template('register.html')
        
        # Check existing user
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            flash('Username atau email sudah wujud', 'danger')
            return render_template('register.html')
        
        # Create user
        try:
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.commit()
            
            flash('Pendaftaran berjaya! Sila login.', 'success')
            return redirect(url_for('login'))
        except:
            db.session.rollback()
            flash('Error semasa pendaftaran', 'danger')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Login berjaya!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Username atau password salah', 'danger')
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Sila login dulu', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    
    # Get statistics
    total_eod = TransaksiEod.query.filter_by(uploaded_by=user.id).count()
    total_emerchant = TransaksiEmerchant.query.filter_by(uploaded_by=user.id).count()
    
    # Recent uploads
    recent_uploads = UploadHistory.query.filter_by(user_id=user.id)\
        .order_by(UploadHistory.upload_date.desc())\
        .limit(5)\
        .all()
    
    return render_template('dashboard.html',
                         user=user,
                         total_eod=total_eod,
                         total_emerchant=total_emerchant,
                         recent_uploads=recent_uploads)

# ==================== UPLOAD ROUTES ====================

@app.route('/upload/eod', methods=['GET'])
def upload_eod_page():
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    return render_template('upload_eod.html')

@app.route('/api/upload/eod', methods=['POST'])
def upload_eod_api():
    """API endpoint for EOD upload - using EODProcessor"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400
        
        # Read file content
        file_content = file.read()
        filename = secure_filename(file.filename)
        
        # Process with EODProcessor
        processor = EODProcessor(
            db_engine=db.engine,
            file_content=file_content,
            filename=filename,
            user_id=session['user_id']
        )
        
        result = processor.process_from_file_content()
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Unknown error')}), 400
            
    except Exception as e:
        logger.error(f"Error in upload_eod_api: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/upload/emerchant', methods=['GET'])
def upload_emerchant_page():
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    return render_template('upload_emerchant.html')

@app.route('/api/upload/emerchant', methods=['POST'])
def upload_emerchant_api():
    """API endpoint for E-Merchant upload - using EMerchantProcessor"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400
        
        # Get merchant type
        merchant_type = request.form.get('merchant_type', 'other')
        
        # Read file content
        file_content = file.read()
        filename = secure_filename(file.filename)
        
        # Process with EMerchantProcessor
        processor = EMerchantProcessor(
            db_engine=db.engine,
            file_content=file_content,
            filename=filename,
            user_id=session['user_id'],
            merchant_type=merchant_type
        )
        
        result = processor.process_from_file_content()
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Unknown error')}), 400
            
    except Exception as e:
        logger.error(f"Error in upload_emerchant_api: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== VIEW DATA ROUTES ====================

@app.route('/view/eod')
def view_eod():
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = TransaksiEod.query.filter_by(uploaded_by=session['user_id'])
    
    # Filtering
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    merchant_id = request.args.get('merchant_id')
    
    if date_from:
        query = query.filter(TransaksiEod.date_of_transaction >= date_from)
    if date_to:
        query = query.filter(TransaksiEod.date_of_transaction <= date_to)
    if merchant_id:
        query = query.filter(TransaksiEod.terminal_name.ilike(f'%{merchant_id}%'))
    
    # Pagination
    pagination = query.order_by(TransaksiEod.date_of_transaction.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('view_eod.html',
                         data=pagination.items,
                         pagination=pagination)

@app.route('/view/emerchant')
def view_emerchant():
    if 'user_id' not in session:
        flash('Sila login terlebih dahulu', 'warning')
        return redirect(url_for('login'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = TransaksiEmerchant.query.filter_by(uploaded_by=session['user_id'])
    
    # Filtering
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    merchant_code = request.args.get('merchant_code')
    
    if date_from:
        query = query.filter(TransaksiEmerchant.transaction_date >= date_from)
    if date_to:
        query = query.filter(TransaksiEmerchant.transaction_date <= date_to)
    if merchant_code:
        query = query.filter(TransaksiEmerchant.merchant_code.ilike(f'%{merchant_code}%'))
    
    # Pagination
    pagination = query.order_by(TransaksiEmerchant.transaction_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('view_emerchant.html',
                         data=pagination.items,
                         pagination=pagination)

# ==================== RECONCILIATION ROUTES ====================

@app.route('/reconcile')
def reconcile_page():
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
    if 'user_id' not in session:
        return jsonify({}), 401
    
    user_id = session['user_id']
    today = datetime.now().date()
    
    # Get counts
    total_eod = TransaksiEod.query.filter_by(uploaded_by=user_id).count()
    total_emerchant = TransaksiEmerchant.query.filter_by(uploaded_by=user_id).count()
    
    # Count matched transactions
    matched_count = ReconciliationMatch.query.filter_by(matched_by=user_id).count()
    
    # Count unmatched
    unmatched_eod = total_eod - matched_count
    unmatched_emerchant = total_emerchant - matched_count
    
    # Today's matches
    today_matches = ReconciliationMatch.query.filter(
        ReconciliationMatch.matched_by == user_id,
        ReconciliationMatch.matched_date >= today
    ).count()
    
    # Pending reconciliation
    pending_count = unmatched_eod + unmatched_emerchant
    
    return jsonify({
        'total_eod': total_eod,
        'total_emerchant': total_emerchant,
        'matched': matched_count,
        'partial_matches': 0,
        'unmatched_eod': unmatched_eod,
        'unmatched_emerchant': unmatched_emerchant,
        'today_matches': today_matches,
        'pending': pending_count,
        'discrepancies': 0
    })

# ==================== API DATA ROUTES ====================

@app.route('/api/eod/uploads')
def get_eod_uploads():
    if 'user_id' not in session:
        return jsonify([]), 401
    
    uploads = UploadHistory.query.filter_by(
        user_id=session['user_id'],
        file_type='eod'
    ).order_by(UploadHistory.upload_date.desc()).limit(10).all()
    
    result = []
    for upload in uploads:
        result.append({
            'id': upload.id,
            'file_name': upload.file_name,
            'record_count': upload.record_count,
            'upload_date': upload.upload_date.strftime('%Y-%m-%d %H:%M'),
            'status': upload.status,
            'batch_id': upload.batch_id
        })
    
    return jsonify(result)

@app.route('/api/emerchant/uploads')
def get_emerchant_uploads():
    if 'user_id' not in session:
        return jsonify([]), 401
    
    uploads = UploadHistory.query.filter_by(
        user_id=session['user_id'],
        file_type='emerchant'
    ).order_by(UploadHistory.upload_date.desc()).limit(10).all()
    
    result = []
    for upload in uploads:
        result.append({
            'id': upload.id,
            'file_name': upload.file_name,
            'record_count': upload.record_count,
            'upload_date': upload.upload_date.strftime('%Y-%m-%d %H:%M'),
            'status': upload.status,
            'batch_id': upload.batch_id,
            'merchant_type': upload.merchant_type
        })
    
    return jsonify(result)

@app.route('/api/emerchant/stats')
def get_emerchant_stats():
    if 'user_id' not in session:
        return jsonify({}), 401
    
    user_id = session['user_id']
    today = datetime.now().date()
    
    # Calculate today's stats
    today_transactions = TransaksiEmerchant.query.filter(
        TransaksiEmerchant.uploaded_by == user_id,
        TransaksiEmerchant.transaction_date == today
    ).all()
    
    today_count = len(today_transactions)
    today_amount = sum(float(t.amount or 0) for t in today_transactions)
    
    # Get merchant distribution
    merchant_dist = {}
    all_transactions = TransaksiEmerchant.query.filter_by(uploaded_by=user_id).all()
    
    for trans in all_transactions:
        merchant = trans.merchant_code or 'unknown'
        merchant_dist[merchant] = merchant_dist.get(merchant, 0) + 1
    
    return jsonify({
        'today_count': today_count,
        'today_amount': today_amount,
        'average_fee': 2.5,
        'merchant_distribution': merchant_dist
    })

# ==================== LOGOUT ====================

@app.route('/logout')
def logout():
    session.clear()
    flash('Logout berjaya', 'info')
    return redirect(url_for('login'))

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# ==================== MAIN ====================

if __name__ == '__main__':
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
    
    app.run(debug=True, port=5001)