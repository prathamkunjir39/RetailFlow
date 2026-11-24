import os
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
CENT = Decimal('0.01')


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def positive_int(value, *, allow_zero=False):
    n = int(value)
    if n < (0 if allow_zero else 1) or n > 4294967295:
        raise ValueError('Quantity is outside the allowed range')
    return n


def decimal_input(value, *, allow_zero=False, maximum='99999999.99'):
    d = Decimal(str(value))
    if not d.is_finite() or d < 0 or (d == 0 and not allow_zero) or d > Decimal(maximum) or d != money(d):
        raise ValueError('Invalid monetary amount')
    return d


def create_app(test_config=None):
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'replace-this-for-development-only')
    if test_config:
        app.config.update(test_config)

    def connect():
        return mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'), port=int(os.getenv('DB_PORT', '3306')),
            user=os.getenv('DB_USER', 'root'), password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'retail_inventory_db'))

    def query(sql, params=(), one=False):
        db = connect()
        try:
            cur = db.cursor(dictionary=True)
            try:
                cur.execute(sql, params)
                return cur.fetchone() if one else cur.fetchall()
            finally:
                cur.close()
        finally:
            db.close()

    def login_required(role=None):
        def decorate(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                if not session.get('user_id'):
                    return redirect(url_for('login'))
                if role and session.get('role') != role:
                    flash('Administrator permission required.', 'danger')
                    return redirect(url_for('dashboard'))
                return func(*args, **kwargs)
            return wrapped
        return decorate

    @app.context_processor
    def context():
        return {'current_user': session.get('username'), 'current_role': session.get('role')}

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        if query('SELECT COUNT(*) AS n FROM users', one=True)['n']:
            return redirect(url_for('login'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not (3 <= len(username) <= 50 and len(password) >= 8):
                flash('Username must be 3–50 characters; password at least 8.', 'danger')
            else:
                db = connect()
                try:
                    cur = db.cursor()
                    try:
                        cur.execute('INSERT INTO users (full_name,username,password_hash,role) VALUES (%s,%s,%s,%s)',
                                    ('Administrator', username, generate_password_hash(password), 'admin'))
                        db.commit()
                        flash('Admin account created. Please sign in.', 'success')
                        return redirect(url_for('login'))
                    finally:
                        cur.close()
                except mysql.connector.Error:
                    db.rollback()
                    flash('Unable to create account.', 'danger')
                finally:
                    db.close()
        return render_template('setup.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if query('SELECT COUNT(*) AS n FROM users', one=True)['n'] == 0:
            return redirect(url_for('setup'))
        if request.method == 'POST':
            user = query('SELECT * FROM users WHERE username=%s', (request.form.get('username', ''),), one=True)
            if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
                session.clear()
                session.update(user_id=user['user_id'], username=user['username'], role=user['role'])
                return redirect(url_for('dashboard'))
            flash('Incorrect username or password.', 'danger')
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    
    @app.route('/')
    @login_required()
    def dashboard():
        stats = query('''
            SELECT
                (SELECT COUNT(*) FROM products) AS products,
                (SELECT COALESCE(SUM(stock_quantity), 0)
                 FROM products) AS stock,
                (SELECT COUNT(*) FROM invoices
                 WHERE status = 'completed') AS invoices,
                (SELECT COALESCE(SUM(total_amount), 0)
                 FROM invoices
                 WHERE status = 'completed') AS revenue
        ''', one=True)

        low = query('''
            SELECT * FROM products
            WHERE stock_quantity <= low_stock_threshold
            ORDER BY stock_quantity, product_name
            LIMIT 10
        ''')

        daily_sales = query('''
            SELECT DATE(invoice_date) AS day,
                   SUM(total_amount) AS revenue
            FROM invoices
            WHERE status = 'completed'
              AND invoice_date >= CURDATE() - INTERVAL 6 DAY
              AND invoice_date < CURDATE() + INTERVAL 1 DAY
            GROUP BY DATE(invoice_date)
            ORDER BY day
        ''')

        top_products = query('''
            SELECT p.product_name,
                   SUM(ii.quantity) AS units
            FROM invoice_items ii
            JOIN products p ON p.product_id = ii.product_id
            JOIN invoices i ON i.invoice_id = ii.invoice_id
            WHERE i.status = 'completed'
            GROUP BY p.product_id, p.product_name
            ORDER BY units DESC
            LIMIT 5
        ''')

        stock_status = query('''
            SELECT
                COALESCE(SUM(CASE WHEN stock_quantity >
                    low_stock_threshold THEN 1 ELSE 0 END), 0)
                    AS healthy,
                COALESCE(SUM(CASE WHEN stock_quantity > 0
                    AND stock_quantity <= low_stock_threshold
                    THEN 1 ELSE 0 END), 0) AS low_stock,
                COALESCE(SUM(CASE WHEN stock_quantity = 0
                    THEN 1 ELSE 0 END), 0) AS out_of_stock
            FROM products
        ''', one=True)

        monthly_sales = query('''
            SELECT DATE_FORMAT(invoice_date, '%Y-%m') AS month,
                   SUM(total_amount) AS revenue
            FROM invoices
            WHERE status = 'completed'
              AND invoice_date >= DATE_FORMAT(
                  CURDATE() - INTERVAL 5 MONTH, '%Y-%m-01')
              AND invoice_date < DATE_FORMAT(
                  CURDATE() + INTERVAL 1 MONTH, '%Y-%m-01')
            GROUP BY DATE_FORMAT(invoice_date, '%Y-%m')
            ORDER BY month
        ''')

        from datetime import date, timedelta

        today = date.today()
        daily_lookup = {
            str(row['day']): float(row['revenue'])
            for row in daily_sales
        }

        days = [
            today - timedelta(days=offset)
            for offset in range(6, -1, -1)
        ]

        daily_labels = [day.strftime('%d %b') for day in days]
        daily_values = [
            daily_lookup.get(day.isoformat(), 0)
            for day in days
        ]

        month_lookup = {
            row['month']: float(row['revenue'])
            for row in monthly_sales
        }

        month_keys = []
        month_labels = []
        for offset in range(5, -1, -1):
            year = today.year
            month = today.month - offset
            while month <= 0:
                month += 12
                year -= 1

            month_keys.append(f'{year}-{month:02d}')
            month_labels.append(
                date(year, month, 1).strftime('%b %Y')
            )

        charts = {
            'daily_labels': daily_labels,
            'daily_values': daily_values,
            'top_labels': [
                row['product_name'] for row in top_products
            ],
            'top_values': [
                int(row['units']) for row in top_products
            ],
            'stock_values': [
                int(stock_status['healthy']),
                int(stock_status['low_stock']),
                int(stock_status['out_of_stock'])
            ],
            'monthly_labels': month_labels,
            'monthly_values': [
                month_lookup.get(month, 0)
                for month in month_keys
            ]
        }

        return render_template(
            'dashboard.html',
            stats=stats,
            low=low,
            charts=charts
        )


    @app.route('/products')
    @login_required()
    def products():
        term = request.args.get('q', '').strip()
        rows = query('SELECT * FROM products WHERE product_name LIKE %s OR sku LIKE %s ORDER BY product_id DESC',
                     (f'%{term}%', f'%{term}%'))
        return render_template('products.html', products=rows, term=term)

    @app.route('/add-product', methods=['GET', 'POST'])
    @login_required('admin')
    def add_product():
        return product_form(None)

    @app.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
    @login_required('admin')
    def edit_product(product_id):
        product = query('SELECT * FROM products WHERE product_id=%s', (product_id,), one=True)
        if not product:
            return 'Product not found', 404
        return product_form(product)

    def product_form(product):
        if request.method == 'POST':
            try:
                name = request.form.get('product_name', '').strip()
                sku = request.form.get('sku', '').strip()
                category = request.form.get('category', '').strip()
                price = decimal_input(request.form.get('price', ''))
                threshold = positive_int(request.form.get('low_stock_threshold', ''), allow_zero=True)
                if not (1 <= len(name) <= 150 and 1 <= len(sku) <= 50 and len(category) <= 100):
                    raise ValueError('Check name, SKU and category lengths')
                stock = positive_int(request.form.get('stock_quantity', ''), allow_zero=True) if product is None else None
            except (ValueError, InvalidOperation) as e:
                flash(f'Invalid product details: {e}', 'danger')
                return render_template('product_form.html', product=product), 400
            db = connect()
            try:
                cur = db.cursor()
                try:
                    if product:
                        cur.execute('UPDATE products SET product_name=%s,sku=%s,category=%s,price=%s,low_stock_threshold=%s WHERE product_id=%s',
                                    (name, sku, category, price, threshold, product['product_id']))
                    else:
                        cur.execute('INSERT INTO products (product_name,sku,category,price,stock_quantity,low_stock_threshold) VALUES (%s,%s,%s,%s,%s,%s)',
                                    (name, sku, category, price, stock, threshold))
                        new_id = cur.lastrowid
                        if stock:
                            cur.execute('INSERT INTO stock_movements (product_id,movement_type,quantity,remarks,user_id) VALUES (%s,%s,%s,%s,%s)',
                                        (new_id, 'stock_in', stock, 'Opening stock', session['user_id']))
                    db.commit()
                    flash('Product saved successfully.', 'success')
                    return redirect(url_for('products'))
                finally:
                    cur.close()
            except mysql.connector.IntegrityError:
                db.rollback()
                flash('SKU already exists or invalid product data.', 'danger')
            except mysql.connector.Error:
                db.rollback()
                app.logger.exception('Save product failed')
                flash('Unable to save product.', 'danger')
            finally:
                db.close()
        return render_template('product_form.html', product=product)

    @app.post('/products/<int:product_id>/delete')
    @login_required('admin')
    def delete_product(product_id):
        db = connect()
        try:
            cur = db.cursor()
            try:
                cur.execute('DELETE FROM products WHERE product_id=%s', (product_id,))
                db.commit()
                flash('Product deleted.', 'success')
            finally:
                cur.close()
        except mysql.connector.IntegrityError:
            db.rollback()
            flash('Cannot delete a product with transaction history. Keep it for audit.', 'warning')
        finally:
            db.close()
        return redirect(url_for('products'))

    @app.route('/stock', methods=['GET', 'POST'])
    @login_required('admin')
    def stock():
        if request.method == 'POST':
            db = None
            try:
                pid = positive_int(request.form.get('product_id', ''))
                qty = positive_int(request.form.get('quantity', ''))
                mode = request.form.get('mode')
                if mode not in ('stock_in', 'adjustment_add', 'adjustment_remove'):
                    raise ValueError('Invalid movement type')
                supplier = request.form.get('supplier_name', '').strip()
                if mode == 'stock_in' and not (1 <= len(supplier) <= 150):
                    raise ValueError('Supplier name required for purchases')
                unit_cost = decimal_input(request.form.get('unit_cost', '0'), allow_zero=True) if mode == 'stock_in' else Decimal('0')
                remarks = request.form.get('remarks', '').strip()[:255]
                db = connect()
                db.start_transaction()
                cur = db.cursor(dictionary=True)
                try:
                    cur.execute('SELECT * FROM products WHERE product_id=%s FOR UPDATE', (pid,))
                    product = cur.fetchone()
                    if not product:
                        raise ValueError('Product not found')
                    delta = -qty if mode == 'adjustment_remove' else qty
                    if product['stock_quantity'] + delta < 0:
                        raise ValueError('Insufficient stock; negative inventory blocked')
                    cur.execute('UPDATE products SET stock_quantity=stock_quantity+%s WHERE product_id=%s', (delta, pid))
                    purchase_id = None
                    if mode == 'stock_in':
                        total = money(unit_cost * qty)
                        if total > Decimal('99999999.99'):
                            raise ValueError('Purchase total exceeds limit')
                        cur.execute('INSERT INTO purchases (supplier_name,total_amount,created_by) VALUES (%s,%s,%s)',
                                    (supplier, total, session['user_id']))
                        purchase_id = cur.lastrowid
                        cur.execute('INSERT INTO purchase_items (purchase_id,product_id,quantity,purchase_price) VALUES (%s,%s,%s,%s)',
                                    (purchase_id, pid, qty, unit_cost))
                    cur.execute('INSERT INTO stock_movements (product_id,movement_type,quantity,reference_id,remarks,user_id) VALUES (%s,%s,%s,%s,%s,%s)',
                                (pid, 'stock_in' if mode == 'stock_in' else 'adjustment', delta, purchase_id, remarks or mode, session['user_id']))
                    db.commit()
                    flash('Stock updated and movement recorded.', 'success')
                    return redirect(url_for('stock'))
                finally:
                    cur.close()
            except (ValueError, InvalidOperation) as e:
                if db:
                    db.rollback()
                flash(str(e), 'danger')
            except mysql.connector.Error:
                if db:
                    db.rollback()
                app.logger.exception('Stock operation failed')
                flash('Stock update failed.', 'danger')
            finally:
                if db:
                    db.close()
        return render_template('stock.html', products=query('SELECT * FROM products ORDER BY product_name'),
                               movements=query('''SELECT m.*,p.product_name,u.username FROM stock_movements m
                               JOIN products p ON p.product_id=m.product_id LEFT JOIN users u ON u.user_id=m.user_id
                               ORDER BY movement_id DESC LIMIT 30'''))

    @app.route('/billing', methods=['GET', 'POST'])
    @login_required()
    def billing():
        if request.method == 'POST':
            db = None
            try:
                ids = request.form.getlist('product_id[]')
                qtys = request.form.getlist('quantity[]')
                if not ids or len(ids) != len(qtys) or len(ids) > 50:
                    raise ValueError('Select at least one product (maximum 50 lines)')
                cart = {}
                for pid, qty in zip(ids, qtys):
                    if not pid:
                        continue
                    product_id = positive_int(pid)
                    quantity = positive_int(qty)
                    cart[product_id] = cart.get(product_id, 0) + quantity
                    if cart[product_id] > 4294967295:
                        raise ValueError('Quantity too large')
                if not cart:
                    raise ValueError('Cart is empty')
                discount_pct = decimal_input(request.form.get('discount', '0'), allow_zero=True, maximum='100')
                tax_pct = decimal_input(request.form.get('tax', '0'), allow_zero=True, maximum='100')
                customer = request.form.get('customer_name', '').strip()[:150]
                db = connect()
                db.start_transaction()
                cur = db.cursor(dictionary=True)
                try:
                    # Lock in a stable order to reduce deadlocks during simultaneous checkout.
                    items = []
                    subtotal = Decimal('0')
                    for pid in sorted(cart):
                        cur.execute('SELECT * FROM products WHERE product_id=%s FOR UPDATE', (pid,))
                        product = cur.fetchone()
                        if not product:
                            raise ValueError('A product in the cart no longer exists')
                        if product['stock_quantity'] < cart[pid]:
                            raise ValueError(f"Insufficient stock for {product['product_name']}")
                        line_total = money(product['price'] * cart[pid])
                        subtotal += line_total
                        items.append((product, cart[pid], line_total))
                    discount = money(subtotal * discount_pct / 100)
                    taxable = subtotal - discount
                    tax = money(taxable * tax_pct / 100)
                    total = taxable + tax
                    if total > Decimal('99999999.99'):
                        raise ValueError('Invoice total exceeds limit')
                    # Idempotency token prevents a double-click/retry from creating two invoices.
                    token = request.form.get('checkout_token', '').strip()
                    if not token or token != session.get('checkout_token'):
                        raise ValueError('Checkout expired or already submitted. Reload billing page.')
                    cur.execute('INSERT INTO invoices (invoice_number,customer_name,subtotal,discount,tax,total_amount,cashier_id) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                                ('PENDING-' + token, customer, subtotal, discount, tax, total, session['user_id']))
                    invoice_id = cur.lastrowid
                    number = f'INV-{invoice_id:06d}'
                    cur.execute('UPDATE invoices SET invoice_number=%s WHERE invoice_id=%s', (number, invoice_id))
                    for product, quantity, line_total in items:
                        cur.execute('UPDATE products SET stock_quantity=stock_quantity-%s WHERE product_id=%s AND stock_quantity >= %s',
                                    (quantity, product['product_id'], quantity))
                        if cur.rowcount != 1:
                            raise ValueError('Stock changed during checkout; please retry')
                        cur.execute('INSERT INTO invoice_items (invoice_id,product_id,quantity,unit_price,item_total) VALUES (%s,%s,%s,%s,%s)',
                                    (invoice_id, product['product_id'], quantity, product['price'], line_total))
                        cur.execute('INSERT INTO stock_movements (product_id,movement_type,quantity,reference_id,remarks,user_id) VALUES (%s,%s,%s,%s,%s,%s)',
                                    (product['product_id'], 'stock_out', -quantity, invoice_id, number, session['user_id']))
                    db.commit()
                    session.pop('checkout_token', None)
                    flash(f'Invoice {number} generated successfully.', 'success')
                    return redirect(url_for('invoice', invoice_id=invoice_id))
                finally:
                    cur.close()
            except (ValueError, InvalidOperation) as e:
                if db:
                    db.rollback()
                flash(str(e), 'danger')
            except mysql.connector.IntegrityError:
                if db:
                    db.rollback()
                flash('Duplicate checkout detected. Check invoices before retrying.', 'warning')
            except mysql.connector.Error:
                if db:
                    db.rollback()
                app.logger.exception('Checkout failed')
                flash('Checkout failed. No sale was saved.', 'danger')
            finally:
                if db:
                    db.close()
        import secrets
        token = secrets.token_hex(16)
        session['checkout_token'] = token
        return render_template('billing.html', products=query('SELECT * FROM products WHERE stock_quantity>0 ORDER BY product_name'), token=token)

    @app.route('/invoices')
    @login_required()
    def invoices():
        return render_template('invoices.html', invoices=query('''SELECT i.*,u.username AS cashier FROM invoices i
            LEFT JOIN users u ON u.user_id=i.cashier_id ORDER BY invoice_id DESC LIMIT 200'''))

    @app.route('/invoices/<int:invoice_id>')
    @login_required()
    def invoice(invoice_id):
        header = query('''SELECT i.*,u.username AS cashier FROM invoices i LEFT JOIN users u
            ON u.user_id=i.cashier_id WHERE invoice_id=%s''', (invoice_id,), one=True)
        if not header:
            return 'Invoice not found', 404
        lines = query('''SELECT ii.*,p.product_name,p.sku FROM invoice_items ii
            JOIN products p ON p.product_id=ii.product_id WHERE invoice_id=%s''', (invoice_id,))
        return render_template('invoice.html', invoice=header, lines=lines)

    @app.route('/alerts')
    @login_required()
    def alerts():
        return render_template('alerts.html', products=query('SELECT * FROM products WHERE stock_quantity<=low_stock_threshold ORDER BY stock_quantity,product_name'))

    @app.route('/reports')
    @login_required('admin')
    def reports():
        sales = query('''SELECT DATE(invoice_date) AS day,COUNT(*) AS bills,SUM(total_amount) AS revenue
            FROM invoices WHERE status='completed' GROUP BY DATE(invoice_date) ORDER BY day DESC LIMIT 30''')
        top = query('''SELECT p.product_name,SUM(ii.quantity) AS units,SUM(ii.item_total) AS gross
            FROM invoice_items ii JOIN products p ON p.product_id=ii.product_id
            JOIN invoices i ON i.invoice_id=ii.invoice_id WHERE i.status='completed'
            GROUP BY p.product_id,p.product_name ORDER BY units DESC LIMIT 10''')
        inventory = query('SELECT product_name,sku,stock_quantity,price,(stock_quantity*price) AS value FROM products ORDER BY product_name')
        return render_template('reports.html', sales=sales, top=top, inventory=inventory)

    @app.route('/users', methods=['GET', 'POST'])
    @login_required('admin')
    def users():
        if request.method == 'POST':
            name = request.form.get('full_name', '').strip()
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            role = request.form.get('role')
            if not (1 <= len(name) <= 100 and 3 <= len(username) <= 50 and len(password) >= 8 and role in ('admin', 'cashier')):
                flash('Check name, username, password (8+ chars), and role.', 'danger')
            else:
                db = connect()
                try:
                    cur = db.cursor()
                    try:
                        cur.execute('INSERT INTO users (full_name,username,password_hash,role) VALUES (%s,%s,%s,%s)',
                                    (name, username, generate_password_hash(password), role))
                        db.commit()
                        flash('User created.', 'success')
                    finally:
                        cur.close()
                except mysql.connector.IntegrityError:
                    db.rollback()
                    flash('Username already exists.', 'danger')
                finally:
                    db.close()
        return render_template('users.html', users=query('SELECT user_id,full_name,username,role,created_at FROM users ORDER BY user_id'))

    return app
