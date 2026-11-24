# RetailFlow — Retail Inventory & Billing System

Flask + MySQL MVP for Agile final jury. Implements product management, stock receipts/adjustments with movement history, POS checkout, invoices, stock deduction, low-stock alerts, sales reports and admin/cashier roles.

## Windows / VS Code installation

1. **Back up your existing project** (especially `.env` and your database). Do not overwrite `.env`.
2. Copy `app`, `templates`, `static`, `run.py`, `requirements.txt`, `tests` into your existing `Retail_Inventory_System` folder. **Replace** the previous `app/__init__.py`; the previous standalone `templates/add_product.html` can remain unused.
3. Activate virtual environment: `venv\Scripts\activate` (PowerShell: `.\venv\Scripts\Activate.ps1`).
4. Run `pip install -r requirements.txt`.
5. Keep your existing `.env`; add `SECRET_KEY=` with a random value. You can generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
6. Confirm the seven MySQL tables exist and match the original jury setup. The application uses `users`, `products`, `purchases`, `purchase_items`, `invoices`, `invoice_items`, `stock_movements`. No schema migration is needed if you created them using the supplied SQL.
7. Run `python run.py`, visit `http://127.0.0.1:5000/setup` and create the first admin account. **Only available if the `users` table is empty**.
8. Sign in and navigate from the menu. Create a cashier account under Users.
9. Run helper unit tests: `python -m unittest discover -s tests -v`.

## Jury demonstration

1. Admin login, create `Notebook` SKU `NOTE001`, price ₹50, opening stock 0, threshold 5.
2. Stock → purchase 10 units from `ABC Supplier` at ₹30 each. Verify 10 available and movement history.
3. Users → create a cashier. Logout and login as cashier.
4. Billing → choose Notebook quantity 6, discount 10%, tax 5%, generate receipt. Subtotal ₹300, discount ₹30, tax ₹13.50, total ₹283.50.
5. Print invoice, view Invoices list, check product stock now 4, and view low-stock alert.
6. Admin login → Reports → daily revenue and units sold.
7. Try to bill 5 more notebooks: insufficient stock; no invoice should be created.
8. Attempt duplicate SKU: blocked; try negative stock adjustment: blocked; attempt 101% discount: blocked.

## Agile artifacts to prepare

- Sprint 1: Product catalog, stock receipts and adjustments, admin access.
- Sprint 2: Cashier login, cart, discount/tax, unique invoices, atomic stock deduction.
- Sprint 3: Alerts, reports, tests, defect log, Sprint Review and Retrospective.
- Backlog: multi-branch analytics (future release, not implemented).
- Jira/Trello: To Do, In Progress, Testing, Done; stories, estimates, acceptance criteria, assignees.
- Show actual board dates/velocity, screenshots of working demo, Git commit history, and test evidence. Do not fabricate past sprint history.

## Important limitations / future work

This is a **local demonstration MVP**, not a production-hardened retail platform. Before deployment, implement CSRF protection, HTTPS, rate limiting, stronger session/security settings, centralized error handling, comprehensive integration/concurrency tests, backups, and secure secrets management. Checkout locks products in ascending ID order to prevent overselling. A session token prevents simple double submissions, but this is not a persistent payment idempotency mechanism. Stock changes are audited, but there is no dedicated purchase cancellation workflow. Reports are basic and exclude multi-branch analytics. Prices use `DECIMAL` and rounding; discount and tax are applied to the subtotal (tax after discount).
