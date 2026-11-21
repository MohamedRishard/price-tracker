from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import PriceHistory, Product, WebStore
from app.notifier import send_dashboard_summary_email
from app.scraper import fetch_product_price, inspect_product_page
from app.worker import run_worker

DASHBOARD_HTML_PATH = Path(__file__).parent / "static" / "dashboard.html"
FAVICON_SVG_PATH = Path(__file__).parent / "static" / "favicon.svg"
FAVICON_ICO_PATH = Path(__file__).parent / "static" / "favicon.ico"
FAVICON_PNG_PATH = Path(__file__).parent / "static" / "favicon.png"
TOUCH_ICON_PATH = Path(__file__).parent / "static" / "apple-touch-icon.png"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on application startup."""
    init_db()
    yield


app = FastAPI(
    title="E-Commerce Price Drop Alerting Engine API",
    description="Production-grade API to monitor product prices and trigger alerts on drops using 100% free-tier tooling.",
    version="1.0.0",
    lifespan=lifespan,
)


# --- Pydantic Schemas ---


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Product title or label")
    url: str = Field(..., description="Full URL to the product page")
    css_selector: str = Field(
        default="auto", description="CSS selector targeting the price element, or 'auto' for auto-detection"
    )
    target_price: float = Field(
        ..., gt=0, description="Target price threshold below which an alert is triggered"
    )
    currency: Optional[str] = Field(
        default="Rs. ", description="Detected or configured currency symbol (e.g. $, Rs., £, €)"
    )


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[str] = None
    target_price: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = None
    is_active: Optional[bool] = None
    css_selector: Optional[str] = None


class ProductResponse(ProductBase):
    id: int
    current_price: Optional[float] = None
    last_alerted_price: Optional[float] = None
    currency: Optional[str] = "Rs. "
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriceHistoryResponse(BaseModel):
    id: int
    product_id: int
    price: float
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SelectorTestRequest(BaseModel):
    url: str
    css_selector: Optional[str] = "auto"


class SelectorTestResponse(BaseModel):
    success: bool
    price: Optional[float] = None
    currency: Optional[str] = "Rs. "
    message: str


class LinkTestRequest(BaseModel):
    url: str
    css_selector: Optional[str] = "auto"


class LinkTestResponse(BaseModel):
    success: bool
    name: str
    price: Optional[float] = None
    currency: Optional[str] = "Rs. "
    selector: str
    message: str


class WebStoreResponse(BaseModel):
    id: int
    name: str
    domain: str
    url: str
    count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Endpoints ---


@app.get("/", response_class=FileResponse, tags=["Dashboard"], include_in_schema=False)
@app.get("/dashboard", response_class=FileResponse, tags=["Dashboard"], include_in_schema=False)
def serve_dashboard():
    """Serve the interactive web dashboard with cache-busting headers."""
    if DASHBOARD_HTML_PATH.exists():
        return FileResponse(
            DASHBOARD_HTML_PATH,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Dashboard UI file not found</h1>", status_code=404)


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon_ico():
    """Serve binary .ico favicon with SVG fallback."""
    if FAVICON_ICO_PATH.exists():
        return FileResponse(FAVICON_ICO_PATH, media_type="image/x-icon")
    if FAVICON_SVG_PATH.exists():
        return FileResponse(FAVICON_SVG_PATH, media_type="image/svg+xml")
    return HTMLResponse("", status_code=204)


@app.get("/favicon.png", include_in_schema=False)
def serve_favicon_png():
    """Serve 192x192 PNG favicon."""
    if FAVICON_PNG_PATH.exists():
        return FileResponse(FAVICON_PNG_PATH, media_type="image/png")
    return HTMLResponse("", status_code=204)


@app.get("/favicon.svg", include_in_schema=False)
def serve_favicon_svg():
    """Serve vector SVG favicon."""
    if FAVICON_SVG_PATH.exists():
        return FileResponse(FAVICON_SVG_PATH, media_type="image/svg+xml")
    return HTMLResponse("", status_code=204)


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def serve_apple_touch_icon():
    """Serve touch icon for mobile and home screen bookmarks."""
    if TOUCH_ICON_PATH.exists():
        return FileResponse(TOUCH_ICON_PATH, media_type="image/png")
    return HTMLResponse("", status_code=204)


@app.get("/stores", response_model=List[WebStoreResponse], tags=["Stores"])
def list_stores(db: Session = Depends(get_db)):
    """Retrieve all supported web stores from the database with active product count."""
    stores = db.query(WebStore).order_by(WebStore.id.asc()).all()
    products = db.query(Product).all()

    results = []
    for store in stores:
        cnt = sum(1 for p in products if p.url and store.domain.lower() in p.url.lower())
        results.append(
            WebStoreResponse(
                id=store.id,
                name=store.name,
                domain=store.domain,
                url=store.url,
                count=cnt,
                created_at=store.created_at or datetime.utcnow(),
            )
        )
    return results


@app.post("/api/test-link", response_model=LinkTestResponse, tags=["Scraper"])
def test_link(payload: LinkTestRequest):
    """Inspect and test a product link directly, auto-detecting name, price, and selector."""
    result = inspect_product_page(payload.url, payload.css_selector, timeout=12.0)
    return LinkTestResponse(**result)


@app.post("/api/test-selector", response_model=SelectorTestResponse, tags=["Scraper"])
def test_selector(payload: SelectorTestRequest):
    """Test extracting a price from a live URL using a CSS selector or auto-detection."""
    price = fetch_product_price(payload.url, payload.css_selector or "auto", max_retries=1, timeout=8.0)
    if price is not None:
        return SelectorTestResponse(
            success=True,
            price=price,
            message=f"Successfully extracted price: ${price:,.2f}",
        )
    return SelectorTestResponse(
        success=False,
        price=None,
        message="Selector not found or page could not be parsed.",
    )


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint for container probes and uptime monitors."""
    return {"status": "healthy", "service": "price-drop-alerting-engine"}


@app.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Products"],
)
def create_product(product_in: ProductCreate, db: Session = Depends(get_db)):
    """Create a new product to be tracked for price drops."""
    # Check if URL already tracked
    existing = db.query(Product).filter(Product.url == product_in.url).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A tracked product with this URL already exists (ID: {existing.id})",
        )

    product = Product(
        name=product_in.name,
        url=product_in.url,
        css_selector=product_in.css_selector,
        target_price=product_in.target_price,
        currency=product_in.currency or "Rs. ",
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    # Auto-register store in database if new domain
    try:
        parsed = urlparse(product_in.url)
        netloc = parsed.netloc.lower()
        clean_domain = netloc[4:] if netloc.startswith("www.") else netloc
        if clean_domain:
            existing_store = (
                db.query(WebStore)
                .filter(WebStore.domain.ilike(f"%{clean_domain}%"))
                .first()
            )
            if not existing_store:
                parts = clean_domain.split(".")
                brand = (
                    parts[0]
                    if parts[0] not in ("buy", "shop", "store", "m")
                    else (parts[1] if len(parts) > 1 else parts[0])
                )
                store_name = brand.capitalize()
                store_url = f"{parsed.scheme or 'https'}://{netloc}"
                new_store = WebStore(name=store_name, domain=clean_domain, url=store_url)
                db.add(new_store)
                db.commit()
    except Exception:
        # Avoid failing product creation if auto-store registration has an issue
        db.rollback()

    return product


@app.get(
    "/products",
    response_model=List[ProductResponse],
    tags=["Products"],
)
def list_products(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Retrieve all tracked products with optional pagination and active status filtering."""
    query = db.query(Product)
    if is_active is not None:
        query = query.filter(Product.is_active == is_active)
    products = query.offset(skip).limit(limit).all()
    return products


@app.get(
    "/products/{product_id}",
    response_model=ProductResponse,
    tags=["Products"],
)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Retrieve details for a single tracked product."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found",
        )
    return product


@app.put(
    "/products/{product_id}",
    response_model=ProductResponse,
    tags=["Products"],
)
def update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
):
    """Update a tracked product's name, target price threshold, or active status."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found",
        )

    if product_in.name is not None:
        product.name = product_in.name.strip()
    if product_in.url is not None:
        product.url = product_in.url.strip()
    if product_in.target_price is not None:
        product.target_price = product_in.target_price
    if product_in.currency is not None:
        product.currency = product_in.currency.strip()
    if product_in.is_active is not None:
        product.is_active = product_in.is_active
    if product_in.css_selector is not None:
        product.css_selector = product_in.css_selector.strip()

    db.commit()
    db.refresh(product)
    return product


@app.get(
    "/products/{product_id}/history",
    response_model=List[PriceHistoryResponse],
    tags=["Price History"],
)
def get_product_history(
    product_id: int,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Retrieve chronological price history entries for a given product."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found",
        )

    history = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.recorded_at.desc())
        .limit(limit)
        .all()
    )
    return history


@app.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Products"],
)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Delete a tracked product and its associated price history."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found",
        )
    db.delete(product)
    db.commit()
    return None


@app.post(
    "/worker/run",
    tags=["Worker"],
    summary="Trigger worker run manually",
)
def trigger_worker_run(db: Session = Depends(get_db)):
    """Manually invoke the price scraping worker, check drops, and send summary email."""
    summary = run_worker()
    products = db.query(Product).order_by(Product.id.asc()).all()
    email_sent = send_dashboard_summary_email(products)
    return {"status": "completed", "summary": summary, "email_sent": email_sent}
