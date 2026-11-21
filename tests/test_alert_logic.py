import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PriceHistory, Product
from app.scraper import parse_price
from app.worker import evaluate_alert_condition, process_single_product


# --- Fixtures ---


@pytest.fixture
def db_session():
    """Create an isolated in-memory SQLite database session for unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


# --- Price Parser Tests ---


class TestPriceParser:
    def test_parse_standard_dollar(self):
        assert parse_price("$19.99") == 19.99

    def test_parse_with_thousands_comma(self):
        assert parse_price("$1,299.99") == 1299.99
        assert parse_price("USD 2,450.00") == 2450.00

    def test_parse_european_format(self):
        assert parse_price("49,99 €") == 49.99
        assert parse_price("€ 12,50") == 12.50

    def test_parse_whitespace_and_labels(self):
        assert parse_price("   Price: $99.50 \n") == 99.50
        assert parse_price("Now only $ 0.99!") == 0.99

    def test_parse_multiple_dots(self):
        # E.g. formatting artifacts like 1.299.99 -> 1299.99
        assert parse_price("1.299.99") == 1299.99

    def test_parse_invalid_or_missing(self):
        assert parse_price("") is None
        assert parse_price(None) is None
        assert parse_price("Out of Stock") is None
        assert parse_price("Free") is None
        assert parse_price("35% Off") is None
        assert parse_price("-20%") is None


# --- Duplicate Alert Suppression Tests ---


class TestAlertConditionLogic:
    def test_alert_first_time_below_target(self):
        """When no prior alert exists and price is below target -> Trigger Alert."""
        assert (
            evaluate_alert_condition(
                new_price=80.0,
                target_price=100.0,
                last_alerted_price=None,
            )
            is True
        )

    def test_alert_first_time_exact_target(self):
        """When price equals target price exactly -> Trigger Alert."""
        assert (
            evaluate_alert_condition(
                new_price=100.0,
                target_price=100.0,
                last_alerted_price=None,
            )
            is True
        )

    def test_suppress_when_above_target(self):
        """When price is above target -> Suppress Alert."""
        assert (
            evaluate_alert_condition(
                new_price=105.0,
                target_price=100.0,
                last_alerted_price=None,
            )
            is False
        )
        assert (
            evaluate_alert_condition(
                new_price=105.0,
                target_price=100.0,
                last_alerted_price=90.0,
            )
            is False
        )

    def test_suppress_duplicate_alert_at_same_price(self):
        """
        Anti-Spam: When price is below target but identical to last alerted price
        -> Suppress duplicate alert.
        """
        assert (
            evaluate_alert_condition(
                new_price=80.0,
                target_price=100.0,
                last_alerted_price=80.0,
            )
            is False
        )

    def test_suppress_when_price_rebounds_slightly_below_target(self):
        """
        Anti-Spam: Price was previously alerted at $70. It now rises to $75
        (still below target $100). Should NOT trigger duplicate alert.
        """
        assert (
            evaluate_alert_condition(
                new_price=75.0,
                target_price=100.0,
                last_alerted_price=70.0,
            )
            is False
        )

    def test_trigger_on_further_price_drop(self):
        """
        When price was alerted at $80, but drops even further to $75
        -> Trigger Alert!
        """
        assert (
            evaluate_alert_condition(
                new_price=75.0,
                target_price=100.0,
                last_alerted_price=80.0,
            )
            is True
        )


# --- Worker Processing & Fault Isolation Tests ---


class TestWorkerProcessing:
    def test_first_price_drop_triggers_email_and_history(self, db_session):
        product = Product(
            name="Mechanical Keyboard",
            url="https://example.com/keyboard",
            css_selector=".price",
            target_price=100.0,
            current_price=120.0,
            last_alerted_price=None,
            is_active=True,
        )
        db_session.add(product)
        db_session.commit()

        mock_fetcher = MagicMock(return_value=85.0)
        mock_notifier = MagicMock(return_value=True)

        success = process_single_product(
            db_session,
            product,
            price_fetcher=mock_fetcher,
            alert_notifier=mock_notifier,
        )

        assert success is True
        assert product.current_price == 85.0
        assert product.last_alerted_price == 85.0
        mock_notifier.assert_called_once_with(
            product_name="Mechanical Keyboard",
            product_url="https://example.com/keyboard",
            new_price=85.0,
            target_price=100.0,
            previous_price=120.0,
            currency="Rs. ",
        )

        # Check PriceHistory recorded
        history = (
            db_session.query(PriceHistory).filter(PriceHistory.product_id == product.id).all()
        )
        assert len(history) == 1
        assert history[0].price == 85.0

    def test_subsequent_duplicate_check_suppresses_email(self, db_session):
        product = Product(
            name="Mechanical Keyboard",
            url="https://example.com/keyboard",
            css_selector=".price",
            target_price=100.0,
            current_price=85.0,
            last_alerted_price=85.0,
            is_active=True,
        )
        db_session.add(product)
        db_session.commit()

        mock_fetcher = MagicMock(return_value=85.0)
        mock_notifier = MagicMock(return_value=True)

        success = process_single_product(
            db_session,
            product,
            price_fetcher=mock_fetcher,
            alert_notifier=mock_notifier,
        )

        assert success is True
        # Email notifier should NOT be called because price has not dropped below 85.0
        mock_notifier.assert_not_called()

        # Second price check still recorded in history
        history = (
            db_session.query(PriceHistory).filter(PriceHistory.product_id == product.id).all()
        )
        assert len(history) == 1
        assert history[0].price == 85.0

    def test_failed_scrape_does_not_abort_or_corrupt_state(self, db_session):
        product = Product(
            name="Rare Vintage Watch",
            url="https://example.com/watch",
            css_selector=".price",
            target_price=500.0,
            current_price=600.0,
            last_alerted_price=None,
            is_active=True,
        )
        db_session.add(product)
        db_session.commit()

        mock_fetcher = MagicMock(return_value=None)  # Scraper could not find element
        mock_notifier = MagicMock()

        success = process_single_product(
            db_session,
            product,
            price_fetcher=mock_fetcher,
            alert_notifier=mock_notifier,
        )

        assert success is False
        assert product.current_price == 600.0
        assert product.last_alerted_price is None
        mock_notifier.assert_not_called()

        # No history entry created on failed fetch
        history = (
            db_session.query(PriceHistory).filter(PriceHistory.product_id == product.id).all()
        )
        assert len(history) == 0

    def test_exception_in_product_is_isolated(self, db_session):
        product = Product(
            name="Faulty Product",
            url="https://example.com/faulty",
            css_selector=".price",
            target_price=50.0,
            current_price=70.0,
            is_active=True,
        )
        db_session.add(product)
        db_session.commit()

        def exploding_fetcher(*args, **kwargs):
            raise RuntimeError("Network cable disconnected!")

        success = process_single_product(
            db_session,
            product,
            price_fetcher=exploding_fetcher,
        )

        assert success is False
        # Ensure session is still usable and not blocked in transaction
        assert db_session.is_active

    def test_summary_email_with_failed_items(self, monkeypatch):
        from app.notifier import send_dashboard_summary_email
        from unittest.mock import MagicMock
        import resend

        monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
        monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "test@example.com")
        mock_send = MagicMock(return_value={"id": "email_123"})
        monkeypatch.setattr(resend.Emails, "send", mock_send)

        dummy_product = MagicMock()
        dummy_product.id = 1
        dummy_product.name = "Test Item"
        dummy_product.url = "https://example.com/item"
        dummy_product.current_price = 100.0
        dummy_product.target_price = 90.0
        dummy_product.currency = "Rs. "

        failed_items = [
            {
                "id": 2,
                "name": "Failing Store Item",
                "url": "https://failing-store.com/item",
                "current_price": 500.0,
                "currency": "Rs. ",
                "reason": "403 Forbidden - anti-bot challenge",
            }
        ]

        result = send_dashboard_summary_email([dummy_product], failed_items=failed_items)
        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Scrape Issue" in call_args["subject"]
        assert "Failing Store Item" in call_args["html"]
        assert "403 Forbidden" in call_args["html"]
