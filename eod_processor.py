import pandas as pd
import os
import glob
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

class EODProcessor:
    def __init__(self, db_engine, folder_path):
        self.engine = db_engine
        self.folder_path = folder_path

    def _insert_on_conflict_nothing(self, table, conn, keys, data_iter):
        """Internal helper: Handle Upsert logic."""
        data = [dict(zip(keys, row)) for row in data_iter]
        stmt = insert(table.table).values(data)
        on_conflict_stmt = stmt.on_conflict_do_nothing(
            index_elements=['tid', 'ref_number', 'date_of_transaction', 'amount_rm']
        )
        conn.execute(on_conflict_stmt)

    def run(self):
        """Main execution flow untuk EOD."""
        print(f"\n🚀 [EOD] Memulakan proses data Bank/EOD dari: {self.folder_path}")
        
        # 1. Pastikan Table Wujud
        self._init_table()
        
        # 2. Proses Fail
        files = glob.glob(os.path.join(self.folder_path, "*.csv"))
        for file_path in files:
            self._process_single_file(file_path)
            
        print("✅ [EOD] Semua fail EOD selesai diproses.")

    def _init_table(self):
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
            CONSTRAINT unique_transaction_ref UNIQUE (tid, ref_number, date_of_transaction, amount_rm)
        );
        CREATE INDEX IF NOT EXISTS idx_ref_num ON transaksi_eod (ref_number);
        """
        with self.engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()

    def _process_single_file(self, file_path):
        file_name = os.path.basename(file_path)
        try:
            df = pd.read_csv(file_path, header=None)
            
            # Logic cari header
            jumpa = []
            for i in range(len(df)):
                row_text = ' '.join(str(x) for x in df.iloc[i].values)
                if 'Terminal Name' in row_text:
                    jumpa.append(i)
            
            if len(jumpa) < 2:
                print(f"   ⚠️ [SKIP] {file_name} - Header tidak lengkap.")
                return

            # Clean header & data
            new_header = [str(val).lower().replace(" ", "_").replace("(","").replace(")","") for val in df.iloc[jumpa[1]]]
            df.columns = new_header
            df = df.iloc[:, df.columns != 'nan']
            df = df.iloc[jumpa[1] + 1:].reset_index(drop=True)
            
            # Cleaning Logic
            df_visa = df[df['card_type'].str.strip() == 'Visa'].copy()
            df_visa['amount_rm'] = df_visa['amount_rm'].astype(str).str.replace('RM', '', case=False).str.replace(',', '')
            df_visa['amount_rm'] = pd.to_numeric(df_visa['amount_rm'].str.replace('[^0-9.]', '', regex=True), errors='coerce').fillna(0.00)
            df_visa['receipt'] = df_visa['receipt'].astype(str).str[:10]
            
            # Date Parsing
            f1 = pd.to_datetime(df_visa['date_of_transaction'], format='%d/%m/%Y %H:%M', errors='coerce')
            f2 = pd.to_datetime(df_visa['date_of_transaction'], format='%d %b %Y %H:%M:%S', errors='coerce')
            df_visa['date_of_transaction'] = f1.fillna(f2)
            
            df_visa = df_visa.dropna(subset=['date_of_transaction'])
            df_visa = df_visa[df_visa['card_number'].astype(str).str.len() == 16]

            if not df_visa.empty:
                df_visa.to_sql('transaksi_eod', self.engine, if_exists='append', index=False, method=self._insert_on_conflict_nothing)
                print(f"   💾 [OK] {file_name}: {len(df_visa)} rekod.")
        except Exception as e:
            print(f"   🔥 [ERROR] {file_name}: {e}")