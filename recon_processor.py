import pandas as pd
from sqlalchemy import text

class ReconProcessor:
    def __init__(self, db_engine):
        self.engine = db_engine
        self.df_recon = None

    def run(self):
        """Logic Full Outer Join."""
        print("\n⚖️  [RECON] Sedang menjalankan Full Outer Join...")
        
        query = """
        SELECT 
            e.date_of_transaction AS eod_date,
            m.tran_date AS merch_date,
            e.card_number AS eod_card,
            e.receipt as eod_receipt,
            e.approval_code AS eod_auth,
            m.auth_code AS merch_auth,
            e.amount_rm AS eod_amount,
            m.amount AS merch_amount,
            m.card_number AS merch_card,
            -- Kita tambah status untuk senang nampak
            CASE 
                WHEN e.approval_code IS NULL THEN 'Missing in EOD'
                WHEN m.auth_code IS NULL THEN 'Missing in Merchant'
                ELSE 'Matched'
            END AS status
            FROM transaksi_eod e
            FULL OUTER JOIN transaksi_merchant m 
            ON e.date_of_transaction::date = m.tran_date::date
            AND e.approval_code = m.auth_code
            AND e.amount_rm = m.amount
            WHERE e.approval_code IS NULL OR m.auth_code IS NULL;
        """
        
        self.df_recon = pd.read_sql(text(query), self.engine)
        
        # Tagging Status
        self.df_recon['status'] = 'MATCH'
        self.df_recon.loc[self.df_recon['eod_card'].isnull(), 'status'] = 'MERCH_ONLY'
        self.df_recon.loc[self.df_recon['merch_card'].isnull(), 'status'] = 'EOD_ONLY'
        
        print(f"✅ [RECON] Selesai! {len(self.df_recon)} transaksi dipadankan.")
        self._export_menu()

    def _export_menu(self):
        """Menu interaktif untuk export."""
        while True:
            print("\n--- 📥 RECON OUTPUT MENU ---")
            print("1. Export ke Excel (.xlsx)")
            print("2. Export ke CSV (.csv)")
            print("3. Papar di skrin (Head 50)")
            print("4. Kembali ke menu utama")
            
            pilihan = input(">> Pilihan: ")
            
            if pilihan == '1':
                self.df_recon.to_excel("result/Recon_Result.xlsx", index=False)
                print("💾 Saved: Recon_Result.xlsx")
                break
            elif pilihan == '2':
                self.df_recon.to_csv("result/Recon_Result.csv", index=False)
                print("💾 Saved: Recon_Result.csv")
                break
            elif pilihan == '3':
                print(self.df_recon.head(50))
            elif pilihan == '4':
                break
            else:
                print("⚠️ Input salah.")