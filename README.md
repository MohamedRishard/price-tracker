# 🛒 PriceDrop Radar &bull; Production Price Tracker & Alerting Engine

A production-grade, modular Python application engineered to monitor e-commerce product prices, record historical pricing trends, and dispatch real-time email alerts when prices drop below target thresholds. Built completely on **100% free-tier architecture** with Neon Serverless PostgreSQL, Resend Email API, GitHub Actions 6-hour cron, and FastAPI.

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
| Monitored Stores | <-------+  app.worker   | -----> | Resend Email API     |
| (10+ Stores)     | (httpx) |  Price Runner |        | (Alert & Report)     |
+------------------+         +-------+-------+        +----------------------+
                                     |
                                     v
+------------------+         +---------------+
| FastAPI Web App  | <-----> | Neon Postgres |
| (app.main + UI)  | (SQLA)  | (Serverless)  |
+------------------+         +---------------+
```

| Component | Free-Tier Service | Free Quota / Feature |
| :--- | :--- | :--- |
| **Database** | [Neon Serverless PostgreSQL](https://neon.tech) | 0.5 GiB storage, connection pooling, auto-suspend |
| **Automation** | [GitHub Actions](https://github.com/features/actions) | 2,000 runner minutes/month running scheduled cron jobs (`0 */6 * * *`) |
| **Hosting** | [Render](https://render.com) | 750 free web service instance hours/month with public HTTPS |
| **Email Notifier** | [Resend](https://resend.com) | 3,000 transactional emails/month (100 emails/day) |
| **Scraper** | `httpx` + `BeautifulSoup4` (`lxml`) | High-resilience scraping with realistic headers, cookies, and backoff |
| **Web Dashboard** | Single-Page App (SPA) | Served directly from FastAPI with Tailwind CSS, Chart.js, mobile responsiveness |

---

## 🌟 Key Features

1. **100% URL-First Tracking**:
   - Simply paste any product link. Title, price, and selector are automatically detected. No CSS selectors needed.
2. **Live Exchange Rate & Rupee Standardization**:
   - Foreign currencies (such as USD `$` from Amazon) are automatically converted to Sri Lankan Rupees (`Rs. `) in real-time using live rates (~332 LKR/$). Kapruka and local stores are parsed directly in Sri Lankan Rupees (e.g. `Rs. 45,000.00`).
3. **Interactive Forest & Gold Dashboard**:
   - Styled with a custom nature-inspired palette: `#15370D` (Forest Pine), `#728E6D` (Moss Sage), `#E5CD82` (Warm Sand Gold), and `#FFF2B4` (Soft Cream Butter). Includes KPI metrics, search filtering, target editing, and interactive Chart.js price trend visualization.
4. **Database-Backed Web Stores Navigation**:
   - Stores the 10 core monitored stores (Amazon, Kapruka, BigDeals, Mo.lk, Pettah Kade, Ikman, Takas, eKade, OnlineKade, eShop.lk) directly in PostgreSQL. Automatically registers and persists any new store domain whenever a new product is added.
5. **Dual Email Notification Engine (Resend)**:
   - **Drop Alerts**: Instant notification when a product price drops at or below your target threshold (with anti-duplicate suppression).
   - **Live Snapshot Email**: Dispatches a full status report table of all monitored items directly to your inbox (`ALERT_RECIPIENT_EMAIL`) whenever you click **"Check Prices Now"**.
6. **Universal Cross-Browser Favicon & Mobile PWA**:
   - Features standard binary `favicon.ico`, high-res `favicon.png`, `apple-touch-icon.png`, and `favicon.svg` for seamless icon rendering on Render, mobile browsers, and desktop tabs.

---

## 📁 Project Structure

```
├── .github/
│   └── workflows/
│       └── check_prices.yml      # GitHub Actions 6-hour cron and manual trigger
├── app/
│   ├── __init__.py
│   ├── database.py               # SQLAlchemy engine, session maker, Neon connection pooling
│   ├── models.py                 # Product, PriceHistory, and WebStore SQLAlchemy ORM models
│   ├── scraper.py                # Resilient scraper with live USD->LKR conversion & Kapruka priority
│   ├── notifier.py               # Resend email client with drop alerts & on-demand snapshot reports
│   ├── worker.py                 # Core evaluation loop with anti-spam alert logic
│   ├── main.py                   # FastAPI REST API, store management & multi-format favicon routing
│   └── static/
│       ├── dashboard.html        # Interactive single-page web dashboard (Custom Forest & Gold palette)
│       ├── favicon.ico           # Binary multi-size .ico favicon (16x16, 32x32, 48x48, 64x64)
│       ├── favicon.png           # 192x192 PNG high-res favicon
│       ├── apple-touch-icon.png  # 192x192 Apple touch icon for mobile home screens
│       └── favicon.svg           # Brand vector SVG favicon
├── tests/
│   ├── __init__.py
│   ├── test_alert_logic.py       # Pytest suite for parser, suppression, and worker isolation
│   └── test_api.py               # FastAPI endpoint integration tests including /stores and favicons
├── .env.example                  # Environment configuration template
├── render.yaml                   # 1-Click Render blueprint configuration
├── requirements.txt              # Production and testing Python dependencies
└── README.md                     # Project documentation
```

---

## 🚀 Getting Started Locally

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/MohamedRishard/price-tracker.git
cd price-tracker

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the project root:
```env
DATABASE_URL=postgresql://[user]:[password]@[neon_hostname]/neondb?sslmode=require
RESEND_API_KEY=re_your_api_key_here
ALERT_RECIPIENT_EMAIL=your_email@gmail.com
PORT=8000
HOST=0.0.0.0
```

### 4. Run the Web Dashboard
```powershell
uvicorn app.main:app --reload
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

### 5. Run Price Scraper Worker Locally
```powershell
python -m app.worker
```

---

## ☁️ Cloud Deployment

### Deploy to Render (Free Web Service)
1. Sign in to [Render](https://dashboard.render.com/) with GitHub.
2. Click **New +** $\rightarrow$ **Web Service** $\rightarrow$ Connect `MohamedRishard/price-tracker`.
3. Set:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: `Free`
4. Add your Environment Variables (`DATABASE_URL`, `RESEND_API_KEY`, `ALERT_RECIPIENT_EMAIL`, `PYTHON_VERSION=3.11.9`).
5. Render deploys a permanent public HTTPS URL (e.g. `https://price-tracker-xxxx.onrender.com`) that you can open and bookmark on any phone or PC!

### Automated 6-Hour Background Tracking (GitHub Actions)
1. In your GitHub repository, go to **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**.
2. Add your 3 secrets: `DATABASE_URL`, `RESEND_API_KEY`, `ALERT_RECIPIENT_EMAIL`.
3. GitHub Actions will automatically run every 6 hours (`00:00, 06:00, 12:00, 18:00 UTC`), check prices, update database history, and alert your email on drops.
4. You can also trigger it on-demand from the **Actions** tab $\rightarrow$ **Run workflow**.

---

## 🧪 Testing

Run the automated test suite covering price parsing, European formats, anti-spam suppression, and API endpoints:
```powershell
pytest -v
```

---

## 📄 License
This project is open-source and available under the MIT License.
