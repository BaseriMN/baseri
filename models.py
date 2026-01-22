from extensions import db, bcrypt
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    eod_uploads = db.relationship('TransaksiEod', backref='uploader', lazy=True)
    emerchant_uploads = db.relationship('TransaksiEmerchant', backref='uploader', lazy=True)
    upload_history = db.relationship('UploadHistory', backref='user', lazy=True)
    reconciliation_matches = db.relationship('ReconciliationMatch', backref='matched_user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class TransaksiEod(db.Model):
    __tablename__ = 'transaksi_eod'
    
    id = db.Column(db.Integer, primary_key=True)
    terminal_name = db.Column(db.String(255))
    tid = db.Column(db.String(100))
    till_summary_no = db.Column(db.String(100))
    till_closure_no = db.Column(db.String(100))
    date_of_transaction = db.Column(db.DateTime)
    card_type = db.Column(db.String(100))
    card_number = db.Column(db.String(100))
    receipt = db.Column(db.String(100))
    ref_number = db.Column(db.String(100))
    stan_no = db.Column(db.String(100))
    acquirer_mid = db.Column(db.String(100))
    acquirer_tid = db.Column(db.String(100))
    approval_code = db.Column(db.String(100))
    amount_rm = db.Column(db.Numeric(12, 2))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    batch_id = db.Column(db.String(100))
    file_name = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    matches = db.relationship('ReconciliationMatch', backref='eod_transaction', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'terminal_name': self.terminal_name,
            'tid': self.tid,
            'ref_number': self.ref_number,
            'date_of_transaction': self.date_of_transaction.strftime('%Y-%m-%d %H:%M:%S') if self.date_of_transaction else None,
            'card_type': self.card_type,
            'card_number': self.card_number,
            'amount_rm': float(self.amount_rm) if self.amount_rm else None,
            'batch_id': self.batch_id,
            'file_name': self.file_name,
            'uploaded_at': self.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if self.uploaded_at else None
        }
    
    def __repr__(self):
        return f'<TransaksiEod {self.ref_number} {self.amount_rm}>'


class TransaksiEmerchant(db.Model):
    __tablename__ = 'transaksi_emerchant'
    
    id = db.Column(db.Integer, primary_key=True)
    merchant_code = db.Column(db.String(100))
    store_id = db.Column(db.String(100))
    transaction_date = db.Column(db.Date)
    order_id = db.Column(db.String(100))
    payment_method = db.Column(db.String(100))
    amount = db.Column(db.Numeric(15, 2))
    fee = db.Column(db.Numeric(15, 2))
    net_amount = db.Column(db.Numeric(15, 2))
    customer_email = db.Column(db.String(255))
    status = db.Column(db.String(50))
    settlement_date = db.Column(db.Date)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    batch_id = db.Column(db.String(100))
    file_name = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    reconciliation_status = db.Column(db.String(20), default='PENDING')
    
    # Relationships
    matches = db.relationship('ReconciliationMatch', backref='emerchant_transaction', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'merchant_code': self.merchant_code,
            'store_id': self.store_id,
            'transaction_date': self.transaction_date.strftime('%Y-%m-%d') if self.transaction_date else None,
            'order_id': self.order_id,
            'payment_method': self.payment_method,
            'amount': float(self.amount) if self.amount else None,
            'fee': float(self.fee) if self.fee else None,
            'net_amount': float(self.net_amount) if self.net_amount else None,
            'customer_email': self.customer_email,
            'status': self.status,
            'settlement_date': self.settlement_date.strftime('%Y-%m-%d') if self.settlement_date else None,
            'batch_id': self.batch_id,
            'file_name': self.file_name,
            'reconciliation_status': self.reconciliation_status,
            'uploaded_at': self.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if self.uploaded_at else None
        }
    
    def __repr__(self):
        return f'<TransaksiEmerchant {self.order_id} {self.amount}>'


class UploadHistory(db.Model):
    __tablename__ = 'upload_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    file_name = db.Column(db.String(255))
    file_type = db.Column(db.String(20))  # 'eod' or 'emerchant'
    merchant_type = db.Column(db.String(50))  # For e-merchant only
    record_count = db.Column(db.Integer)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20))  # 'success', 'failed', 'processing'
    batch_id = db.Column(db.String(100))
    processing_time = db.Column(db.Interval)
    
    def __repr__(self):
        return f'<UploadHistory {self.file_name} {self.status}>'


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
    
    def __repr__(self):
        return f'<ReconciliationMatch {self.eod_transaction_id} - {self.emerchant_transaction_id}>'