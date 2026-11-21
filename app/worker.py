from datetime import datetime, timezone
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.models import PriceHistory, Product
from app.notifier import send_price_drop_alert
from app.scraper import fetch_product_price

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("price_tracker.worker")


def evaluate_alert_condition(
    new_price: float,
    target_price: float,
    last_alerted_price: Optional[float],
) -> bool:
    """
    Determine if an alert email should be sent.
    Triggers ONLY when:
      1. new_price <= target_price
      AND
      2. (last_alerted_price is None OR new_price < last_alerted_price)
    This prevents duplicate alert spam while still notifying on further price drops.
    """
    if new_price > target_price:
        return False

    if last_alerted_price is None:
        return True

    return new_price < last_alerted_price


def process_single_product(
    db: Session,
    product: Product,
    price_fetcher=fetch_product_price,
    alert_notifier=send_price_drop_alert,
) -> bool:
    """
    Process price check for a single product with error isolation.
    Returns True if successfully processed, False if an error occurred.
    """
    try:
        logger.info(
            "Checking product #%d: '%s' (Target: $%.2f)",
            product.id,
            product.name,
            product.target_price,
        )

        new_price = price_fetcher(product.url, product.css_selector)
        if new_price is None:
            logger.warning(
                "Could not fetch price for product #%d ('%s'). Leaving unchanged.",
                product.id,
                product.name,
            )
            return False

        # 1. Log every fetched price to PriceHistory
        history = PriceHistory(
            product_id=product.id,
            price=new_price,
            recorded_at=datetime.now(timezone.utc),
        )
        db.add(history)

        previous_price = product.current_price

        # 2. Check alert condition
        should_alert = evaluate_alert_condition(
            new_price=new_price,
            target_price=product.target_price,
            last_alerted_price=product.last_alerted_price,
        )

        if should_alert:
            logger.info(
                "ALERT TRIGGERED for '%s'! New price $%.2f <= target $%.2f (Last alerted: %s)",
                product.name,
                new_price,
                product.target_price,
                f"${product.last_alerted_price:.2f}"
                if product.last_alerted_price is not None
                else "None",
            )
            # Dispatch email notification
            alert_notifier(
                product_name=product.name,
                product_url=product.url,
                new_price=new_price,
                target_price=product.target_price,
                previous_price=previous_price,
            )
            # Update last_alerted_price to suppress duplicates until further drop
            product.last_alerted_price = new_price

        # Update current price
        product.current_price = new_price
        db.commit()
        return True

    except Exception as exc:
        db.rollback()
        logger.error(
            "Failed processing product #%d ('%s'): %s",
            product.id,
            product.name,
            str(exc),
            exc_info=True,
        )
        return False


def run_worker() -> dict:
    """
    Main worker routine:
    Iterates active products, checks prices, updates history, and dispatches alerts.
    Isolates errors per product so one failed scrape does not abort the run.
    """
    init_db()
    db = SessionLocal()
    summary = {"total": 0, "processed": 0, "failed": 0}

    try:
        active_products = (
            db.query(Product).filter(Product.is_active == True).all()  # noqa: E712
        )
        summary["total"] = len(active_products)
        logger.info("Worker run started. Found %d active products to check.", len(active_products))

        for product in active_products:
            success = process_single_product(db, product)
            if success:
                summary["processed"] += 1
            else:
                summary["failed"] += 1

        logger.info(
            "Worker run completed: %d total, %d processed, %d failed.",
            summary["total"],
            summary["processed"],
            summary["failed"],
        )
        return summary
    finally:
        db.close()


if __name__ == "__main__":
    run_worker()
