# 🛒 E-Commerce Price Drop Alerting Engine

A production-grade, modular Python backend engineered to monitor e-commerce product prices, store historical pricing trends, and dispatch real-time email alerts when prices drop below target thresholds. Built with **100% free-tier services**.

---

## ⚡ 100% Free-Tier Architecture

```
                      +-----------------------------+
                      |   GitHub Actions (Cron)     |
                      |      0 */6 * * *            |
                      +--------------+--------------+
                                     |
                                     v
+------------------+         +---------------+        +----------------------+
| Target E-Comm    | <-------+  app.worker   | -----> | Resend Email API     |
| Product Pages    | (httpx) |  Price Runner |        | (HTML Alert Email)   |
+------------------+         +-------+-------+        +----------------------+
                                     |
                                     v
+------------------+         +---------------+
| FastAPI App      | <-----> | Neon Postgres |
| (app.main)       | (SQLA)  | (Serverless)  |
+------------------+         +---------------+
```

| Component | Free-Tier Service | Free Quota / Feature |
| :--- | :--- | :--- |
| **Database** | [Neon Serverless PostgreSQL](https://neon.tech) | 0.5 GiB storage, connection pooling, auto-suspend |
| **Automation** | [GitHub Actions](https://github.com/features/actions) | 2,000 runner minutes/month running scheduled cron jobs (`0 */6 * * *`) |
| **Email Notifier** | [Resend](https://resend.com) | 3,000 transactional emails/month (100 emails/day) |
| **Scraper** | `httpx` + `BeautifulSoup4` (`lxml`) | Resilient HTTP/2 client with backoff and realistic headers |
| **REST API** | [FastAPI](https://fastapi.tiangolo.com) | Modern ASGI web framework with Pydantic validation |
| **Testing** | `pytest` | Isolated unit testing with in-memory SQLite fixtures |

---

## 📁 Project Structure

```
├── .github/
│   └── workflows/
│       └── check_prices.yml      # Cron workflow (every 6 hours + manual dispatch)
├── app/
│   ├── __init__.py
│   ├── database.py               # SQLAlchemy engine, session maker, Neon pooling
│   ├── models.py                 # Product and PriceHistory SQLAlchemy ORM models
│   ├── scraper.py                # Scraper with headers, backoff & regex price extraction
│   ├── notifier.py               # Resend email client with rich HTML email templates
│   ├── worker.py                 # Core evaluation loop with anti-spam alert logic
│   └── main.py                   # FastAPI application with Pydantic CRUD endpoints
├── tests/
│   ├── __init__.py
│   └── test_alert_logic.py       # Pytest suite for parser, suppression, and worker isolation
├── .env.example                  # Environment configuration template
├── requirements.txt              # Production and testing dependencies
├── Dockerfile                    # Container configuration for production deployment
└── README.md                     # Documentation
```

---

## 🧠 Core Engineering Highlights

### 1. Anti-Spam Duplicate Alert Suppression
To prevent inbox flooding when a product remains at or slightly rebounds while below target, the alert condition enforces:

$$\text{should\_alert} = (\text{new\_price} \le \text{target\_price}) \land (\text{last\_alerted\_price is None} \lor \text{new\_price} < \text{last\_alerted\_price})$$

- **Initial Drop**: When price drops below `target_price`, email triggers and `last_alerted_price` is updated.
- **Identical Price Scrapes**: If the price remains identical on future runs, no email is sent.
- **Upward Fluctuation**: If price rises slightly (e.g. \$70 $\to$ \$75, target \$100), no duplicate alert is triggered.
- **Further Price Drop**: If price drops lower than the previous alert (e.g. \$70 $\to$ \$65), a new alert is immediately dispatched.

### 2. Scraper Resilience
- **Realistic Browser Fingerprint**: Injects desktop `User-Agent`, `Accept-Language`, `Sec-Ch-Ua`, and navigation headers.
- **Exponential Backoff**: 3 retry attempts with exponential backoff delays ($1\text{s}, 2\text{s}, 4\text{s}$) handling rate limits and transient connection resets.
- **Regex Price Extraction**: Strips currency signs, handles thousands commas (`$1,299.99` $\to$ `1299.99`), European commas (`49,99 €` $\to$ `49.99`), and ignores trailing textual artifacts.

### 3. Worker Fault Isolation
Individual product checks execute inside isolated try-catch blocks. If a product URL returns a 404, times out, or changes markup, the worker logs the error and continues to the next product without crashing the batch.

---

## 🚀 Quickstart & Setup

### Prerequisites
- Python 3.10+ (or Docker)
- Git

### 1. Clone & Set Up Virtual Environment

```bash
git clone <repo-url>
cd "Price Tracker"

python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```ini
# Neon PostgreSQL Connection String
DATABASE_URL=postgresql://neondb_owner:YOUR_PASSWORD@ep-sample.us-east-2.aws.neon.tech/neondb?sslmode=require

# Resend API Key
RESEND_API_KEY=re_your_api_key_here

# Recipient Email for Price Alerts
ALERT_RECIPIENT_EMAIL=your-email@example.com
```

> **Note**: If `DATABASE_URL` is omitted, the application automatically falls back to local SQLite (`sqlite:///./price_tracker.db`).

---

## 🏃 Running the Application

### 1. Start the FastAPI Server & Interactive Dashboard

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Open the **Interactive Web Dashboard** in your browser:  
  👉 **[http://localhost:8000/](http://localhost:8000/)**
- Access Swagger UI interactive docs at:  
  👉 [http://localhost:8000/docs](http://localhost:8000/docs)

### 2. Run the Price Check Worker Manually

```bash
python -m app.worker
```

---

## 📡 REST API Reference

### Create a Tracked Product
`POST /products`
```bash
curl -X POST "http://localhost:8000/products" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "Sony WH-1000XM5 Headphones",
       "url": "https://example.com/products/sony-wh1000xm5",
       "css_selector": ".product-price-current",
       "target_price": 299.99
     }'
```

### List Tracked Products
`GET /products?is_active=true`
```bash
curl "http://localhost:8000/products"
```

### Get Product Details
`GET /products/{id}`
```bash
curl "http://localhost:8000/products/1"
```

### View Historical Price Logs
`GET /products/{id}/history`
```bash
curl "http://localhost:8000/products/1/history"
```

### Delete Tracked Product
`DELETE /products/{id}`
```bash
curl -X DELETE "http://localhost:8000/products/1"
```

### Trigger Manual Worker Run via API
`POST /worker/run`
```bash
curl -X POST "http://localhost:8000/worker/run"
```

---

## ⏰ Automated Scheduling with GitHub Actions

The workflow in `.github/workflows/check_prices.yml` runs every 6 hours automatically.

To configure:
1. Push this repository to GitHub.
2. Go to **Settings > Secrets and variables > Actions**.
3. Add the following repository secrets:
   - `DATABASE_URL`: Your Neon PostgreSQL connection string.
   - `RESEND_API_KEY`: Your Resend API key.
   - `ALERT_RECIPIENT_EMAIL`: Your alert destination email address.
4. Test run anytime by clicking **Actions > Check Product Prices & Alert > Run workflow**.

---

## 🧪 Running Unit Tests

Run the complete test suite with `pytest`:

```bash
pytest -v tests/test_alert_logic.py
```

All tests run against in-memory SQLite and mock external network requests, verifying:
- Duplicate alert suppression edge cases.
- Regex price cleaning for multiple global currencies.
- Scraper fault isolation across multi-product batches.

---

## 🐳 Docker Deployment

Build and run using Docker:

```bash
# Build Docker image
docker build -t price-drop-engine .

# Run container
docker run -d -p 8000:8000 --env-file .env --name price-tracker price-drop-engine
```
