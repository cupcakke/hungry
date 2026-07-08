from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.domain.payment_links import (
    PaymentLink,
    PaymentLinkLineItem,
    PaymentLinkRestrictions,
    PaymentLinkCustomization,
    PaymentLinkAnalytics,
    PaymentLinkPayment,
)
from payment_platform.backend.application.services.payment_link_service import (
    PaymentLinkService,
    LineItemService,
    RestrictionService,
    CustomizationService,
    AnalyticsService,
    PaymentProcessingService,
)

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


class CustomerInfo(BaseModel):
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None


class PaymentForm(BaseModel):
    customer_email: str
    customer_name: Optional[str] = None
    payment_method: str = "card"
    card_number: Optional[str] = None
    card_expiry: Optional[str] = None
    card_cvc: Optional[str] = None


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _get_timestamp() -> int:
    import time
    return int(time.time())


@router.get("/{payment_link_id}", response_class=HTMLResponse)
async def render_payment_page(
    request: Request,
    payment_link_id: str,
    session: AsyncSession = Depends(get_session),
):
    payment_link = await _get_payment_link(session, payment_link_id)
    if not payment_link:
        return _render_error_page(request, "Payment link not found", 404)
    
    if not payment_link.active:
        return _render_error_page(request, "This payment link is no longer active", 400)
    
    restrictions = await _get_restrictions(session, payment_link_id)
    if restrictions:
        validation = await _validate_restrictions(restrictions)
        if not validation["valid"]:
            return _render_error_page(request, validation["message"], 400)
    
    line_items = await _get_line_items(session, payment_link_id)
    customization = await _get_customization(session, payment_link_id)
    
    analytics_service = AnalyticsService(session)
    await analytics_service.track_view(payment_link_id)
    
    total_amount = _calculate_total(line_items)
    
    return _render_hosted_page(
        request,
        payment_link,
        line_items,
        customization,
        total_amount,
    )


@router.post("/{payment_link_id}/checkout", response_class=HTMLResponse)
async def process_checkout(
    request: Request,
    payment_link_id: str,
    customer_email: str = Form(...),
    customer_name: Optional[str] = Form(None),
    payment_method: str = Form("card"),
    card_number: Optional[str] = Form(None),
    card_expiry: Optional[str] = Form(None),
    card_cvc: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    payment_link = await _get_payment_link(session, payment_link_id)
    if not payment_link:
        return _render_error_page(request, "Payment link not found", 404)
    
    if not payment_link.active:
        return _render_error_page(request, "This payment link is no longer active", 400)
    
    restrictions = await _get_restrictions(session, payment_link_id)
    if restrictions:
        validation = await _validate_restrictions_with_email(restrictions, customer_email)
        if not validation["valid"]:
            return _render_error_page(request, validation["message"], 400)
    
    line_items = await _get_line_items(session, payment_link_id)
    customization = await _get_customization(session, payment_link_id)
    total_amount = _calculate_total(line_items)
    currency = payment_link.payment_intent_data.get("currency", "usd") if payment_link.payment_intent_data else "usd"
    
    analytics_service = AnalyticsService(session)
    await analytics_service.track_event(payment_link_id, "checkout_started")
    
    payment_processing = PaymentProcessingService(session)
    
    customer_id = await payment_processing.create_customer_if_needed(
        email=customer_email,
        name=customer_name,
        payment_link_id=payment_link_id,
    )
    
    payment = await payment_processing.process_payment(
        payment_link_id=payment_link_id,
        amount=total_amount,
        currency=currency,
        customer_id=customer_id,
        metadata={
            "customer_email": customer_email,
            "customer_name": customer_name,
        },
    )
    
    try:
        payment_result = await _process_payment_method(
            payment_method,
            card_number,
            card_expiry,
            card_cvc,
            total_amount,
            currency,
        )
        
        if payment_result["success"]:
            await payment_processing.complete_payment(payment.id)
            return _render_success_page(request, payment_link, customization, payment)
        else:
            await payment_processing.fail_payment(payment.id)
            return _render_payment_failed_page(request, payment_link, customization, payment_result.get("error", "Payment failed"))
    
    except Exception as e:
        await payment_processing.fail_payment(payment.id)
        return _render_error_page(request, f"Payment processing error: {str(e)}", 500)


@router.get("/{payment_link_id}/success", response_class=HTMLResponse)
async def render_success_page(
    request: Request,
    payment_link_id: str,
    payment_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    payment_link = await _get_payment_link(session, payment_link_id)
    if not payment_link:
        return _render_error_page(request, "Payment link not found", 404)
    
    customization = await _get_customization(session, payment_link_id)
    return _render_success_page(request, payment_link, customization, None)


async def _get_payment_link(session: AsyncSession, payment_link_id: str) -> Optional[PaymentLink]:
    query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def _get_line_items(session: AsyncSession, payment_link_id: str) -> List[PaymentLinkLineItem]:
    query = select(PaymentLinkLineItem).where(
        PaymentLinkLineItem.payment_link_id == payment_link_id
    ).order_by(PaymentLinkLineItem.created_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def _get_restrictions(session: AsyncSession, payment_link_id: str) -> Optional[PaymentLinkRestrictions]:
    query = select(PaymentLinkRestrictions).where(
        PaymentLinkRestrictions.payment_link_id == payment_link_id
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def _get_customization(session: AsyncSession, payment_link_id: str) -> Optional[PaymentLinkCustomization]:
    query = select(PaymentLinkCustomization).where(
        PaymentLinkCustomization.payment_link_id == payment_link_id
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def _validate_restrictions(restrictions: PaymentLinkRestrictions) -> Dict[str, Any]:
    if restrictions.max_uses is not None and restrictions.current_uses >= restrictions.max_uses:
        return {"valid": False, "message": "This payment link has reached its maximum uses"}
    
    if restrictions.expiry_date is not None:
        current_time = int(datetime.utcnow().timestamp())
        if current_time > restrictions.expiry_date:
            return {"valid": False, "message": "This payment link has expired"}
    
    return {"valid": True}


async def _validate_restrictions_with_email(restrictions: PaymentLinkRestrictions, email: str) -> Dict[str, Any]:
    result = await _validate_restrictions(restrictions)
    if not result["valid"]:
        return result
    
    if restrictions.allowed_emails:
        if not _match_email_pattern(email, restrictions.allowed_emails):
            return {"valid": False, "message": "This email is not authorized to use this payment link"}
    
    return {"valid": True}


def _match_email_pattern(email: str, patterns: List[str]) -> bool:
    import fnmatch
    email_lower = email.lower()
    for pattern in patterns:
        pattern_lower = pattern.lower()
        if fnmatch.fnmatch(email_lower, pattern_lower):
            return True
        if email_lower == pattern_lower:
            return True
        if pattern_lower.startswith("@"):
            if email_lower.endswith(pattern_lower):
                return True
    return False


def _calculate_total(line_items: List[PaymentLinkLineItem]) -> int:
    total = 0
    for item in line_items:
        total += item.quantity * 1000
    return total


async def _process_payment_method(
    payment_method: str,
    card_number: Optional[str],
    card_expiry: Optional[str],
    card_cvc: Optional[str],
    amount: int,
    currency: str,
) -> Dict[str, Any]:
    if payment_method == "card":
        if not card_number or not card_expiry or not card_cvc:
            return {"success": False, "error": "Missing card details"}
        
        if len(card_number.replace(" ", "")) < 13:
            return {"success": False, "error": "Invalid card number"}
        
        return {"success": True, "payment_intent_id": _generate_id("pi")}
    
    return {"success": True, "payment_intent_id": _generate_id("pi")}


def _render_hosted_page(
    request: Request,
    payment_link: PaymentLink,
    line_items: List[PaymentLinkLineItem],
    customization: Optional[PaymentLinkCustomization],
    total_amount: int,
) -> HTMLResponse:
    brand_color = customization.brand_color if customization and customization.brand_color else "#635BFF"
    logo_url = customization.logo_url if customization and customization.logo_url else None
    button_text = customization.button_text if customization and customization.button_text else "Pay Now"
    custom_fields = customization.custom_fields if customization and customization.custom_fields else []
    terms_url = customization.terms_url if customization and customization.terms_url else None
    privacy_url = customization.privacy_url if customization and customization.privacy_url else None
    
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{payment_link.name or 'Complete Payment'}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background-color: #f6f9fc;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        
        .container {{
            max-width: 420px;
            width: 100%;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, {brand_color} 0%, {brand_color}dd 100%);
            padding: 24px;
            text-align: center;
            color: white;
        }}
        
        .header h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        
        .header .amount {{
            font-size: 36px;
            font-weight: 700;
        }}
        
        .content {{
            padding: 24px;
        }}
        
        .line-items {{
            border-bottom: 1px solid #e5e7eb;
            padding-bottom: 16px;
            margin-bottom: 16px;
        }}
        
        .line-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
        }}
        
        .line-item .name {{
            color: #374151;
            font-size: 14px;
        }}
        
        .line-item .quantity {{
            color: #6b7280;
            font-size: 12px;
        }}
        
        .line-item .price {{
            color: #111827;
            font-weight: 500;
        }}
        
        .total {{
            display: flex;
            justify-content: space-between;
            font-size: 18px;
            font-weight: 600;
            padding: 16px 0;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        form {{
            margin-top: 20px;
        }}
        
        .form-group {{
            margin-bottom: 16px;
        }}
        
        label {{
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: #374151;
            margin-bottom: 6px;
        }}
        
        input {{
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        
        input:focus {{
            outline: none;
            border-color: {brand_color};
            box-shadow: 0 0 0 3px {brand_color}33;
        }}
        
        .card-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }}
        
        .payment-methods {{
            margin-bottom: 16px;
        }}
        
        .payment-method-option {{
            display: flex;
            align-items: center;
            padding: 12px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            margin-bottom: 8px;
            cursor: pointer;
        }}
        
        .payment-method-option.selected {{
            border-color: {brand_color};
            background: {brand_color}0d;
        }}
        
        .payment-method-option input {{
            width: auto;
            margin-right: 10px;
        }}
        
        .submit-btn {{
            width: 100%;
            padding: 14px;
            background: {brand_color};
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.2s, transform 0.1s;
        }}
        
        .submit-btn:hover {{
            filter: brightness(1.1);
        }}
        
        .submit-btn:active {{
            transform: scale(0.98);
        }}
        
        .footer {{
            padding: 16px 24px;
            background: #f9fafb;
            text-align: center;
            font-size: 12px;
            color: #6b7280;
        }}
        
        .footer a {{
            color: {brand_color};
            text-decoration: none;
        }}
        
        .secure-badge {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            margin-top: 12px;
            font-size: 12px;
            color: #6b7280;
        }}
        
        @media (max-width: 480px) {{
            body {{
                padding: 0;
            }}
            
            .container {{
                border-radius: 0;
            }}
            
            .card-row {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            {'<img src="' + logo_url + '" alt="Logo" style="height: 40px; margin-bottom: 16px;">' if logo_url else ''}
            <h1>{payment_link.name or 'Complete Payment'}</h1>
            <div class="amount">${'{:.2f}'.format(total_amount / 100)}</div>
        </div>
        
        <div class="content">
            <div class="line-items">
                {''.join([f'''
                <div class="line-item">
                    <div>
                        <span class="name">Item {item.price_id}</span>
                        <span class="quantity"> x{item.quantity}</span>
                    </div>
                    <span class="price">${'{:.2f}'.format(item.quantity * 1000 / 100)}</span>
                </div>
                ''' for item in line_items])}
            </div>
            
            <div class="total">
                <span>Total</span>
                <span>${'{:.2f}'.format(total_amount / 100)}</span>
            </div>
            
            <form method="POST" action="/payment_link/{payment_link.id}/checkout">
                <div class="form-group">
                    <label for="customer_email">Email</label>
                    <input type="email" id="customer_email" name="customer_email" required placeholder="your@email.com">
                </div>
                
                <div class="form-group">
                    <label for="customer_name">Name (optional)</label>
                    <input type="text" id="customer_name" name="customer_name" placeholder="Your name">
                </div>
                
                <div class="payment-methods">
                    <div class="payment-method-option selected">
                        <input type="radio" name="payment_method" value="card" checked>
                        <span>💳 Card</span>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="card_number">Card number</label>
                    <input type="text" id="card_number" name="card_number" placeholder="1234 5678 9012 3456" maxlength="19">
                </div>
                
                <div class="card-row">
                    <div class="form-group">
                        <label for="card_expiry">Expiry</label>
                        <input type="text" id="card_expiry" name="card_expiry" placeholder="MM/YY" maxlength="5">
                    </div>
                    <div class="form-group">
                        <label for="card_cvc">CVC</label>
                        <input type="text" id="card_cvc" name="card_cvc" placeholder="123" maxlength="4">
                    </div>
                </div>
                
                <button type="submit" class="submit-btn">{button_text}</button>
            </form>
            
            <div class="secure-badge">
                🔒 Secure payment powered by Payment Platform
            </div>
        </div>
        
        <div class="footer">
            {'<a href="' + terms_url + '">Terms</a> · ' if terms_url else ''}
            {'<a href="' + privacy_url + '">Privacy</a>' if privacy_url else ''}
        </div>
    </div>
</body>
</html>
    """
    return HTMLResponse(content=html)


def _render_success_page(
    request: Request,
    payment_link: PaymentLink,
    customization: Optional[PaymentLinkCustomization],
    payment: Optional[PaymentLinkPayment],
) -> HTMLResponse:
    brand_color = customization.brand_color if customization and customization.brand_color else "#635BFF"
    logo_url = customization.logo_url if customization and customization.logo_url else None
    
    after_completion = payment_link.after_completion or {}
    redirect_url = after_completion.get("redirect", {}).get("url")
    
    if redirect_url:
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="3;url={redirect_url}">
    <title>Payment Successful</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            background: #f6f9fc;
        }}
        .container {{
            text-align: center;
            padding: 40px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #111827;
            margin-bottom: 10px;
        }}
        p {{
            color: #6b7280;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✅</div>
        <h1>Payment Successful!</h1>
        <p>Redirecting you...</p>
    </div>
</body>
</html>
        """
    else:
        message = after_completion.get("message", "Your payment has been processed successfully.")
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Successful</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #f6f9fc;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        
        .container {{
            max-width: 420px;
            width: 100%;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            overflow: hidden;
            text-align: center;
        }}
        
        .header {{
            background: linear-gradient(135deg, {brand_color} 0%, {brand_color}dd 100%);
            padding: 40px 24px;
            color: white;
        }}
        
        .icon {{
            font-size: 64px;
            margin-bottom: 16px;
        }}
        
        h1 {{
            font-size: 24px;
            font-weight: 600;
        }}
        
        .content {{
            padding: 32px 24px;
        }}
        
        p {{
            color: #6b7280;
            font-size: 16px;
            line-height: 1.6;
            margin-bottom: 24px;
        }}
        
        .details {{
            background: #f9fafb;
            padding: 16px;
            border-radius: 8px;
            text-align: left;
        }}
        
        .detail-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        .detail-row:last-child {{
            border-bottom: none;
        }}
        
        .detail-label {{
            color: #6b7280;
            font-size: 14px;
        }}
        
        .detail-value {{
            color: #111827;
            font-weight: 500;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            {'<img src="' + logo_url + '" alt="Logo" style="height: 40px; margin-bottom: 16px;">' if logo_url else ''}
            <div class="icon">✅</div>
            <h1>Payment Successful!</h1>
        </div>
        
        <div class="content">
            <p>{message}</p>
            
            {f'''
            <div class="details">
                <div class="detail-row">
                    <span class="detail-label">Amount</span>
                    <span class="detail-value">${'{{:.2f}}'.format(payment.amount / 100)} {payment.currency.upper()}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Payment ID</span>
                    <span class="detail-value">{payment.id}</span>
                </div>
            </div>
            ''' if payment else ''}
        </div>
    </div>
</body>
</html>
        """
    
    return HTMLResponse(content=html)


def _render_error_page(request: Request, message: str, status_code: int) -> HTMLResponse:
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Error</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #f6f9fc;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        
        .container {{
            max-width: 420px;
            width: 100%;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            overflow: hidden;
            text-align: center;
            padding: 40px 24px;
        }}
        
        .icon {{
            font-size: 64px;
            margin-bottom: 16px;
        }}
        
        h1 {{
            font-size: 24px;
            color: #111827;
            margin-bottom: 16px;
        }}
        
        p {{
            color: #6b7280;
            font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">⚠️</div>
        <h1>Unable to Complete</h1>
        <p>{message}</p>
    </div>
</body>
</html>
    """
    return HTMLResponse(content=html, status_code=status_code)


def _render_payment_failed_page(
    request: Request,
    payment_link: PaymentLink,
    customization: Optional[PaymentLinkCustomization],
    error_message: str,
) -> HTMLResponse:
    brand_color = customization.brand_color if customization and customization.brand_color else "#635BFF"
    
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Failed</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #f6f9fc;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        
        .container {{
            max-width: 420px;
            width: 100%;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            overflow: hidden;
            text-align: center;
        }}
        
        .header {{
            background: #fee2e2;
            padding: 40px 24px;
        }}
        
        .icon {{
            font-size: 64px;
            margin-bottom: 16px;
        }}
        
        h1 {{
            font-size: 24px;
            color: #991b1b;
        }}
        
        .content {{
            padding: 32px 24px;
        }}
        
        p {{
            color: #6b7280;
            font-size: 16px;
            margin-bottom: 24px;
        }}
        
        a {{
            display: inline-block;
            padding: 14px 28px;
            background: {brand_color};
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="icon">❌</div>
            <h1>Payment Failed</h1>
        </div>
        
        <div class="content">
            <p>{error_message}</p>
            <p>Please try again or contact support if the problem persists.</p>
            <a href="/payment_link/{payment_link.id}">Try Again</a>
        </div>
    </div>
</body>
</html>
    """
    return HTMLResponse(content=html)
