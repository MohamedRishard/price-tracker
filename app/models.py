from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(2048), unique=True, index=True, nullable=False)
    css_selector = Column(String(512), nullable=False)
    target_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    last_alerted_price = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    price_history = relationship(
        "PriceHistory",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="desc(PriceHistory.recorded_at)",
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="price_history")
