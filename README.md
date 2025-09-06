# Shopkeeper Billing Web App (Flask + SQLite)

## Quick Start
```bash
# 1) Create and activate a virtual environment
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Run the app
# (optional) set a stronger secret key
# PowerShell:   $env:SECRET_KEY="your-strong-key"
# macOS/Linux:  export SECRET_KEY="your-strong-key"
python app.py

# 4) Visit http://127.0.0.1:5000
```

## Seed sample products
Open your browser at: `http://127.0.0.1:5000/dev/seed` (only once).

## Features
- Register/Login for shopkeepers
- Manage products (add, edit, delete, stock, price)
- Create bills with amount/% discount
- Auto stock deduction
- PDF Invoice generation (downloadable)
- Bills history with line items
