import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF
from functools import wraps

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "database.db")
BILLS_DIR = os.path.join(APP_DIR, "bills")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ---------- DB helpers ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL CHECK(price >= 0),
        stock INTEGER NOT NULL CHECK(stock >= 0)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS bills(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        discount_type TEXT NOT NULL DEFAULT 'amount', -- 'amount' or 'percent'
        discount_value REAL NOT NULL DEFAULT 0,
        subtotal REAL NOT NULL,
        total REAL NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS bill_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        line_total REAL NOT NULL,
        FOREIGN KEY(bill_id) REFERENCES bills(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    )""")
    conn.commit()
    conn.close()

os.makedirs(BILLS_DIR, exist_ok=True)
init_db()

# ---------- auth decorator ----------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

# ---------- routes: auth ----------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("register"))
        hashed = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
            conn.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# ---------- routes: products ----------
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("dashboard.html", products=products)

@app.route("/products", methods=["GET"])
@login_required
def products_page():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("products.html", products=products)

@app.route("/products/add", methods=["POST"])
@login_required
def add_product():
    name = request.form["name"].strip()
    price = float(request.form["price"] or 0)
    stock = int(request.form["stock"] or 0)
    if not name:
        flash("Product name is required.", "danger")
        return redirect(url_for("products_page"))
    conn = get_db()
    conn.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", (name, price, stock))
    conn.commit()
    conn.close()
    flash("Product added.", "success")
    return redirect(url_for("products_page"))

@app.route("/products/<int:pid>/delete", methods=["POST"])
@login_required
def delete_product(pid):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash("Product deleted.", "info")
    return redirect(url_for("products_page"))

@app.route("/products/<int:pid>/update", methods=["POST"])
@login_required
def update_product(pid):
    name = request.form["name"].strip()
    price = float(request.form["price"] or 0)
    stock = int(request.form["stock"] or 0)
    conn = get_db()
    conn.execute("UPDATE products SET name=?, price=?, stock=? WHERE id=?", (name, price, stock, pid))
    conn.commit()
    conn.close()
    flash("Product updated.", "success")
    return redirect(url_for("products_page"))

# ---------- routes: billing ----------
@app.route("/bill/new", methods=["GET"])
@login_required
def new_bill():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY name ASC").fetchall()
    conn.close()
    return render_template("bill_new.html", products=products)

@app.route("/bill/create", methods=["POST"])
@login_required
def create_bill():
    discount_type = request.form.get("discount_type", "amount")
    discount_value = float(request.form.get("discount_value") or 0)
    product_ids = request.form.getlist("product_id")
    quantities = request.form.getlist("quantity")

    items = []
    subtotal = 0.0

    conn = get_db()
    try:
        for pid, qty_str in zip(product_ids, quantities):
            qty = int(qty_str or 0)
            if qty <= 0:
                continue
            prod = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not prod:
                continue
            if qty > prod["stock"]:
                flash(f"Not enough stock for {prod['name']}. Available: {prod['stock']}", "danger")
                return redirect(url_for("new_bill"))
            line_total = prod["price"] * qty
            subtotal += line_total
            items.append({
                "product_id": prod["id"],
                "name": prod["name"],
                "price": float(prod["price"]),
                "quantity": qty,
                "line_total": line_total
            })

        if not items:
            flash("Please select at least one item with quantity.", "warning")
            return redirect(url_for("new_bill"))

        # Calculate discount and total
        if discount_type == "percent":
            discount_amount = (discount_value / 100.0) * subtotal
        else:
            discount_amount = discount_value
        total = max(0.0, subtotal - discount_amount)

        # Insert bill
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bills (user_id, created_at, discount_type, discount_value, subtotal, total) VALUES (?, datetime('now'), ?, ?, ?, ?)",
            (session["user_id"], discount_type, discount_value, subtotal, total)
        )
        bill_id = cur.lastrowid

        # Insert bill items & decrement stock
        for it in items:
            cur.execute("""INSERT INTO bill_items (bill_id, product_id, name, price, quantity, line_total)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (bill_id, it["product_id"], it["name"], it["price"], it["quantity"], it["line_total"]))
            cur.execute("UPDATE products SET stock = stock - ? WHERE id=?", (it["quantity"], it["product_id"]))

        conn.commit()

        # Generate PDF
        filename = f"INVOICE-{bill_id}.pdf"
        filepath = os.path.join(BILLS_DIR, filename)
        generate_invoice_pdf(
            filepath=filepath,
            bill_id=bill_id,
            username=session.get("username", "Shopkeeper"),
            items=items,
            subtotal=subtotal,
            discount_type=discount_type,
            discount_value=discount_value,
            total=total
        )

        flash("Bill created and PDF generated.", "success")
        return redirect(url_for("bill_detail", bill_id=bill_id))
    finally:
        conn.close()

def generate_invoice_pdf(filepath, bill_id, username, items, subtotal, discount_type, discount_value, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Shopkeeper Billing - Invoice", ln=True, align="C")

    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 8, f"Invoice #: {bill_id}", ln=True)
    pdf.cell(0, 8, f"Issued to: {username}", ln=True)
    pdf.cell(0, 8, "", ln=True)

    # Table header
    pdf.set_font("Arial", "B", 12)
    pdf.cell(80, 8, "Item", border=1)
    pdf.cell(30, 8, "Price", border=1, align="R")
    pdf.cell(30, 8, "Qty", border=1, align="R")
    pdf.cell(40, 8, "Line Total", border=1, ln=True, align="R")

    pdf.set_font("Arial", "", 12)
    for it in items:
        pdf.cell(80, 8, it["name"], border=1)
        pdf.cell(30, 8, f"{it['price']:.2f}", border=1, align="R")
        pdf.cell(30, 8, str(it["quantity"]), border=1, align="R")
        pdf.cell(40, 8, f"{it['line_total']:.2f}", border=1, ln=True, align="R")

    pdf.set_font("Arial", "B", 12)
    pdf.cell(140, 8, "Subtotal", border=1)
    pdf.cell(40, 8, f"{subtotal:.2f}", border=1, ln=True, align="R")

    pdf.set_font("Arial", "", 12)
    disc_label = f"Discount ({discount_value:.2f}%)" if discount_type == "percent" else "Discount"
    disc_value = (discount_value/100.0)*subtotal if discount_type == "percent" else discount_value
    pdf.cell(140, 8, disc_label, border=1)
    pdf.cell(40, 8, f"{disc_value:.2f}", border=1, ln=True, align="R")

    pdf.set_font("Arial", "B", 12)
    pdf.cell(140, 8, "Grand Total", border=1)
    pdf.cell(40, 8, f"{total:.2f}", border=1, ln=True, align="R")

    pdf.output(filepath)

# ---------- routes: bills/history ----------
@app.route("/bills")
@login_required
def bills():
    conn = get_db()
    rows = conn.execute("""SELECT id, created_at, discount_type, discount_value, subtotal, total
                           FROM bills WHERE user_id=? ORDER BY id DESC""", (session["user_id"],)).fetchall()
    conn.close()
    return render_template("bills.html", bills=rows)

@app.route("/bills/<int:bill_id>")
@login_required
def bill_detail(bill_id):
    conn = get_db()
    bill = conn.execute("SELECT * FROM bills WHERE id=? AND user_id=?", (bill_id, session["user_id"])).fetchone()
    if not bill:
        conn.close()
        flash("Bill not found.", "danger")
        return redirect(url_for("bills"))
    items = conn.execute("SELECT * FROM bill_items WHERE bill_id=?", (bill_id,)).fetchall()
    conn.close()
    filename = f"INVOICE-{bill_id}.pdf"
    exists = os.path.exists(os.path.join(BILLS_DIR, filename))
    return render_template("bill_show.html", bill=bill, items=items, pdf_exists=exists, filename=filename)

@app.route("/download/<path:filename>")
@login_required
def download_pdf(filename):
    return send_from_directory(BILLS_DIR, filename, as_attachment=True)

# ---------- dev: seed sample data ----------
@app.route("/dev/seed")
def dev_seed():
    # only seed if no products
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count == 0:
        sample = [
            ("Milk 1L", 58.0, 50),
            ("Bread Loaf", 40.0, 30),
            ("Sugar 1kg", 45.0, 100),
            ("Tea Pack", 120.0, 20),
        ]
        conn.executemany("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)", sample)
        conn.commit()
        msg = "Seeded sample products."
    else:
        msg = "Products already seeded."
    conn.close()
    return msg

if __name__ == "__main__":
    app.run(debug=True)
