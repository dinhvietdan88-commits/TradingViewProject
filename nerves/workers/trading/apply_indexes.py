import sqlite3

import config

db = sqlite3.connect(config.DB_PATH)
stmts = [
    "CREATE INDEX IF NOT EXISTS idx_ind_sig_sym_date ON indicator_signals(symbol, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_ind_sig_date_sym ON indicator_signals(created_at, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_ind_sig_sym_type ON indicator_signals(symbol, signal_type)",
]
for s in stmts:
    db.execute(s)
    print("OK:", s[:60])
db.commit()

rows = db.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='indicator_signals'"
).fetchall()
print("\nAll indexes on indicator_signals:")
for r in rows:
    print(" -", r[0])
db.close()
print("\nDone.")
