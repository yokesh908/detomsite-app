"""Conservative bank-credit parsing: unknown formats require manual review."""
import re


def is_credit(text: str) -> bool:
    return bool(re.search(r"\b(credited|credit|deposited|received|rcvd)\b", text, re.I)) and not re.search(
        r"\b(debit(?:ed)?|deducted|otp|failed|reversed|refund(?:ed)?|request)\b", text, re.I
    )


def extract_utr(text: str) -> str:
    if not is_credit(text):
        return ""
    matches = re.findall(
        r"\b(?:utr|ref(?:erence)?|rrn)(?:\s*(?:no\.?|number))?\s*[:.#-]?\s*([a-z0-9]{8,30})\b",
        text, re.I,
    )
    values = {v.upper() for v in matches if any(c.isdigit() for c in v)}
    return values.pop() if len(values) == 1 else ""


def extract_amount(text: str) -> float | None:
    if not is_credit(text):
        return None
    values = []
    for m in re.finditer(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)(?![\d.])", text, re.I):
        before = text[max(0, m.start() - 40):m.start()]
        if re.search(r"\b(?:bal(?:ance)?|available|avl)\b[^₹\d]*$", before, re.I):
            continue
        value = float(m.group(1).replace(",", ""))
        if value > 0:
            values.append(value)
    return values[0] if len(values) == 1 else None
