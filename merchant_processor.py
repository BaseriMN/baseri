import pandas as pd
import os
import glob
from sqlalchemy import text

class MerchantProcessor:
    def __init__(self, db_engine, folder_path):
        self.engine = db_engine
        self.folder_path = folder_path
        self.table_name = 'transaksi_merchant'

    def run(self):
        """Main execution flow untuk Merchant."""
        print(f"\n🚀 [MERCHANT] Memulakan proses data Merchant dari: {self.folder_path}")
        self._init_table()
        
        files = glob.glob(os.path.join(self.folder_path, "*.csv"))
        for file_path in files:
            self._process_single_file(file_path)
            
        print("✅ [MERCHANT] Semua fail Merchant selesai diproses.")

    def _init_table(self):
        query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            card_number VARCHAR(20),
            amount DECIMAL(15, 2),
            tran_date TIMESTAMP,
            auth_code VARCHAR(50),
            tran_id VARCHAR(100),
            reference_no VARCHAR(100),
            terminal_no VARCHAR(50),
            batch_no VARCHAR(50),
            card_type VARCHAR(50),
            ezypay_term VARCHAR(50),
            interchange_fee DECIMAL(15, 2),
            file_source VARCHAR(100),
            CONSTRAINT uniq_transaction UNIQUE (card_number, amount, auth_code, tran_date)
        );
        """
        with self.engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()

    def _process_single_file(self, file_path):
        file_name = os.path.basename(file_path)
        try:

            df = pd.read_csv(
                file_path, 
                header=None
            )           
            # Cari Header 'card number'
            card_rows = [i for i in range(len(df)) if 'card number' in ' '.join(df.iloc[i].astype(str).values).lower()]
            if not card_rows:
                return

            target_row = card_rows[0]
            df.columns = [str(val).lower().strip().replace(" ", "_").replace("(","").replace(")","") for val in df.iloc[target_row]]
            df = df.iloc[target_row + 1:].reset_index(drop=True)

            # Filter Visa & 16 Digit
            col_type = [c for c in df.columns if 'card_type' in c]
            if col_type:
                df = df[df[col_type[0]].str.contains('VISA', case=False, na=False)].copy()
            
            df['card_number'] = df['card_number'].astype(str).str.strip()
            df = df[df['card_number'].str.len() == 16].copy()

            if df.empty:
                return

            # Cleanup
            df.columns = [col.replace('.', '').strip() for col in df.columns]
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
            df['tran_date'] = df['tran_date'].astype(str).str.replace('-', '/').str.strip()
            df['tran_date'] = pd.to_datetime(df['tran_date'], format='%d/%m/%y', errors='coerce')
            df['file_source'] = file_name

            cols = ['card_number', 'amount', 'tran_date', 'auth_code', 'tran_id', 'reference_no', 'terminal_no', 'batch_no', 'card_type', 'ezypay_term', 'interchange_fee', 'file_source']
            df_final = df[[c for c in cols if c in df.columns]].copy()

            try:
                df_final.to_sql(self.table_name, self.engine, if_exists='append', index=False)
                print(f"   💾 [OK] {file_name}: +{len(df_final)} rekod.")
            except Exception:
                print(f"   ⏭️ [SKIP] {file_name}: Duplicate detected.")
                
        except Exception as e:
            print(f"   🔥 [ERROR] {file_name}: {e}")