"""
Canonical status vocabularies for every status-writing endpoint.

PENTEST FIX (finding 12): status fields drive each portal's state machine and
are persisted as-is, so they must never be free-form strings — an arbitrary
value (or a megabyte payload) corrupts the pipeline views, breaks the clients'
state logic, and is an unbounded DB-write primitive. Each schema annotates its
field with one of these ``Literal`` types, so FastAPI rejects anything outside
the vocabulary with a 422 BEFORE any handler or database code runs.
"""
from typing import Literal

# Every state a single order, parent order or shop sub-order can be in
# (union of businessFlow.OrderStatus, the shop pipeline buttons, and the
# admin tools' status prompt).
OrderStatus = Literal[
    "Pending",
    "Placed",
    "Pending Payment",
    "Pending Acceptance",
    "Accepted",
    "Confirmed",
    "Preparing",
    "Ready",
    "Delivered",
    "Completed",
    "Cancelled",
    "Failed",
    "Refunded",
    "Rejected",
]

# The subset a shopkeeper may set on their OWN orders — they can move an order
# through the shop pipeline, never into payment states (Pending Payment etc.).
VendorOrderStatus = Literal[
    "Accepted",
    "Cancelled",
    "Preparing",
    "Ready",
    "Delivered",
    "Completed",
    "Rejected",
]

# payments.status — written by checkout, the cancel flow and admin verification.
PaymentStatus = Literal["Pending", "Success", "Failed", "Cancelled", "Rejected"]

# share_payments.status — the vendor's ₹10-per-order ledger.
SharePaymentStatus = Literal["Pending", "Completed", "Rejected"]

# complaints.status — 'New' is the row seed, the rest are the admin buttons.
ComplaintStatus = Literal["New", "Open", "Under Review", "Resolved", "Closed"]

# refunds.status — 'Pending' is the row seed.
RefundStatus = Literal["Pending", "Processed", "Rejected", "Completed"]

# menu_change_requests.status — 'Pending' is the row seed.
MenuChangeStatus = Literal["Pending", "Approved", "Rejected"]

# shops.status — matches frontend businessFlow.ShopStatus.
ShopStatus = Literal["Open", "Busy", "Closed", "Maintenance"]

# shops.approval_status — set by approve/reject/suspend/restore flows.
ShopApprovalStatus = Literal[
    "Approved", "Pending Approval", "Rejected", "Suspended", "Removed",
]
