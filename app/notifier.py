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


def send_dashboard_summary_email(
    products: list,
    failed_items: Optional[list] = None,
    recipient_email: Optional[str] = None,
) -> bool:
    """
    Send a full status summary email table of all currently tracked products
    whenever 'Check Prices Now' is manually invoked, prominently reporting
    any sites where scraping failed.
    """
    to_email = recipient_email or ALERT_RECIPIENT_EMAIL
    api_key = os.getenv("RESEND_API_KEY")

    if not api_key or api_key.startswith("re_123456789") or not to_email:
        logger.warning("Resend credentials not configured. Skipping summary email.")
        return False

    resend.api_key = api_key

    failed_items = failed_items or []
    failed_ids = {item["id"] for item in failed_items if "id" in item}

    # Build failed sites warning banner if any item failed
    failed_section_html = ""
    if failed_items:
        failed_rows = ""
        for fi in failed_items:
            f_curr = fi.get("currency", "Rs. ") or "Rs. "
            pres_price = f"{f_curr}{fi['current_price']:,.2f}" if fi.get("current_price") is not None else "Not set"
            failed_rows += f"""
            <tr style="border-bottom: 1px solid #fecaca;">
              <td style="padding: 8px 12px; vertical-align: top; font-weight: 600; color: #991b1b;">
                <a href="{fi['url']}" target="_blank" style="color: #991b1b; text-decoration: underline;">{fi['name']}</a>
              </td>
              <td style="padding: 8px 12px; vertical-align: top; color: #7f1d1d;">
                {pres_price}
              </td>
              <td style="padding: 8px 12px; vertical-align: top; color: #7f1d1d; font-size: 11px;">
                {fi.get('reason', 'Site timeout or anti-bot challenge')}
              </td>
            </tr>
            """

        failed_section_html = f"""
        <div style="background-color: #FEF2F2; border: 1px solid #F87171; border-radius: 10px; padding: 16px 20px; margin-bottom: 22px;">
          <h2 style="margin: 0 0 6px 0; color: #991B1B; font-size: 15px; font-weight: 700;">
            ⚠️ {len(failed_items)} Store(s) Encountered Scraping Issues
          </h2>
          <p style="margin: 0 0 10px 0; font-size: 13px; color: #7F1D1D; line-height: 1.45;">
            The following product page(s) could not be refreshed on this check (due to temporary store rate-limiting, Cloudflare/Shopify challenge, or network timeout).
            Their previous database prices were safely preserved and the engine will retry automatically on the next scheduled check.
          </p>
          <table style="width: 100%; border-collapse: collapse; font-size: 12px; background: #ffffff; border-radius: 6px; overflow: hidden; border: 1px solid #FECACA;">
            <thead>
              <tr style="background: #FEE2E2; text-align: left; color: #991B1B; font-size: 11px; text-transform: uppercase;">
                <th style="padding: 8px 12px;">Product</th>
                <th style="padding: 8px 12px;">Preserved Price</th>
                <th style="padding: 8px 12px;">Notice</th>
              </tr>
            </thead>
            <tbody>
              {failed_rows}
            </tbody>
          </table>
        </div>
        """

    # Build main products table
    table_rows = ""
    for p in products:
        curr = getattr(p, "currency", "Rs. ") or "Rs. "
        is_deal = p.current_price is not None and p.current_price <= p.target_price
        is_failed = p.id in failed_ids

        if is_failed:
            badge = '<span style="background: #FEE2E2; color: #991B1B; font-weight: 600; padding: 4px 8px; border-radius: 10px; font-size: 11px;">⚠️ Failed to refresh</span>'
        elif is_deal:
            badge = '<span style="background: #15370D; color: #FFF2B4; font-weight: bold; padding: 4px 10px; border-radius: 12px; font-size: 11px;">🔥 Drop Alert!</span>'
        else:
            badge = '<span style="background: #f1f5f9; color: #475569; padding: 4px 10px; border-radius: 12px; font-size: 11px;">Monitoring</span>'

        current_str = f"<strong>{curr}{p.current_price:,.2f}</strong>" if p.current_price is not None else '<span style="color: #94a3b8; font-style: italic;">Not fetched</span>'
        target_str = f"{curr}{p.target_price:,.2f}"

        table_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 12px 14px; vertical-align: top;">
            <a href="{p.url}" target="_blank" style="color: #15370D; font-weight: 600; text-decoration: none; font-size: 14px; display: block; margin-bottom: 3px;">
              {p.name}
            </a>
            <span style="color: #728E6D; font-size: 11px; word-break: break-all;">{p.url[:60]}...</span>
          </td>
          <td style="padding: 12px 14px; vertical-align: top; font-size: 14px; color: {'#15370D' if is_deal else '#1e293b'};">
            {current_str}
          </td>
          <td style="padding: 12px 14px; vertical-align: top; font-size: 14px; color: #64748b;">
            {target_str}
          </td>
          <td style="padding: 12px 14px; vertical-align: top;">
            {badge}
          </td>
        </tr>
        """

    header_subtitle = (
        f"Instant status snapshot of all {len(products)} tracked items. (⚠️ {len(failed_items)} store(s) could not be refreshed on this check)"
        if failed_items
        else f"All {len(products)} monitored products were checked and updated successfully in Sri Lankan Rupees."
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Price Tracker - Live Check Report</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
      <div style="max-width: 700px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);">
        <div style="background-color: #15370D; padding: 24px; color: #ffffff; border-bottom: 3px solid #E5CD82;">
          <h1 style="margin: 0; font-size: 20px; font-weight: 700; color: #FFF2B4; letter-spacing: -0.3px;">PriceDrop Radar &bull; Live Price Check Report</h1>
          <p style="margin: 6px 0 0 0; font-size: 13px; color: #E5CD82;">{header_subtitle}</p>
        </div>

        <div style="padding: 22px;">
          {failed_section_html}

          <h3 style="margin: 0 0 12px 0; font-size: 14px; font-weight: 700; color: #15370D; text-transform: uppercase; letter-spacing: 0.5px;">All Tracked Products Status</h3>
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left;">
              <thead>
                <tr style="background-color: #f8fafc; border-bottom: 2px solid #cbd5e1; font-size: 11px; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">
                  <th style="padding: 10px 14px;">Product</th>
                  <th style="padding: 10px 14px;">Current</th>
                  <th style="padding: 10px 14px;">Target</th>
                  <th style="padding: 10px 14px;">Status</th>
                </tr>
              </thead>
              <tbody>
                {table_rows}
              </tbody>
            </table>
          </div>
        </div>

        <div style="background-color: #f1f5f9; padding: 14px 24px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0;">
          Sent by PriceDrop Radar via Resend &bull; 100% Free-Tier Architecture
        </div>
      </div>
    </body>
    </html>
    """

    subject = (
        f"⚠️ Price Tracker Report: {len(failed_items)} Scrape Issue(s) Detected"
        if failed_items
        else "📊 Price Tracker Report: All Stores Checked Successfully"
    )

    params: resend.Emails.SendParams = {
        "from": SENDER_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    try:
        response = resend.Emails.send(params)
        logger.info("Summary report email sent successfully. Response: %s", response)
        return True
    except Exception as exc:
        logger.error("Failed to send summary report email: %s", str(exc))
        return False
