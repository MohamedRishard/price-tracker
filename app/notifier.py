import logging
import os
from typing import Optional
from dotenv import load_dotenv
import resend

load_dotenv()

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
ALERT_RECIPIENT_EMAIL = os.getenv("ALERT_RECIPIENT_EMAIL")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "onboarding@resend.dev")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def build_email_html(
    product_name: str,
    product_url: str,
    new_price: float,
    target_price: float,
    previous_price: Optional[float] = None,
    currency: str = "Rs. ",
) -> str:
    """Build a modern responsive HTML email for price drop alerts."""
    prev_price_display = (
        f'<span style="text-decoration: line-through; color: #888888; font-size: 18px; margin-right: 12px;">{currency}{previous_price:,.2f}</span>'
        if previous_price is not None
        else ""
    )

    savings_badge = ""
    if previous_price and previous_price > new_price:
        pct_drop = round(((previous_price - new_price) / previous_price) * 100)
        savings_badge = f"""
        <div style="display: inline-block; background-color: #e6f4ea; color: #137333; font-weight: bold; font-size: 13px; padding: 4px 10px; border-radius: 12px; margin-bottom: 12px;">
            Save {pct_drop}% ({currency}{(previous_price - new_price):,.2f} off)
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Price Drop Alert</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6f9fc; margin: 0; padding: 24px; color: #1a1a1a;">
      <div style="max-width: 560px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; border: 1px solid #e0e6ed; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.04);">
        <!-- Header -->
        <div style="background-color: #10b981; padding: 20px 24px; color: #ffffff;">
          <h1 style="margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.2px;">Price Drop Alert!</h1>
        </div>
        <!-- Body -->
        <div style="padding: 24px;">
          {savings_badge}
          <h2 style="margin: 0 0 16px 0; font-size: 18px; line-height: 1.4; color: #111827;">{product_name}</h2>
          
          <div style="background-color: #f9fafb; border-radius: 6px; padding: 16px; margin-bottom: 24px;">
            <div style="margin-bottom: 8px;">
              <span style="font-size: 13px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Current Price</span>
              <div style="margin-top: 4px;">
                {prev_price_display}
                <span style="font-size: 26px; font-weight: 700; color: #059669;">{currency}{new_price:,.2f}</span>
              </div>
            </div>
            <div style="border-top: 1px solid #e5e7eb; padding-top: 10px; margin-top: 10px; font-size: 14px; color: #4b5563;">
              <strong>Your Target Price:</strong> {currency}{target_price:,.2f}
            </div>
          </div>

          <!-- CTA Button -->
          <div style="text-align: center; margin: 28px 0 12px 0;">
            <a href="{product_url}" target="_blank" style="background-color: #2563eb; color: #ffffff; text-decoration: none; padding: 12px 28px; font-size: 15px; font-weight: 600; border-radius: 6px; display: inline-block;">
              View Product on Store &rarr;
            </a>
          </div>
        </div>

        <!-- Footer -->
        <div style="background-color: #f9fafb; border-top: 1px solid #e5e7eb; padding: 14px 24px; font-size: 12px; color: #9ca3af; text-align: center;">
          Sent by automated E-Commerce Price Drop Alerting Engine &bull; 100% Free Tier Architecture
        </div>
      </div>
    </body>
    </html>
    """


def send_price_drop_alert(
    product_name: str,
    product_url: str,
    new_price: float,
    target_price: float,
    previous_price: Optional[float] = None,
    recipient_email: Optional[str] = None,
    currency: str = "Rs. ",
) -> bool:
    """
    Send a price-drop HTML email alert via Resend SDK.
    Returns True if sent successfully, False otherwise.
    """
    to_email = recipient_email or ALERT_RECIPIENT_EMAIL
    api_key = os.getenv("RESEND_API_KEY")

    if not api_key or api_key.startswith("re_123456789"):
        logger.warning(
            "Resend API key not configured or using placeholder. Skipping email dispatch for '%s'.",
            product_name,
        )
        return False

    if not to_email:
        logger.warning("ALERT_RECIPIENT_EMAIL not configured. Cannot send price drop email.")
        return False

    resend.api_key = api_key

    html_content = build_email_html(
        product_name=product_name,
        product_url=product_url,
        new_price=new_price,
        target_price=target_price,
        previous_price=previous_price,
        currency=currency,
    )

    params: resend.Emails.SendParams = {
        "from": SENDER_EMAIL,
        "to": [to_email],
        "subject": f"Price Drop Alert: {product_name} is now {currency}{new_price:,.2f}!",
        "html": html_content,
    }

    try:
        response = resend.Emails.send(params)
        logger.info("Alert email sent successfully for '%s'. Response: %s", product_name, response)
        return True
    except Exception as exc:
        logger.error("Failed to send price drop email for '%s': %s", product_name, str(exc))
        return False
