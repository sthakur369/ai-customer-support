r"""Generate 30 versioned support-policy PDFs.

Run from the repository root:
    python .\rag\data_preparation\script\generate_knowledge_docs_rag.py --dry-run
    python .\rag\data_preparation\script\generate_knowledge_docs_rag.py --document-id KB-001
    python .\rag\data_preparation\script\generate_knowledge_docs_rag.py --batch-size 10

Completed PDFs are skipped automatically. The manifest is updated after each PDF.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from openai import (
    OpenAI, APIConnectionError, APITimeoutError, InternalServerError,
    RateLimitError, APIStatusError,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from pypdf import PdfReader


# The script is inside rag/data_preparation/script/.
SCRIPT_PATH = Path(__file__).resolve()
RAG_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]
load_dotenv(REPO_ROOT / ".env")

OUTPUT_DIR = RAG_ROOT / "data" / "generated_files"
MANIFEST_PATH = OUTPUT_DIR / "documents_manifest.json"

COMPANY = "Customer Support"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_BATCH_SIZE = 10
MAX_WORDS = 400
MAX_PAGES = 3
MAX_API_ATTEMPTS = 5
PROMPT_VERSION = "1.0"

DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "KB-001",
        "slug": "refund_policy_v1",
        "title": "Refund Policy",
        "language": "English",
        "version": "1.0",
        "status": "superseded",
        "owner": "Payments Operations",
        "effective_date": "2025-01-01",
        "effective_to": "2025-05-31",
        "policy_family": "refund_policy",
        "superseded_by": "KB-002",
        "brief": (
            "This is the OLD refund policy and must preserve its historical rules: "
            "eligible return requests had to be submitted within 7 calendar days of delivery; "
            "after the returned item was received and inspected, the refund was initiated "
            "within 7 business days. Clearly identify this document as superseded and valid "
            "only for orders governed by the old policy period. Do not describe these rules "
            "as the current policy."
        ),
    },
    {
        "id": "KB-002",
        "slug": "refund_policy_v2",
        "title": "Refund Policy",
        "language": "English",
        "version": "2.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "effective_to": None,
        "policy_family": "refund_policy",
        "supersedes": "KB-001",
        "brief": (
            "This is the CURRENT refund policy and replaces version 1.0 from 2025-06-01. "
            "Eligible return requests must be submitted within 10 calendar days of delivery. "
            "After the returned item is received and inspected, the refund is initiated "
            "within 5 business days. Explain that the time for the money to appear in the "
            "customer's bank or payment account may depend on the payment provider; do not "
            "invent a fixed bank-credit timeline."
        ),
    },
    {
        "id": "KB-003",
        "slug": "return_eligibility",
        "title": "Return Eligibility and Conditions",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Returns Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Current eligible return requests must be submitted within 10 calendar days "
            "after delivery. Items should be unused, complete and returned with included "
            "parts and original packaging where available. Eligibility can vary by product "
            "category; direct customers to the product page or support team when uncertain. "
            "Do not contradict the current refund policy."
        ),
    },
    {
        "id": "KB-004",
        "slug": "order_cancellation",
        "title": "Order Cancellation Policy",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Order Management",
        "effective_date": "2025-06-01",
        "brief": (
            "An order can generally be cancelled while it has not yet entered packing. "
            "Once packed or dispatched, cancellation may no longer be available; the customer "
            "should contact support and follow the applicable return process after delivery. "
            "Do not promise cancellation after dispatch or invent cancellation fees."
        ),
    },
    {
        "id": "KB-005",
        "slug": "shipping_and_delivery",
        "title": "Shipping and Delivery Information",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Fulfillment Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "The estimated delivery date shown at checkout and in order tracking is the "
            "customer's reference. Orders are processed after payment confirmation, subject "
            "to product availability and address validation. Tracking updates may take time "
            "to appear after dispatch. Do not invent universal delivery guarantees or "
            "specific courier names."
        ),
    },
    {
        "id": "KB-006",
        "slug": "delivery_delay",
        "title": "Delayed Delivery Resolution",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Fulfillment Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "If an order passes its displayed estimated delivery date, customers should "
            "check tracking, confirm the delivery address and contact support with the "
            "order ID. Support should review the latest carrier status and create or update "
            "a case. Do not promise compensation, a new delivery date or a refund without "
            "an approved case outcome."
        ),
    },
    {
        "id": "KB-007",
        "slug": "damaged_item_claims",
        "title": "Damaged or Defective Item Claims",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Returns Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Customers should report visible delivery damage within 48 hours of delivery. "
            "Ask for the order ID, clear photos of the item and packaging, and a short "
            "description of the damage. If an item appears electrically unsafe, overheats "
            "or emits smoke, the customer should stop using it and contact support. "
            "Replacement or refund depends on review and eligibility; do not guarantee it."
        ),
    },
    {
        "id": "KB-008",
        "slug": "missing_item_claims",
        "title": "Missing Item or Incomplete Package Claims",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Fulfillment Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "For a missing item, customers should check the order details and package "
            "contents, since items in one order may arrive separately. They should report "
            "the issue with the order ID, missing product name and package photos where "
            "available. Support verifies shipment records before deciding the next action. "
            "Do not promise an automatic refund or replacement."
        ),
    },
    {
        "id": "KB-009",
        "slug": "payment_failure",
        "title": "Failed or Pending Payment Guidance",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "If checkout shows failure or pending status, customers should first check "
            "their order history and payment account before attempting payment again. "
            "If money appears debited but no order is confirmed, collect the order attempt "
            "details, transaction reference and timestamp through the secure support flow. "
            "Never ask for a password, OTP, CVV or full card number. Do not invent reversal "
            "timelines; bank/payment-provider processing can vary."
        ),
    },
    {
        "id": "KB-010",
        "slug": "duplicate_payment",
        "title": "Duplicate Payment and Multiple Debit Claims",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "When a customer reports two debits for one order, support should verify "
            "payment references, timestamps, order records and settlement status. Ask only "
            "for safe transaction references through approved support channels. Never ask "
            "for OTP, CVV, PIN, password or full card details. Explain that a verified "
            "duplicate charge is reviewed for reversal; do not promise a fixed bank timeline."
        ),
    },
    {
        "id": "KB-011",
        "slug": "cash_on_delivery",
        "title": "Cash on Delivery Policy",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Cash on Delivery is available only when shown as an option at checkout for "
            "the customer's order and address. The amount due is the amount displayed in "
            "the confirmed order. Customers should not pay extra amounts requested outside "
            "the order total. If COD is unavailable, use another checkout payment method."
        ),
    },
    {
        "id": "KB-012",
        "slug": "warranty_coverage",
        "title": "Warranty and Manufacturer Support",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Product Support",
        "effective_date": "2025-06-01",
        "brief": (
            "Warranty coverage and duration are product-specific and should be checked "
            "on the product page, invoice or warranty card. Our support team can help "
            "customers identify the manufacturer support route and required purchase "
            "evidence. Do not invent a universal warranty duration or extend manufacturer "
            "coverage beyond the published product terms."
        ),
    },
    {
        "id": "KB-013",
        "slug": "non_returnable_products",
        "title": "Non-Returnable and Restricted Return Categories",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Returns Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Some categories may be non-returnable for hygiene, customization, perishability "
            "or digital-delivery reasons. The product page must disclose category-specific "
            "return restrictions before purchase. If a product arrives damaged, defective "
            "or incorrect, the customer may still contact support for review. Do not invent "
            "a universal category list beyond these examples."
        ),
    },
    {
        "id": "KB-014",
        "slug": "exchange_and_replacement",
        "title": "Product Exchange and Replacement",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Returns Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "An exchange or replacement request is subject to product eligibility, "
            "inspection where required and stock availability. Customers should provide "
            "the order ID and reason for the request. If the requested replacement is "
            "unavailable, support explains the available eligible options. Do not guarantee "
            "a replacement before checks are complete."
        ),
    },
    {
        "id": "KB-015",
        "slug": "order_modification",
        "title": "Order Modification Requests",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Order Management",
        "effective_date": "2025-06-01",
        "brief": (
            "Product, quantity or variant changes may be possible only before an order "
            "enters packing. Once packing or dispatch begins, changes may not be possible. "
            "Customers should contact support promptly with the order ID and requested "
            "change. Do not promise that an edit has been made until the order record "
            "confirms it."
        ),
    },
    {
        "id": "KB-016",
        "slug": "shipping_address_changes",
        "title": "Shipping Address Change Requests",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Order Management",
        "effective_date": "2025-06-01",
        "brief": (
            "An address change may be possible before packing, subject to address "
            "validation and service availability. After dispatch, the address generally "
            "cannot be changed through the order system. Customers should contact support "
            "promptly and never post full personal addresses in public channels."
        ),
    },
    {
        "id": "KB-017",
        "slug": "account_access_security",
        "title": "Customer Account Access and Security",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Account Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Customers should use the official sign-in and account-recovery flow. They "
            "must never share passwords, one-time passwords, PINs or recovery codes with "
            "anyone, including a person claiming to be support. Support may verify account "
            "ownership only through approved verification steps and must not disclose "
            "account information before verification."
        ),
    },
    {
        "id": "KB-018",
        "slug": "privacy_and_personal_data",
        "title": "Customer Privacy and Personal Data Handling",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Privacy Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Collect only information needed to resolve the customer's request. Sensitive "
            "payment credentials, passwords, OTPs, CVVs and full card numbers must never "
            "be requested in support conversations or stored in support notes. Restrict "
            "access to customer information to authorized staff and use approved systems "
            "for verification and case handling. Do not invent legal retention periods."
        ),
    },
    {
        "id": "KB-019",
        "slug": "complaint_handling",
        "title": "Customer Complaint Handling Procedure",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Customer Experience",
        "effective_date": "2025-06-01",
        "brief": (
            "Support should acknowledge the complaint, understand the issue, link it to "
            "the relevant order or interaction, record evidence and explain the next step. "
            "Do not blame the customer or promise an outcome before investigation. Keep "
            "case notes factual, respectful and free of unnecessary personal information."
        ),
    },
    {
        "id": "KB-020",
        "slug": "escalation_and_human_review",
        "title": "Escalation and Human Review Guidelines",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Customer Experience",
        "effective_date": "2025-06-01",
        "brief": (
            "Escalate cases involving safety risks, suspected fraud, privacy/security "
            "incidents, repeated unresolved failures, significant customer impact or "
            "requests outside frontline authority. The escalation record should include "
            "case ID, concise issue summary, relevant evidence, actions already taken and "
            "reason for escalation. Do not invent numerical SLAs or approval thresholds."
        ),
    },
    {
        "id": "KB-021",
        "slug": "product_safety_incident",
        "title": "Product Safety Incident Reporting",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Product Safety",
        "effective_date": "2025-06-01",
        "brief": (
            "For smoke, overheating, sparks, electric shock, leaking batteries or other "
            "possible product hazards, tell the customer to stop using the product. If it "
            "is safe to do so, disconnect power without touching damaged or hot components. "
            "Ask the customer to keep others away and contact support promptly with the "
            "order ID and a description. Escalate immediately to the product-safety team. "
            "Do not ask the customer to test the product again."
        ),
    },
    {
        "id": "KB-022",
        "slug": "gift_cards_store_credit",
        "title": "Gift Cards and Store Credit",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "brief": (
            "Gift card balance and validity details should be checked in the customer's "
            "account or on the gift card terms shown at purchase. Store credit is associated "
            "with the eligible customer account and should not be promised as cash. Support "
            "must verify ownership before discussing balance or redemption. Do not invent "
            "expiry periods, transfer rules or cash-out options."
        ),
    },
    {
        "id": "KB-023",
        "slug": "loyalty_points",
        "title": "Loyalty Points Earning and Redemption",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Customer Experience",
        "effective_date": "2025-06-01",
        "brief": (
            "Customers should review their account for eligible points, earning activity "
            "and redemption options. Points are account-linked and should not be transferred "
            "between customers unless the account terms explicitly allow it. Returned or "
            "cancelled purchases may cause associated points to be adjusted. Do not invent "
            "conversion rates, expiry dates or earning percentages."
        ),
    },
    {
        "id": "KB-024",
        "slug": "subscription_orders",
        "title": "Subscription and Recurring Order Management",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Order Management",
        "effective_date": "2025-06-01",
        "brief": (
            "Where a product offers a subscription, the renewal frequency and next renewal "
            "date should be visible in the customer's account before the renewal. Customers "
            "can manage or cancel using the subscription controls shown in their account. "
            "A cancellation request should be confirmed in the account status. Do not invent "
            "a universal notice period or refund entitlement."
        ),
    },
    {
        "id": "KB-025",
        "slug": "customer_support_channels",
        "title": "Customer Support Contact and Case Follow-up",
        "language": "English",
        "version": "1.0",
        "status": "current",
        "owner": "Customer Experience",
        "effective_date": "2025-06-01",
        "brief": (
            "Customers should use the support options displayed in the official "
            "Commerce website or app. They should keep the case or ticket ID for follow-up "
            "and provide only information relevant to the issue. Support agents should "
            "record the channel, issue summary and next action. Do not invent email addresses, "
            "phone numbers, URLs or opening hours."
        ),
    },
    {
        "id": "KB-026",
        "slug": "refund_policy_hindi_v2",
        "title": "धनवापसी नीति",
        "language": "Hindi",
        "version": "2.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "policy_family": "refund_policy",
        "translation_of": "KB-002",
        "brief": (
            "यह KB-002 की वर्तमान Refund Policy का हिंदी संस्करण है। नियम बिल्कुल समान "
            "रखें: डिलीवरी के 10 कैलेंडर दिनों के भीतर पात्र रिटर्न अनुरोध जमा होना चाहिए। "
            "वापस आया सामान प्राप्त और जांचे जाने के बाद 5 कार्यदिवसों के भीतर रिफंड शुरू "
            "किया जाता है। बैंक या भुगतान प्रदाता के खाते में राशि दिखने का समय अलग हो सकता "
            "है; कोई निश्चित बैंक-क्रेडिट समय न बनाएं। पुराने 7 दिन वाले नियम का उल्लेख "
            "वर्तमान नियम के रूप में न करें। पूरा दस्तावेज़ स्वाभाविक, स्पष्ट हिंदी में लिखें।"
        ),
    },
    {
        "id": "KB-027",
        "slug": "order_cancellation_hindi",
        "title": "ऑर्डर रद्द करने की नीति",
        "language": "Hindi",
        "version": "1.0",
        "status": "current",
        "owner": "Order Management",
        "effective_date": "2025-06-01",
        "translation_of": "KB-004",
        "brief": (
            "यह ऑर्डर रद्द करने की नीति का हिंदी संस्करण है। ऑर्डर पैकिंग में जाने से पहले "
            "रद्द किया जा सकता है। पैकिंग या डिस्पैच शुरू होने के बाद रद्द करना संभव न भी हो। "
            "ऐसी स्थिति में ग्राहक सहायता से संपर्क करे और डिलीवरी के बाद लागू रिटर्न प्रक्रिया "
            "का पालन करे। कोई रद्दीकरण शुल्क या गारंटी न बनाएं। पूरा दस्तावेज़ स्वाभाविक हिंदी "
            "में लिखें।"
        ),
    },
    {
        "id": "KB-028",
        "slug": "shipping_delivery_hindi",
        "title": "शिपिंग और डिलीवरी जानकारी",
        "language": "Hindi",
        "version": "1.0",
        "status": "current",
        "owner": "Fulfillment Operations",
        "effective_date": "2025-06-01",
        "translation_of": "KB-005",
        "brief": (
            "यह शिपिंग और डिलीवरी जानकारी का हिंदी संस्करण है। ग्राहक के लिए चेकआउट और "
            "ऑर्डर ट्रैकिंग में दिखाई गई अनुमानित डिलीवरी तारीख ही संदर्भ तारीख है। भुगतान "
            "की पुष्टि, उत्पाद की उपलब्धता और पते की जांच के बाद ऑर्डर प्रोसेस होता है। "
            "डिस्पैच के बाद ट्रैकिंग अपडेट दिखने में समय लग सकता है। कोई निश्चित डिलीवरी "
            "गारंटी या कूरियर का नाम न बनाएं। पूरा दस्तावेज़ स्वाभाविक हिंदी में लिखें।"
        ),
    },
    {
        "id": "KB-029",
        "slug": "damaged_item_hindi",
        "title": "क्षतिग्रस्त या खराब उत्पाद की शिकायत",
        "language": "Hindi",
        "version": "1.0",
        "status": "current",
        "owner": "Returns Operations",
        "effective_date": "2025-06-01",
        "translation_of": "KB-007",
        "brief": (
            "यह क्षतिग्रस्त या खराब उत्पाद की शिकायत का हिंदी संस्करण है। डिलीवरी के "
            "48 घंटों के भीतर दिखाई देने वाली क्षति की सूचना दें। ग्राहक से ऑर्डर ID, उत्पाद "
            "और पैकेजिंग की स्पष्ट तस्वीरें तथा समस्या का संक्षिप्त विवरण लें। यदि उत्पाद "
            "गर्म हो रहा है, धुआँ छोड़ रहा है या बिजली से जुड़ा खतरा दिखाता है, तो उसका "
            "उपयोग बंद करने और सहायता से संपर्क करने को कहें। रिफंड या रिप्लेसमेंट की गारंटी "
            "न दें। पूरा दस्तावेज़ स्वाभाविक हिंदी में लिखें।"
        ),
    },
    {
        "id": "KB-030",
        "slug": "payment_failure_hindi",
        "title": "असफल या लंबित भुगतान के लिए सहायता",
        "language": "Hindi",
        "version": "1.0",
        "status": "current",
        "owner": "Payments Operations",
        "effective_date": "2025-06-01",
        "translation_of": "KB-009",
        "brief": (
            "यह असफल या लंबित भुगतान की प्रक्रिया का हिंदी संस्करण है। ग्राहक पहले ऑर्डर "
            "हिस्ट्री और भुगतान खाते में स्थिति जांचे। यदि पैसे कट गए हों लेकिन ऑर्डर की "
            "पुष्टि न हुई हो, तो सुरक्षित सहायता प्रक्रिया में ट्रांजैक्शन संदर्भ और समय दें। "
            "पासवर्ड, OTP, CVV, PIN या पूरा कार्ड नंबर कभी न मांगें। बैंक की राशि-वापसी "
            "समय-सीमा न बनाएं। पूरा दस्तावेज़ स्वाभाविक हिंदी में लिखें।"
        ),
    },
]


SYSTEM_PROMPT = f"""
You are a senior customer-support policy writer for the fictional company {COMPANY}.
Create concise, operationally useful knowledge-base documents for a RAG system.

FACTS AND SAFETY
- Use only facts in the supplied brief. Never invent timelines, fees, guarantees,
  contact details, legal claims, eligibility rules or service commitments.
- If a detail is missing, say support must verify it; do not make assumptions.
- Keep each document internally consistent and do not introduce conflicting rules.
- The only intentional conflict is between KB-001 (superseded: 7 calendar days
  to request a return; refund initiated within 7 business days after receipt and
  inspection) and KB-002 (current from 2025-06-01: 10 calendar days; refund
  initiated within 5 business days after receipt and inspection). Never mix them.
- Clearly mark superseded documents as historical only. Current documents must not
  present obsolete rules as current.
- Never promise automatic refunds, replacements or compensation unless specified.
- Never request passwords, OTPs, PINs, CVVs or full card numbers.
- For unsafe products, tell customers to stop using them. Never ask them to test
  a smoking, overheating, sparking or otherwise unsafe product.
- Do not include real personal data or contact details.

WRITING
- Write clearly and practically for customers and support agents.
- Explain customer actions, support checks and what cannot be promised.
- Use 3-5 meaningful sections, 100-400 words total, short paragraphs and useful
  bullets. Avoid filler, repetition and marketing language.
- Write entirely in the requested language. Hindi must be natural professional
  Devanagari, not Hinglish.
- Do not repeat the metadata block; Python adds it to the PDF.

OUTPUT
Return one valid JSON object only:
{{
  "summary": "A concise 1-2 sentence summary.",
  "sections": [
    {{"heading": "Heading", "paragraphs": ["Paragraph"], "bullets": ["Rule"]}}
  ]
}}
Each section must contain heading, paragraphs and bullets. Use [] when no bullets.
"""


def build_prompt(spec: dict[str, Any], correction: str = "") -> str:
    return f"""Write {spec['id']} for {COMPANY}.

Title: {spec['title']}
Language: {spec['language']}
Version: {spec['version']}
Status: {spec['status']}
Owner: {spec['owner']}
Effective date: {spec['effective_date']}
Effective to: {spec.get('effective_to') or 'No end date specified'}

Document-specific facts:
{spec['brief']}

Make this document useful on its own. Keep it within the exact scope of the brief.
Do not create missing rules or timelines. {correction}"""


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def content_text(content: dict[str, Any]) -> str:
    parts = [content["summary"]]
    for section in content["sections"]:
        parts.append(section["heading"])
        parts.extend(section["paragraphs"])
        parts.extend(section["bullets"])
    return "\n".join(parts)


def validate_content(content: Any) -> tuple[bool, str]:
    if not isinstance(content, dict):
        return False, "Response is not a JSON object."
    if not isinstance(content.get("summary"), str) or not content["summary"].strip():
        return False, "Missing summary."

    sections = content.get("sections")
    if not isinstance(sections, list) or not 3 <= len(sections) <= 5:
        return False, "Expected 3-5 sections."

    for number, section in enumerate(sections, 1):
        if not isinstance(section, dict) or not isinstance(section.get("heading"), str):
            return False, f"Section {number} has no valid heading."
        for field in ("paragraphs", "bullets"):
            values = section.get(field)
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                return False, f"Section {number}: {field} must contain non-empty strings."
        if not section["paragraphs"] and not section["bullets"]:
            return False, f"Section {number} is empty."

    text = content_text(content)
    words = word_count(text)
    if not 100 <= words <= MAX_WORDS:
        return False, f"Word count is {words}; expected 100-{MAX_WORDS}."
    if any(term in text.casefold() for term in
           ("as an ai", "lorem ipsum", "todo", "insert here", "placeholder")):
        return False, "Found placeholder or AI-referential text."
    return True, f"{words} words; {len(sections)} sections."


def generate_content(client: OpenAI, spec: dict[str, Any], model: str):
    """Call the API, retry transient errors, and return content plus usage."""
    last_error = None
    for content_attempt in range(2):
        correction = ""
        if content_attempt:
            correction = f"Your previous response failed validation: {last_error}. Rewrite it."
        for api_attempt in range(1, MAX_API_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                # Do not pass temperature: some reasoning models accept only its default.
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_prompt(spec, correction)},
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=3000,
                    timeout=90,
                )
                choice = response.choices[0]
                if choice.finish_reason != "stop":
                    raise ValueError(f"Model response ended with {choice.finish_reason}.")
                if not choice.message.content:
                    raise ValueError("Model returned an empty response.")

                content = json.loads(choice.message.content)
                valid, message = validate_content(content)
                if valid:
                    usage = response.usage
                    metrics = {
                        "latency_seconds": round(time.perf_counter() - started, 3),
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                        "total_tokens": getattr(usage, "total_tokens", None),
                    }
                    print(f"    [OK] Content validated: {message}")
                    return content, metrics

                last_error = message
                print(f"    [WARN] Validation failed: {message}")
                break  # Use the second content attempt, not an API retry.

            except (RateLimitError, APIConnectionError, APITimeoutError,
                    InternalServerError) as exc:
                last_error = str(exc)
                if api_attempt == MAX_API_ATTEMPTS:
                    raise
                delay = min(2 ** api_attempt, 30)
                print(f"    [RETRY] {type(exc).__name__}; waiting {delay}s "
                      f"({api_attempt}/{MAX_API_ATTEMPTS})")
                time.sleep(delay)
            except APIStatusError as exc:
                # Retry only rate limits and server-side failures.
                if exc.status_code == 429 or exc.status_code >= 500:
                    last_error = str(exc)
                    if api_attempt == MAX_API_ATTEMPTS:
                        raise
                    delay = min(2 ** api_attempt, 30)
                    print(f"    [RETRY] API {exc.status_code}; waiting {delay}s")
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"OpenAI API rejected the request ({exc.status_code}): {exc}"
                ) from exc
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                print(f"    [WARN] Response issue: {last_error}")
                break

    raise RuntimeError(f"Could not generate valid content for {spec['id']}: {last_error}")


def hindi_shaper():
    try:
        from devanagari_reportlab import Shaper
        return Shaper()
    except ImportError as exc:
        raise RuntimeError(
            "Hindi PDF support is missing. Install the devanagari-reportlab "
            "dependency listed in requirements_knowledge_docs.txt."
        ) from exc


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("KBTitle", parent=base["Title"], fontName="Helvetica-Bold",
                               fontSize=18, leading=22, textColor=colors.HexColor("#17365D"),
                               alignment=TA_LEFT, spaceAfter=5),
        "subtitle": ParagraphStyle("KBSubtitle", parent=base["Normal"], fontSize=9,
                                   leading=12, textColor=colors.HexColor("#526174"),
                                   spaceAfter=10),
        "heading": ParagraphStyle("KBHeading", parent=base["Heading2"], fontSize=11,
                                  leading=14, textColor=colors.HexColor("#1F4E79"),
                                  spaceBefore=8, spaceAfter=4, keepWithNext=True),
        "body": ParagraphStyle("KBBody", parent=base["BodyText"], fontSize=9,
                               leading=12, textColor=colors.HexColor("#202833"),
                               spaceAfter=5),
        "bullet": ParagraphStyle("KBBullet", parent=base["BodyText"], fontSize=8.8,
                                 leading=11.5, leftIndent=12, firstLineIndent=-8,
                                 spaceAfter=3),
        "meta": ParagraphStyle("KBMeta", parent=base["Normal"], fontSize=8,
                               leading=10, textColor=colors.HexColor("#526174")),
        "summary": ParagraphStyle("KBSummary", parent=base["Normal"], fontSize=9.2,
                                  leading=13, textColor=colors.HexColor("#27364A"),
                                  leftIndent=7, rightIndent=7, spaceBefore=5, spaceAfter=8),
    }


def build_pdf(spec: dict[str, Any], content: dict[str, Any], path: Path) -> int:
    hindi = spec["language"] == "Hindi"
    shaper = hindi_shaper() if hindi else None
    styles = make_styles()

    def para(text: str, style: str):
        if shaper:
            mapping = {"title": "title", "subtitle": "subtitle", "heading": "heading",
                       "body": "body", "summary": "body", "bullet": "body"}
            return shaper.paragraph(text, shaper.styles(body_size=9)[mapping[style]])
        return Paragraph(escape(text).replace("\n", "<br/>"), styles[style])

    story = [
        para(spec["title"], "title"),
        para(f"{COMPANY} | Knowledge Base | {spec['id']} | Version {spec['version']}",
             "subtitle"),
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#B7C9D6")),
        Spacer(1, 5),
    ]

    metadata = [
        ["Document ID", spec["id"], "Version", spec["version"]],
        ["Status", spec["status"].upper(), "Language", spec["language"]],
        ["Owner", spec["owner"], "Effective", spec["effective_date"]],
    ]
    if spec.get("effective_to"):
        metadata.append(["Effective to", spec["effective_to"], "Policy family",
                         spec.get("policy_family", "General")])
    elif spec.get("policy_family"):
        metadata.append(["Policy family", spec["policy_family"], "Related document",
                         spec.get("supersedes") or spec.get("translation_of") or "—"])

    table = Table(metadata, colWidths=[25*mm, 48*mm, 27*mm, 55*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F5F8")),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#D5DEE7")),
        ("INNERGRID", (0, 0), (-1, -1), .3, colors.HexColor("#D5DEE7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([table, Spacer(1, 9)])

    if spec["status"] == "superseded":
        warning = ("SUPERSEDED POLICY — historical reference only. Do not use as current."
                   if not hindi else
                   "पुरानी नीति — केवल ऐतिहासिक संदर्भ के लिए। इसे वर्तमान नीति न मानें।")
        warning_style = ParagraphStyle(
            "KBWarning", parent=styles["body"], fontName="Helvetica-Bold",
            textColor=colors.HexColor("#8A3B12"), backColor=colors.HexColor("#FFF1E6"),
            borderColor=colors.HexColor("#E8B48C"), borderWidth=.5, borderPadding=6,
        )
        story.append(Paragraph(escape(warning), warning_style))

    story += [para(content["summary"], "summary"),
              HRFlowable(width="100%", thickness=.4, color=colors.HexColor("#D5DEE7")),
              Spacer(1, 4)]

    for section in content["sections"]:
        items = [para(section["heading"], "heading")]
        items += [para(text, "body") for text in section["paragraphs"]]
        for text in section["bullets"]:
            items.append(para("• " + text, "bullet"))
        story.append(KeepTogether(items))

    def footer(canvas, doc):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(colors.HexColor("#D5DEE7"))
        canvas.setLineWidth(.4)
        canvas.line(18*mm, 14*mm, width-18*mm, 14*mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#687789"))
        canvas.drawString(18*mm, 9*mm,
                          f"{COMPANY} | {spec['id']} | v{spec['version']} | {spec['status'].upper()}")
        canvas.drawRightString(width-18*mm, 9*mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=16*mm, bottomMargin=20*mm,
        title=f"{spec['title']} - {spec['id']} - v{spec['version']}", author=COMPANY,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    pdf_data = buffer.getvalue()
    pages = len(PdfReader(BytesIO(pdf_data)).pages)
    if pages > MAX_PAGES:
        raise ValueError(f"{spec['id']} is {pages} pages; maximum is {MAX_PAGES}.")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".pdf.tmp")
    temp.write_bytes(pdf_data)
    temp.replace(path)
    return pages


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"project": COMPANY, "created_at": datetime.now(timezone.utc).isoformat(),
                "documents": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(data.get("documents"), dict):
            raise ValueError("Missing documents object.")
        return data
    except Exception as exc:
        raise RuntimeError(f"Cannot read manifest {MANIFEST_PATH}: {exc}") from exc


def save_manifest(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp = MANIFEST_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(MANIFEST_PATH)


def filename(spec: dict[str, Any]) -> str:
    return f"{spec['id']}_{spec['slug']}.pdf"


def completed(spec: dict[str, Any], manifest: dict[str, Any]) -> bool:
    entry = manifest["documents"].get(spec["id"])
    return bool(entry and (OUTPUT_DIR / entry.get("file", "")).is_file())


def validate_catalog() -> None:
    ids = [doc["id"] for doc in DOCUMENTS]
    if len(DOCUMENTS) != 30 or len(set(ids)) != 30:
        raise RuntimeError("Catalog must contain exactly 30 unique documents.")
    if sum(doc["language"] == "Hindi" for doc in DOCUMENTS) < 5:
        raise RuntimeError("Catalog must contain at least 5 Hindi documents.")
    old = next(doc for doc in DOCUMENTS if doc["id"] == "KB-001")
    current = next(doc for doc in DOCUMENTS if doc["id"] == "KB-002")
    if not (old["status"] == "superseded" and current["status"] == "current"
            and old.get("superseded_by") == current["id"]
            and current.get("supersedes") == old["id"]):
        raise RuntimeError("Refund policy version relationship is incorrect.")


def generate_one(client: OpenAI, spec: dict[str, Any], model: str,
                 manifest: dict[str, Any]) -> None:
    print(f"\n[{spec['id']}] {spec['title']} | {spec['language']} | v{spec['version']}")
    print(f"    Status: {spec['status']} | Owner: {spec['owner']}")
    content, usage = generate_content(client, spec, model)
    pdf_name = filename(spec)
    pages = build_pdf(spec, content, OUTPUT_DIR / pdf_name)

    manifest["documents"][spec["id"]] = {
        "document_id": spec["id"], "title": spec["title"],
        "language": spec["language"], "version": spec["version"],
        "status": spec["status"], "owner": spec["owner"],
        "effective_date": spec["effective_date"],
        "effective_to": spec.get("effective_to"),
        "policy_family": spec.get("policy_family"),
        "supersedes": spec.get("supersedes"),
        "superseded_by": spec.get("superseded_by"),
        "translation_of": spec.get("translation_of"),
        "file": pdf_name, "pages": pages,
        "word_count": word_count(content_text(content)),
        "model": model, "prompt_version": PROMPT_VERSION,
        "usage": usage, "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_manifest(manifest)
    print(f"    [SAVED] {OUTPUT_DIR / pdf_name} ({pages} page(s))")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a chosen number of support PDFs in automatic batches."
    )
    parser.add_argument("--total-docs", type=int, default=len(DOCUMENTS),
                        help=f"Total number of documents to have generated (default: {len(DOCUMENTS)}).")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Documents per batch (default: {DEFAULT_BATCH_SIZE}).")
    parser.add_argument("--document-id", help="Generate only one document, e.g. KB-001.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model ID.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the automatic batch plan without calling the API.")
    args = parser.parse_args()

    validate_catalog()
    if not 1 <= args.batch_size <= len(DOCUMENTS):
        parser.error(f"--batch-size must be between 1 and {len(DOCUMENTS)}.")
    if not 1 <= args.total_docs <= len(DOCUMENTS):
        parser.error(f"--total-docs must be between 1 and {len(DOCUMENTS)}.")

    manifest = load_manifest()
    pending = [doc for doc in DOCUMENTS if not completed(doc, manifest)]

    # Single-document mode is intentionally separate from bulk generation.
    if args.document_id:
        spec = next((doc for doc in DOCUMENTS if doc["id"] == args.document_id), None)
        if spec is None:
            parser.error(f"Unknown document ID: {args.document_id}")
        if completed(spec, manifest):
            print(f"[SKIP] {args.document_id} is already generated and recorded.")
            return
        selected = [spec]
        target_total = len(DOCUMENTS) - len(pending) + 1
    else:
        already_done = len(DOCUMENTS) - len(pending)
        if args.total_docs < already_done:
            parser.error(
                f"--total-docs ({args.total_docs}) is less than the {already_done} "
                "documents already completed."
            )
        remaining_to_target = args.total_docs - already_done
        selected = pending[:remaining_to_target]
        target_total = args.total_docs

    total_batches = (len(selected) + args.batch_size - 1) // args.batch_size

    print("\n" + "=" * 68)
    print(f"{COMPANY.upper()} - KNOWLEDGE DOCUMENT GENERATOR")
    print("=" * 68)
    print(f"Catalogue documents : {len(DOCUMENTS)}")
    print(f"Target completed    : {target_total}")
    print(f"Already completed   : {len(DOCUMENTS) - len(pending)}")
    print(f"To generate now     : {len(selected)}")
    print(f"Batch size          : {args.batch_size}")
    print(f"Automatic batches   : {total_batches}")
    print(f"Model               : {args.model}")
    print(f"Output folder       : {OUTPUT_DIR}")
    print(f"Manifest            : {MANIFEST_PATH}")

    if not selected:
        print("\n[OK] The requested number of documents is already generated.")
        return

    # Show the exact batches before making any paid API calls.
    for batch_index in range(total_batches):
        start_index = batch_index * args.batch_size
        batch = selected[start_index:start_index + args.batch_size]
        print(f"\nBATCH {batch_index + 1}/{total_batches} ({len(batch)} document(s))")
        for doc in batch:
            print(f"  {doc['id']} | {doc['title']} | {doc['language']} | "
                  f"v{doc['version']} | {doc['status']}")

    if args.dry_run:
        print("\n[DRY RUN] Batch plan displayed. No API calls or files created.")
        return
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY was not found. Check the .env file in the repository root.")

    client = OpenAI()
    generated = 0
    stopped = False

    # Process every batch in this run. Successful documents are saved immediately;
    # if a document fails, stop safely and resume from the next missing document later.
    for batch_index in range(total_batches):
        start_index = batch_index * args.batch_size
        batch = selected[start_index:start_index + args.batch_size]
        print("\n" + "-" * 68)
        print(f"STARTING BATCH {batch_index + 1}/{total_batches}")
        print("-" * 68)

        for spec in batch:
            try:
                generate_one(client, spec, args.model, manifest)
                generated += 1
            except KeyboardInterrupt:
                print("\n[STOPPED] Interrupted. Completed PDFs and manifest entries are preserved.")
                stopped = True
                break
            except Exception as exc:
                print(f"\n[ERROR] {spec['id']} failed: {type(exc).__name__}: {exc}")
                print("[STOPPED] Remaining documents were not attempted. Rerun the same command to resume.")
                stopped = True
                break

        total_done = sum(completed(doc, manifest) for doc in DOCUMENTS)
        print(f"[BATCH COMPLETE] {total_done}/{target_total} target documents completed.")
        if stopped:
            break

    total_done = sum(completed(doc, manifest) for doc in DOCUMENTS)
    remaining_target = max(0, target_total - total_done)
    print("\n" + "=" * 68)
    print("GENERATION SUMMARY")
    print("=" * 68)
    print(f"Generated this run : {generated}")
    print(f"Completed total    : {total_done}/{target_total} target")
    print(f"Remaining to target: {remaining_target}")
    print(f"PDF folder         : {OUTPUT_DIR}")
    print(f"Manifest            : {MANIFEST_PATH}")
    if remaining_target == 0:
        print("\n[SUCCESS] Requested document total has been generated.")
    elif stopped:
        print("\n[RESUME] Fix the reported issue, then rerun the same command. Completed files will be skipped.")


if __name__ == "__main__":
    main()

