from extensions import db, bcrypt
from datetime import datetime
import re

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
    eod_uploads = db.relationship('TransaksiEod', backref='uploader_eod', lazy=True)
    emerchant_uploads = db.relationship('TransaksiEmerchant', backref='uploader_emerchant', lazy=True)
    upload_history = db.relationship('UploadHistory', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class TransaksiEod(db.Model):
    __tablename__ = 'transaksi_eod'
    
    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(db.String(50))
    terminal_id = db.Column(db.String(50))
    transaction_date = db.Column(db.Date, nullable=False)
    transaction_time = db.Column(db.Time)
    card_number = db.Column(db.String(20))
    amount = db.Column(db.Numeric(15, 2))
    transaction_type = db.Column(db.String(20))
    response_code = db.Column(db.String(10))
    approval_code = db.Column(db.String(20))
    stan = db.Column(db.String(20))
    rrn = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    batch_id = db.Column(db.String(50))
    file_name = db.Column(db.String(255))
    status = db.Column(db.String(20), default='PENDING')
    
    def to_dict(self):
        return {
            'id': self.id,
            'merchant_id': self.merchant_id,
            'terminal_id': self.terminal_id,
            'transaction_date': self.transaction_date.strftime('%Y-%m-%d') if self.transaction_date else None,
            'transaction_time': str(self.transaction_time) if self.transaction_time else None,
            'card_number': self.card_number,
            'amount': float(self.amount) if self.amount else None,
            'transaction_type': self.transaction_type,
            'response_code': self.response_code,
            'approval_code': self.approval_code,
            'stan': self.stan,
            'rrn': self.rrn,
            'batch_id': self.batch_id,
            'file_name': self.file_name,
            'status': self.status,
            'uploaded_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def __repr__(self):
        return f'<TransaksiEod {self.merchant_id} {self.transaction_date}>'


class TransaksiEmerchant(db.Model):
    __tablename__ = 'transaksi_emerchant'
    
    id = db.Column(db.Integer, primary_key=True)
    merchant_code = db.Column(db.String(50))
    store_id = db.Column(db.String(50))
    transaction_date = db.Column(db.Date, nullable=False)
    transaction_time = db.Column(db.Time)
    order_id = db.Column(db.String(100))
    payment_method = db.Column(db.String(50))
    amount = db.Column(db.Numeric(15, 2))
    fee = db.Column(db.Numeric(15, 2))
    net_amount = db.Column(db.Numeric(15, 2))
    customer_email = db.Column(db.String(255))
    status = db.Column(db.String(20))
    settlement_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    batch_id = db.Column(db.String(50))
    file_name = db.Column(db.String(255))
    reconciliation_status = db.Column(db.String(20), default='PENDING')
    
    def to_dict(self):
        return {
            'id': self.id,
            'merchant_code': self.merchant_code,
            'store_id': self.store_id,
            'transaction_date': self.transaction_date.strftime('%Y-%m-%d') if self.transaction_date else None,
            'transaction_time': str(self.transaction_time) if self.transaction_time else None,
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
            'uploaded_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def __repr__(self):
        return f'<TransaksiEmerchant {self.merchant_code} {self.order_id}>'


class UploadHistory(db.Model):
    __tablename__ = 'upload_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    file_name = db.Column(db.String(255))
    file_type = db.Column(db.String(20))
    record_count = db.Column(db.Integer)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20))
    batch_id = db.Column(db.String(50))
    processing_time = db.Column(db.Interval)
    
    def __repr__(self):
        return f'<UploadHistory {self.file_name} {self.status}>'