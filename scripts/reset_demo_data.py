"""Reset the travel database to its pristine state (undo demo bookings / changes).

    python scripts/reset_demo_data.py

Restores `travel2.sqlite` from the untouched download (`travel2.sqlite.backup`)
and shifts the flight dates so they are relative to today again. Stop the API
first. The vector index does not need to be rebuilt.
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from customer_support_chat.app.core.settings import get_settings  # noqa: E402
from customer_support_chat.app.services.utils import update_dates  # noqa: E402

if __name__ == "__main__":
    db_file = get_settings().SQLITE_DB_PATH
    backup = db_file + ".backup"
    if not os.path.exists(backup):
        sys.exit(f"No pristine backup found at {backup}. Run `python scripts/ingest.py` first.")
    shutil.copy(backup, db_file)
    update_dates(db_file)
    print(f"Restored {db_file} and shifted flight dates to the current time.")
