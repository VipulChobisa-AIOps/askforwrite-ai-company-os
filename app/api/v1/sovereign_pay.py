"""AFW DirectPay: Sovereign Zero-Fee Payment Gateway API Router.

Exposes endpoints for:
- POST /v1/pay/create-session: Initialize a sovereign payment session across 3 settlement rails.
- GET  /v1/pay/{session_id}/checkout: Public responsive HTML checkout page with live QR, Web3, and Wire tabs.
- GET  /v1/pay/checkout: Direct query-param checkout entrypoint (?package={pkg}&company={co}).
- POST /v1/pay/{session_id}/verify: Submit payment proof, seal NIST P-256 TrustBlock, auto-provision tenant.
- GET  /v1/pay/{session_id}/status: Check session status and cryptographic receipt.
"""

from __future__ import annotations

import html
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, require_owner
from app.services.catalog import CATALOG, get_package
from app.services.sovereign_pay import (
    confirm_sovereign_payment_by_owner,
    create_sovereign_pay_session,
    get_sovereign_pay_session,
    verify_sovereign_payment,
)

router = APIRouter(prefix="/v1/pay", tags=["AFW DirectPay Sovereign Gateway"])


class CreateSessionRequest(BaseModel):
    package_key: str = Field(min_length=1, max_length=100, description="Catalog SKU package key")
    company_name: str = Field(min_length=1, max_length=200, description="Customer or prospect company name")
    customer_email: str = Field(min_length=3, max_length=200, description="Customer billing and login email")
    currency: str = Field(default="INR", pattern="^(INR|USD)$", description="Settlement currency")
    preferred_rail: str = Field(
        default="upi_direct",
        pattern="^(upi_direct|web3_usdc|bank_wire_direct)$",
        description="Default rail shown to customer",
    )
    customer_name: str | None = Field(default=None, max_length=150)
    customer_phone: str | None = Field(default=None, max_length=50)


class VerifyPaymentRequest(BaseModel):
    rail: str = Field(
        pattern="^(upi_direct|web3_usdc|bank_wire_direct)$",
        description="Settlement rail used for payment",
    )
    proof_reference: str = Field(
        min_length=1,
        max_length=150,
        description="12-digit UPI UTR number, 0x... Web3 tx hash, or bank wire reference code",
    )


@router.post("/create-session")
def create_session_endpoint(
    payload: CreateSessionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new sovereign payment session across 3 native settlement rails with 0% gateway commission."""
    session = create_sovereign_pay_session(
        package_key=payload.package_key,
        company_name=payload.company_name,
        customer_email=payload.customer_email,
        currency=payload.currency,
        preferred_rail=payload.preferred_rail,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        db=db,
    )
    return {
        "session_id": session.session_id,
        "package_key": session.package_key,
        "package_name": session.package_name,
        "company_name": session.company_name,
        "customer_email": session.customer_email,
        "currency": session.currency,
        "amount": session.amount,
        "preferred_rail": session.preferred_rail,
        "status": session.status,
        "checkout_url": session.checkout_url,
        "upi_uri": session.upi_uri,
        "upi_qr_svg": session.upi_qr_svg,
        "usdc_payload": session.usdc_payload,
        "bank_wire_invoice": session.bank_wire_invoice,
        "zero_gateway_fee": True,
        "created_at": session.created_at,
    }


@router.post("/{session_id}/verify")
def verify_payment_endpoint(
    session_id: str,
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Validate settlement proof, seal ECDSA NIST P-256 TrustBlock, and auto-provision multi-tenant workspace."""
    try:
        return verify_sovereign_payment(
            session_id=session_id,
            rail=payload.rail,
            proof_reference=payload.proof_reference,
            db=db,
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.post("/{session_id}/confirm-owner")
def confirm_payment_owner_endpoint(
    session_id: str,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Owner Human-in-the-Loop confirmation to seal NIST P-256 block, invoice, and auto-provision workspace."""
    try:
        return confirm_sovereign_payment_by_owner(
            session_id=session_id,
            db=db,
            decided_by=principal.subject or "owner",
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.get("/{session_id}/status")
def get_session_status_endpoint(
    session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Check the real-time settlement and verification status of a sovereign payment session."""
    session = get_sovereign_pay_session(session_id, db=db)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found")
    return session.to_dict()


def _render_checkout_html(session: Any) -> str:
    """Generate responsive, dark glassmorphic HTML checkout experience for AFW DirectPay."""
    curr_symbol = "₹" if session.currency == "INR" else "$"
    amount_str = f"{session.amount:,.0f}" if session.currency == "INR" else f"{session.amount:.2f}"
    safe_company = html.escape(session.company_name)
    safe_pkg_name = html.escape(session.package_name)
    safe_session_id = html.escape(session.session_id)
    safe_upi_uri = html.escape(session.upi_uri)

    evm_address = session.usdc_payload.get("evm_deposit_address", "")
    sol_address = session.usdc_payload.get("sol_deposit_address", "")
    wire = session.bank_wire_invoice
    wire_beneficiary = wire.get("beneficiary", {})
    wire_ref = wire.get("payment_reference_code", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AFW DirectPay — Sovereign Checkout for {safe_company}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #07090e;
      --card-bg: rgba(15, 23, 42, 0.75);
      --card-border: rgba(99, 102, 241, 0.25);
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.35);
      --accent: #06b6d4;
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.3);
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #07090e 65%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-start;
      padding: 32px 16px 64px;
    }}
    .checkout-container {{
      width: 100%;
      max-width: 640px;
    }}
    .brand-header {{
      text-align: center;
      margin-bottom: 28px;
    }}
    .brand-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 9999px;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: #818cf8;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    .brand-title {{
      font-size: 1.75rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 6px;
    }}
    .brand-subtitle {{
      color: var(--text-muted);
      font-size: 0.92rem;
    }}
    .order-summary-card {{
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.7);
    }}
    .order-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      margin-bottom: 14px;
    }}
    .order-item-title {{
      font-size: 1.05rem;
      font-weight: 700;
      color: #ffffff;
    }}
    .order-item-company {{
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 2px;
    }}
    .order-price {{
      font-size: 1.65rem;
      font-weight: 800;
      color: #38bdf8;
      letter-spacing: -0.02em;
    }}
    .order-features {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      font-size: 0.8rem;
      color: #94a3b8;
    }}
    .feature-tag {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: #34d399;
    }}
    /* Tabs Navigation */
    .tabs-header {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      background: rgba(15, 23, 42, 0.6);
      padding: 6px;
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      margin-bottom: 20px;
    }}
    .tab-btn {{
      padding: 10px 8px;
      border: none;
      border-radius: 10px;
      background: transparent;
      color: var(--text-muted);
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s ease;
      text-align: center;
    }}
    .tab-btn.active {{
      background: #4f46e5;
      color: #ffffff;
      box-shadow: 0 4px 14px var(--primary-glow);
    }}
    .tab-content {{
      display: none;
      animation: fadeIn 0.25s ease;
    }}
    .tab-content.active {{
      display: block;
    }}
    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(6px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    /* Payment Rails Panels */
    .rail-card {{
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 28px 24px;
      margin-bottom: 24px;
      text-align: center;
    }}
    .qr-frame {{
      display: inline-block;
      padding: 14px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
      margin-bottom: 18px;
    }}
    .qr-frame svg {{
      display: block;
      max-width: 230px;
      height: auto;
    }}
    .upi-action-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      max-width: 320px;
      padding: 14px 20px;
      border-radius: 12px;
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: #ffffff;
      font-weight: 700;
      font-size: 0.95rem;
      text-decoration: none;
      margin: 12px auto;
      box-shadow: 0 6px 18px var(--success-glow);
      transition: transform 0.15s ease;
    }}
    .upi-action-btn:hover {{
      transform: translateY(-2px);
    }}
    .copy-box {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 10px;
      padding: 10px 14px;
      margin-top: 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.84rem;
      color: #e2e8f0;
      word-break: break-all;
    }}
    .copy-btn {{
      background: rgba(255, 255, 255, 0.1);
      border: none;
      color: #38bdf8;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 0.76rem;
      font-weight: 600;
      cursor: pointer;
      margin-left: 10px;
      white-space: nowrap;
      transition: background 0.15s ease;
    }}
    .copy-btn:hover {{
      background: rgba(255, 255, 255, 0.2);
    }}
    .wire-table {{
      width: 100%;
      text-align: left;
      font-size: 0.85rem;
      border-collapse: collapse;
      margin-top: 14px;
    }}
    .wire-table td {{
      padding: 8px 6px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }}
    .wire-table td.label {{
      color: var(--text-muted);
      width: 40%;
    }}
    .wire-table td.val {{
      font-family: 'JetBrains Mono', monospace;
      color: #f1f5f9;
      font-weight: 600;
    }}
    /* Verification Box */
    .verify-card {{
      background: rgba(30, 41, 59, 0.8);
      border: 1px solid rgba(16, 185, 129, 0.35);
      border-radius: 20px;
      padding: 24px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }}
    .verify-title {{
      font-size: 1.1rem;
      font-weight: 800;
      color: #34d399;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .verify-desc {{
      font-size: 0.84rem;
      color: var(--text-muted);
      margin-bottom: 18px;
    }}
    .form-group {{
      margin-bottom: 14px;
      text-align: left;
    }}
    .form-label {{
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
    }}
    .form-control {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 10px;
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: #ffffff;
      font-family: inherit;
      font-size: 0.9rem;
      outline: none;
      transition: border 0.15s ease;
    }}
    .form-control:focus {{
      border-color: #6366f1;
    }}
    .verify-btn {{
      width: 100%;
      padding: 14px;
      border-radius: 12px;
      background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
      color: #ffffff;
      border: none;
      font-weight: 800;
      font-size: 0.95rem;
      cursor: pointer;
      box-shadow: 0 6px 20px var(--primary-glow);
      transition: all 0.15s ease;
      margin-top: 6px;
    }}
    .verify-btn:hover {{
      background: linear-gradient(135deg, #6366f1 0%, #4338ca 100%);
      transform: translateY(-1px);
    }}
    .verify-btn:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
    }}
    /* Result card */
    .success-result {{
      display: none;
      padding: 24px;
      background: rgba(6, 78, 59, 0.5);
      border: 1px solid rgba(52, 211, 153, 0.4);
      border-radius: 16px;
      margin-top: 18px;
      text-align: left;
    }}
    .trust-badge {{
      display: inline-block;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.72rem;
      background: rgba(0, 0, 0, 0.4);
      padding: 4px 8px;
      border-radius: 6px;
      color: #6ee7b7;
      margin-top: 8px;
      word-break: break-all;
    }}
    .error-msg {{
      display: none;
      color: #f87171;
      font-size: 0.82rem;
      margin-top: 10px;
      text-align: left;
    }}
  </style>
</head>
<body>

<div class="checkout-container">
  <div class="brand-header">
    <div class="brand-pill">⚡ Sovereign Direct Settlement • 0% Commission</div>
    <h1 class="brand-title">AFW DirectPay</h1>
    <p class="brand-subtitle">First-party sovereign payments with zero aggregator fees and instant cryptographic provisioning</p>
  </div>

  <!-- Order Summary -->
  <div class="order-summary-card">
    <div class="order-row">
      <div>
        <div class="order-item-title">{safe_pkg_name}</div>
        <div class="order-item-company">Prepared for {safe_company}</div>
      </div>
      <div class="order-price">{curr_symbol}{amount_str}</div>
    </div>
    <div class="order-features">
      <span class="feature-tag">✓ 0% Gateway Deduction</span>
      <span class="feature-tag">✓ NIST P-256 Merkle Block Sealed</span>
      <span class="feature-tag">✓ Instant Autonomous Provisioning</span>
    </div>
  </div>

  <!-- Rails Tabs Navigation -->
  <div class="tabs-header">
    <button class="tab-btn {'active' if session.currency == 'INR' else ''}" onclick="switchTab('upi')">🇮🇳 Instant UPI QR</button>
    <button class="tab-btn {'active' if session.currency == 'USD' else ''}" onclick="switchTab('web3')">🌐 USDC Web3 (<$0.01)</button>
    <button class="tab-btn" onclick="switchTab('wire')">🏛️ Direct Bank Wire</button>
  </div>

  <!-- Tab 1: UPI Direct -->
  <div id="tab-upi" class="tab-content {'active' if session.currency == 'INR' else ''}">
    <div class="rail-card">
      <div style="font-weight:700; color:#38bdf8; margin-bottom:12px;">Scan with Any UPI App (GPay, PhonePe, Paytm, BHIM)</div>
      <div class="qr-frame">
        {session.upi_qr_svg}
      </div>
      <div>
        <a href="{safe_upi_uri}" class="upi-action-btn">📱 Tap to Open in Mobile UPI App</a>
      </div>
      <div style="max-width:440px; margin:14px auto 0;">
        <div style="font-size:0.78rem; color:var(--text-muted); text-align:left;">Merchant VPA / UPI ID:</div>
        <div class="copy-box">
          <span id="vpa-text">{html.escape(str(wire_beneficiary.get('upi_vpa') or os.getenv('AFW_MERCHANT_UPI_VPA', 'ask4write@icici')))}</span>
          <button class="copy-btn" onclick="copyText('vpa-text')">Copy VPA</button>
        </div>
        <div style="font-size:0.78rem; color:var(--text-muted); text-align:left; margin-top:8px;">Exact Amount:</div>
        <div class="copy-box">
          <span id="amt-text">₹{session.amount:.2f}</span>
          <button class="copy-btn" onclick="copyText('amt-text')">Copy Amount</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab 2: Web3 USDC -->
  <div id="tab-web3" class="tab-content {'active' if session.currency == 'USD' else ''}">
    <div class="rail-card" style="text-align:left;">
      <div style="font-weight:700; color:#38bdf8; margin-bottom:8px; text-align:center;">Direct Stablecoin Settlement (Polygon / Base / Solana)</div>
      <p style="font-size:0.84rem; color:var(--text-muted); text-align:center; margin-bottom:16px;">
        Transfer exactly <strong style="color:#ffffff;">${session.usdc_payload.get('amount_usd', 129):.2f} USDC</strong> (or USDT) to our verified deposit address.
      </p>

      <div style="font-size:0.8rem; font-weight:700; color:#cbd5e1; margin-top:8px;">Polygon & Base EVM Address (Sub-Cent Fees):</div>
      <div class="copy-box">
        <span id="evm-addr">{evm_address}</span>
        <button class="copy-btn" onclick="copyText('evm-addr')">Copy EVM</button>
      </div>

      <div style="font-size:0.8rem; font-weight:700; color:#cbd5e1; margin-top:12px;">Solana Deposit Address:</div>
      <div class="copy-box">
        <span id="sol-addr">{sol_address}</span>
        <button class="copy-btn" onclick="copyText('sol-addr')">Copy SOL</button>
      </div>

      <div style="margin-top:14px; font-size:0.78rem; color:#94a3b8; line-height:1.4;">
        ⚡ Supported Chains: Polygon (ID 137), Base (ID 8453), Ethereum (ID 1), Solana Mainnet.
      </div>
    </div>
  </div>

  <!-- Tab 3: Bank Wire -->
  <div id="tab-wire" class="tab-content">
    <div class="rail-card" style="text-align:left;">
      <div style="font-weight:700; color:#38bdf8; margin-bottom:8px; text-align:center;">Official Proforma Tax Invoice & RTGS / NEFT / SWIFT Details</div>
      
      <table class="wire-table">
        <tr><td class="label">Beneficiary:</td><td class="val">{wire_beneficiary.get('entity_name')}</td></tr>
        <tr><td class="label">Bank Name:</td><td class="val">{wire_beneficiary.get('bank_name')}</td></tr>
        <tr><td class="label">Account Number:</td><td class="val">{wire_beneficiary.get('account_number')}</td></tr>
        <tr><td class="label">Account Type:</td><td class="val">{wire_beneficiary.get('account_type')}</td></tr>
        <tr><td class="label">IFSC Code:</td><td class="val">{wire_beneficiary.get('ifsc_code')}</td></tr>
        <tr><td class="label">SWIFT Code:</td><td class="val">{wire_beneficiary.get('swift_code')}</td></tr>
        <tr><td class="label">Branch:</td><td class="val">{wire_beneficiary.get('branch')}</td></tr>
        <tr><td class="label">Payment Reference:</td><td class="val" style="color:#38bdf8;">{wire_ref}</td></tr>
      </table>

      <div class="copy-box" style="margin-top:14px;">
        <span id="wire-ref-text">{wire_ref}</span>
        <button class="copy-btn" onclick="copyText('wire-ref-text')">Copy Narration Ref</button>
      </div>
    </div>
  </div>

  <!-- Verification & Instant Activation Form -->
  <div class="verify-card">
    <div class="verify-title">
      <span>🛡️</span> Instant Activation & Trust Block Verification
    </div>
    <p class="verify-desc">Submit your payment reference for immediate 0-second multi-tenant activation and NIST P-256 Merkle DAG sealing.</p>

    <div class="form-group">
      <label class="form-label" for="verify-rail">Settlement Rail Used</label>
      <select id="verify-rail" class="form-control">
        <option value="upi_direct" {'selected' if session.currency == 'INR' else ''}>UPI Direct (12-digit UTR)</option>
        <option value="web3_usdc" {'selected' if session.currency == 'USD' else ''}>Web3 Stablecoin (0x... TX Hash)</option>
        <option value="bank_wire_direct">Direct Bank Wire / NEFT / RTGS</option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label" for="verify-proof">UTR / Transaction Hash / Narration Reference</label>
      <input type="text" id="verify-proof" class="form-control" placeholder="e.g. 12-digit UPI UTR (412345678901) or 0x... TX hash" required>
    </div>

    <button id="submit-verify-btn" class="verify-btn" onclick="submitVerification()">
      ⚡ Verify & Instantly Activate AI OS Workspace
    </button>

    <div id="verify-error" class="error-msg"></div>

    <div id="verify-success" class="success-result">
      <h3 style="color:#34d399; margin-bottom:8px; font-weight:800;">🎉 Sovereign Payment Verified!</h3>
      <p style="font-size:0.86rem; color:#e2e8f0; margin-bottom:12px;" id="success-msg"></p>
      
      <div style="font-size:0.78rem; color:#94a3b8; margin-bottom:4px;">NIST P-256 Cryptographic Block Seal:</div>
      <div class="trust-badge" id="trust-block-hash"></div>

      <div style="margin-top:18px;">
        <a href="/portal" style="display:inline-block; padding:10px 18px; border-radius:8px; background:#10b981; color:#ffffff; font-weight:700; text-decoration:none; font-size:0.88rem;">
          🚀 Enter Customer Portal & AI OS
        </a>
      </div>
    </div>
  </div>

  <!-- Statutory MSME Enterprise Declaration & Legal Footer -->
  <div style="margin-top: 36px; padding: 20px 16px; border-top: 1px solid rgba(255,255,255,0.08); text-align: center; font-size: 0.76rem; color: #94a3b8; line-height: 1.6;">
    <div style="font-weight: 700; color: #cbd5e1; font-size: 0.82rem; margin-bottom: 4px;">
      🏛️ ASKFORWRITE MSME • Statutory Enterprise Registration: <span style="font-family:'JetBrains Mono',monospace; color:#38bdf8;">UDYAM-RJ-14-0018404</span>
    </div>
    <div>Registered Enterprise Office: Udaipur Bus Stand, Udaipur, Rajasthan, India - 313001</div>
    <div style="margin-top: 8px;">
      <a href="/legal/tos" target="_blank" style="color: #38bdf8; text-decoration: underline; margin: 0 8px;">Terms of Service</a> |
      <a href="/legal/privacy" target="_blank" style="color: #38bdf8; text-decoration: underline; margin: 0 8px;">Privacy & BYOK Policy</a> |
      <a href="/legal/declaration" target="_blank" style="color: #38bdf8; text-decoration: underline; margin: 0 8px;">MSME Statutory Declaration</a> |
      <a href="/legal/refund-policy" target="_blank" style="color: #38bdf8; text-decoration: underline; margin: 0 8px;">Refund Policy</a>
    </div>
    <div style="margin-top: 8px; color: #64748b; font-size: 0.72rem;">
      © 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.
    </div>
  </div>
</div>

<script>
  const SESSION_ID = "{safe_session_id}";

  function switchTab(tabId) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    const target = document.getElementById('tab-' + tabId);
    if (target) target.classList.add('active');
    
    // Highlight button
    event.target.classList.add('active');

    // Sync dropdown
    const railSelect = document.getElementById('verify-rail');
    if (tabId === 'upi') railSelect.value = 'upi_direct';
    else if (tabId === 'web3') railSelect.value = 'web3_usdc';
    else if (tabId === 'wire') railSelect.value = 'bank_wire_direct';
  }}

  function copyText(elementId) {{
    const text = document.getElementById(elementId).innerText.trim();
    navigator.clipboard.writeText(text).then(() => {{
      const btn = event.target;
      const original = btn.innerText;
      btn.innerText = 'Copied!';
      setTimeout(() => btn.innerText = original, 1800);
    }}).catch(() => {{
      alert('Copied to clipboard: ' + text);
    }});
  }}

  async function submitVerification() {{
    const rail = document.getElementById('verify-rail').value;
    const proof = document.getElementById('verify-proof').value.trim();
    const btn = document.getElementById('submit-verify-btn');
    const errBox = document.getElementById('verify-error');
    const succBox = document.getElementById('verify-success');

    errBox.style.display = 'none';
    succBox.style.display = 'none';

    if (!proof) {{
      errBox.innerText = 'Please enter your transaction reference number or hash.';
      errBox.style.display = 'block';
      return;
    }}

    btn.disabled = true;
    btn.innerText = 'Verifying cryptographic proof...';

    try {{
      const resp = await fetch('/v1/pay/' + SESSION_ID + '/verify', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ rail: rail, proof_reference: proof }})
      }});

      const data = await resp.json();
      if (!resp.ok) {{
        throw new Error(data.detail || 'Verification failed. Please check your reference code.');
      }}

      // Display success
      btn.style.display = 'none';
      succBox.style.display = 'block';
      document.getElementById('success-msg').innerText = data.message || 'Workspace activated successfully.';
      if (data.trust_block) {{
        document.getElementById('trust-block-hash').innerText = 'Block #' + data.trust_block.index + ' • Hash: ' + data.trust_block.block_hash;
      }}
    }} catch (err) {{
      errBox.innerText = err.message;
      errBox.style.display = 'block';
      btn.disabled = false;
      btn.innerText = '⚡ Verify & Instantly Activate AI OS Workspace';
    }}
  }}
</script>

</body>
</html>
"""


@router.get("/{session_id}/checkout", response_class=HTMLResponse)
def get_checkout_page_endpoint(
    session_id: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render public responsive HTML checkout page for AFW DirectPay."""
    session = get_sovereign_pay_session(session_id, db=db)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sovereign payment session '{session_id}' not found.",
        )
    return HTMLResponse(content=_render_checkout_html(session))


@router.get("/checkout", response_class=HTMLResponse)
def direct_checkout_endpoint(
    package: str = Query(default="growth_all_in_one", description="Catalog SKU package key"),
    company: str = Query(default="Commercial Enterprise", description="Client or company name"),
    email: str | None = Query(default=None, description="Client billing email"),
    currency: str = Query(default="INR", description="Settlement currency"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Direct URL query-param entrypoint for AFW DirectPay checkout (/v1/pay/checkout?package={pkg}&company={co})."""
    pkg = get_package(package) or CATALOG.get(package) or CATALOG["growth_all_in_one"]
    clean_company = company.strip()
    safe_slug = re.sub(r"[^\w]", "", clean_company.lower()) or "client"
    client_email = (email or f"contact@{safe_slug}.com").strip().lower()

    session = create_sovereign_pay_session(
        package_key=pkg.key,
        company_name=clean_company,
        customer_email=client_email,
        currency=currency.upper(),
        preferred_rail="upi_direct" if currency.upper() == "INR" else "web3_usdc",
        db=db,
    )
    return HTMLResponse(content=_render_checkout_html(session))
