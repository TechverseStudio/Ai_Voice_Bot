"""Robust Contact Import and Processing Engine for real estate contact documents."""

import csv
import io
import os
from pathlib import Path
import re
import subprocess
from typing import Any

import pandas as pd
from pypdf import PdfReader
import docx

from backend.crm import is_phone_dnd, get_lead_by_phone


# Common column name heuristics (normalized lowercase)
COLUMN_MAPPINGS = {
    "name": [
        "name", "fullname", "full_name", "customer", "customer_name",
        "client", "client_name", "contact_person", "prospect", "lead", "lead_name", "buyer"
    ],
    "phone": [
        "phone", "mobile", "contact", "cell", "telephone", "tel",
        "calling_number", "whatsapp", "phone_number", "mobile_no", "contact_no", "mobile_number"
    ],
    "email": [
        "email", "e-mail", "mail", "email_id", "mail_id", "email_address"
    ],
    "locality": [
        "locality", "area", "location", "city", "address", "zone", "preferred_location"
    ],
    "budget": [
        "budget", "price", "budget_range", "price_range", "investment"
    ],
    "bhk": [
        "bhk", "configuration", "flat_type", "type", "property_type", "unit_type"
    ],
    "notes": [
        "notes", "remarks", "comments", "requirement", "requirements", "source", "status"
    ],
}


def normalize_and_validate_phone(raw_phone: Any) -> tuple[str, str, str]:
    """Normalize and validate Indian and international mobile numbers.

    Returns:
        (normalized_phone, validation_status, validation_message)
        where validation_status is one of: 'valid', 'review_needed', 'invalid'
    """
    if raw_phone is None or pd.isna(raw_phone):
        return "", "invalid", "Phone number is missing or empty"

    text = str(raw_phone).strip()
    if not text:
        return "", "invalid", "Phone number is empty"

    # Remove floating point decimal from excel imports like 9823456789.0
    if text.endswith(".0"):
        text = text[:-2]

    # Clean non-digit and non-+ characters
    cleaned = re.sub(r"[^\d+]", "", text)

    # Check for obvious dummy sequences
    if re.match(r"^(\+?91)?(0{10}|1{10}|9{10}|1234567890|9876543210)$", cleaned):
        return cleaned, "invalid", "Dummy or placeholder phone number detected"

    # Handle Indian mobile formats
    # 1. +91XXXXXXXXXX
    if cleaned.startswith("+91"):
        digits = cleaned[3:]
        if len(digits) == 10:
            if digits[0] in "6789":
                return f"+91{digits}", "valid", "Valid Indian mobile (+91)"
            else:
                return f"+91{digits}", "review_needed", f"Uncertain Indian mobile starting with {digits[0]}"
        elif len(digits) > 10:
            return cleaned, "review_needed", f"Phone has excessive digits ({len(digits)})"
        else:
            return cleaned, "invalid", f"Incomplete phone number ({len(digits)} digits)"

    # 2. 91XXXXXXXXXX without +
    if cleaned.startswith("91") and len(cleaned) == 12:
        digits = cleaned[2:]
        if digits[0] in "6789":
            return f"+91{digits}", "valid", "Valid Indian mobile (91-prefix normalized)"
        else:
            return f"+91{digits}", "review_needed", f"Uncertain Indian mobile starting with {digits[0]}"

    # 3. 0XXXXXXXXXX (leading 0)
    if cleaned.startswith("0") and len(cleaned) == 11:
        digits = cleaned[1:]
        if digits[0] in "6789":
            return f"+91{digits}", "valid", "Valid Indian mobile (leading-0 normalized)"
        else:
            return f"+91{digits}", "review_needed", f"Uncertain Indian mobile starting with {digits[0]}"

    # 4. Standard 10-digit Indian number
    if cleaned.isdigit() and len(cleaned) == 10:
        if cleaned[0] in "6789":
            return f"+91{cleaned}", "valid", "Valid 10-digit Indian mobile"
        else:
            return f"+91{cleaned}", "review_needed", f"Uncertain Indian mobile prefix '{cleaned[0]}', requires review"

    # 5. International number with +
    if cleaned.startswith("+") and 8 <= len(cleaned[1:]) <= 15 and cleaned[1:].isdigit():
        return cleaned, "valid", "Valid international format"

    # 6. Fallback ambiguous formats
    if cleaned.isdigit() and 7 <= len(cleaned) <= 15:
        return cleaned, "review_needed", f"Uncertain format ({len(cleaned)} digits without country code)"

    return text, "invalid", "Invalid phone number characters or length"


def _match_column_headers(headers: list[str]) -> dict[str, str]:
    """Map raw table headers to standard fields (name, phone, email, etc.)."""
    mapped = {}
    used_headers = set()

    for standard_col, patterns in COLUMN_MAPPINGS.items():
        for h in headers:
            if h in used_headers:
                continue
            norm_h = re.sub(r"[^a-z0-9]", "", str(h).lower())
            for pattern in patterns:
                norm_pat = re.sub(r"[^a-z0-9]", "", pattern.lower())
                if norm_h == norm_pat or (len(norm_h) >= 4 and norm_pat in norm_h):
                    mapped[standard_col] = h
                    used_headers.add(h)
                    break
            if standard_col in mapped:
                break
    return mapped


def parse_tabular_data(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Extract standard contact rows from a pandas DataFrame."""
    headers = [str(col).strip() for col in df.columns]
    mapping = _match_column_headers(headers)

    # Fallback heuristics if phone or name not matched by header
    if "phone" not in mapping:
        for col in df.columns:
            sample_vals = df[col].dropna().astype(str).head(10).tolist()
            digit_counts = [len(re.sub(r"\D", "", v)) for v in sample_vals]
            if any(9 <= c <= 13 for c in digit_counts):
                mapping["phone"] = col
                break

    if "name" not in mapping:
        for col in df.columns:
            if col != mapping.get("phone"):
                mapping["name"] = col
                break

    rows = []
    for _, row in df.iterrows():
        raw_name = str(row[mapping["name"]]).strip() if "name" in mapping and pd.notna(row[mapping["name"]]) else ""
        raw_phone = str(row[mapping["phone"]]).strip() if "phone" in mapping and pd.notna(row[mapping["phone"]]) else ""
        raw_email = str(row[mapping["email"]]).strip() if "email" in mapping and pd.notna(row[mapping["email"]]) else ""
        raw_locality = str(row[mapping["locality"]]).strip() if "locality" in mapping and pd.notna(row[mapping["locality"]]) else ""
        raw_budget = str(row[mapping["budget"]]).strip() if "budget" in mapping and pd.notna(row[mapping["budget"]]) else ""
        raw_bhk = str(row[mapping["bhk"]]).strip() if "bhk" in mapping and pd.notna(row[mapping["bhk"]]) else ""
        raw_notes = str(row[mapping["notes"]]).strip() if "notes" in mapping and pd.notna(row[mapping["notes"]]) else ""

        # Skip completely empty rows
        if not raw_name and not raw_phone:
            continue

        rows.append({
            "name": raw_name,
            "raw_phone": raw_phone,
            "email": raw_email,
            "locality": raw_locality,
            "budget": raw_budget,
            "bhk": raw_bhk,
            "notes": raw_notes,
        })
    return rows


def parse_excel(file_path: str) -> list[dict[str, Any]]:
    """Parse Excel spreadsheet (.xlsx, .xls)."""
    df = pd.read_excel(file_path, sheet_name=0)
    return parse_tabular_data(df)


def parse_csv_file(file_path: str) -> list[dict[str, Any]]:
    """Parse CSV with delimiter and encoding auto-detection."""
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                sample = f.read(4096)
                dialect = csv.Sniffer().sniff(sample, delimiters=",	;|")
                delimiter = dialect.delimiter
            df = pd.read_csv(file_path, encoding=enc, sep=delimiter)
            return parse_tabular_data(df)
        except Exception:
            continue
    # Fallback simple read
    df = pd.read_csv(file_path)
    return parse_tabular_data(df)


def parse_word_docx(file_path: str) -> list[dict[str, Any]]:
    """Parse Word Document (.docx) checking both tables and paragraphs."""
    doc = docx.Document(file_path)
    rows = []

    # 1. Parse tables if present
    for table in doc.tables:
        if len(table.rows) > 1:
            headers = [cell.text.strip() for cell in table.rows[0].cells]
            table_data = []
            for tr in table.rows[1:]:
                row_vals = [cell.text.strip() for cell in tr.cells]
                table_data.append(dict(zip(headers, row_vals)))
            if table_data:
                df = pd.DataFrame(table_data)
                rows.extend(parse_tabular_data(df))

    if rows:
        return rows

    # 2. Parse text lines/paragraphs
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        parsed = _parse_unstructured_line(text)
        if parsed:
            rows.append(parsed)

    return rows


def parse_pdf_file(file_path: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse PDF document using pypdf and pdftotext.

    Returns:
        (rows, is_scanned_without_ocr)
    """
    rows = []
    text_content = ""

    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            t = page.extract_text() or ""
            text_content += t + chr(10)
    except Exception:
        pass

    if len(text_content.strip()) < 20:
        # Fallback to pdftotext system binary
        try:
            res = subprocess.run(["pdftotext", file_path, "-"], capture_output=True, text=True, check=True)
            text_content = res.stdout
        except Exception:
            pass

    if len(text_content.strip()) < 20:
        # Scanned document without extractable text layer
        return [], True

    # Parse lines
    for line in text_content.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = _parse_unstructured_line(line)
        if parsed:
            rows.append(parsed)

    return rows, False


def parse_text_file(file_path: str) -> list[dict[str, Any]]:
    """Parse plain text file line by line."""
    rows = []
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # Check if CSV/TSV format
    if lines and any(delimiter in lines[0] for delimiter in [",", "	", "|"]):
        try:
            df = pd.read_csv(io.StringIO("".join(lines)))
            if len(df.columns) > 1:
                return parse_tabular_data(df)
        except Exception:
            pass

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parsed = _parse_unstructured_line(line)
        if parsed:
            rows.append(parsed)
    return rows


def _parse_unstructured_line(line: str) -> dict[str, Any] | None:
    """Extract contact information from an unstructured text line."""
    # Look for Indian mobile or phone number pattern
    phone_match = re.search(r"(\+?91[\-\s]?)?[6-9]\d{9}", line)
    if not phone_match:
        phone_match = re.search(r"\d{10,12}", line)

    if not phone_match:
        return None

    raw_phone = phone_match.group(0).strip()
    remaining = (line[:phone_match.start()] + " " + line[phone_match.end()]).strip()

    # Extract email if present
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", remaining)
    email = email_match.group(0) if email_match else ""
    if email_match:
        remaining = (remaining[:email_match.start()] + " " + remaining[email_match.end()]).strip()

    # Clean remaining string for customer name and locality
    cleaned_name = re.sub(r"^(name|customer|client|mr|ms|mrs)[\s:\-\.]+", "", remaining, flags=re.IGNORECASE).strip()
    parts = [p.strip() for p in re.split(r"[,|\-–]", cleaned_name) if p.strip()]

    name = parts[0] if parts else "Customer"
    locality = parts[1] if len(parts) > 1 else ""

    return {
        "name": name,
        "raw_phone": raw_phone,
        "email": email,
        "locality": locality,
        "budget": "",
        "bhk": "",
        "notes": "",
    }


def process_contact_document(file_path: str, filename: str) -> dict[str, Any]:
    """Process an uploaded contact document and return validation summary and rows.

    Supports: .xlsx, .xls, .csv, .docx, .pdf, .txt
    """
    ext = Path(filename).suffix.lower()
    raw_contacts: list[dict[str, Any]] = []
    scanned_alert = False

    if ext in [".xlsx", ".xls"]:
        raw_contacts = parse_excel(file_path)
    elif ext == ".csv":
        raw_contacts = parse_csv_file(file_path)
    elif ext == ".docx":
        raw_contacts = parse_word_docx(file_path)
    elif ext == ".pdf":
        raw_contacts, scanned_alert = parse_pdf_file(file_path)
    elif ext == ".txt":
        raw_contacts = parse_text_file(file_path)
    else:
        raise ValueError(f"Unsupported file format '{ext}'. Supported: .xlsx, .xls, .csv, .pdf, .docx, .txt")

    if not raw_contacts and scanned_alert:
        return {
            "summary": {
                "total_rows": 0,
                "valid_rows": 0,
                "duplicate_rows": 0,
                "invalid_rows": 0,
                "review_needed_rows": 0,
                "filename": filename,
                "file_type": ext.lstrip("."),
                "ocr_status": "Scanned document detected without extractable text layer. Please provide high-resolution OCR text or manual entry.",
            },
            "rows": [],
        }

    # Validate, normalize, and detect duplicates
    seen_in_batch = set()
    validated_rows = []
    valid_count = 0
    duplicate_count = 0
    invalid_count = 0
    review_needed_count = 0

    for idx, item in enumerate(raw_contacts, start=1):
        name = item.get("name", "").strip()
        raw_phone = item.get("raw_phone", "").strip()
        email = item.get("email", "").strip()
        locality = item.get("locality", "").strip()
        budget = item.get("budget", "").strip()
        bhk = item.get("bhk", "").strip()
        notes = item.get("notes", "").strip()

        normalized_phone, status, message = normalize_and_validate_phone(raw_phone)

        # Duplicate check within current batch
        if normalized_phone in seen_in_batch and status == "valid":
            status = "duplicate"
            message = "Duplicate number found within this uploaded document"
        elif status == "valid":
            seen_in_batch.add(normalized_phone)

        # Check against existing DND / Opt-out list
        is_dnd = False
        if normalized_phone and is_phone_dnd(normalized_phone):
            is_dnd = True
            status = "opted_out"
            message = "Registered on Do-Not-Call (DND) / Opt-Out List"

        # Check existing lead in CRM
        if status == "valid" and normalized_phone:
            existing_lead = get_lead_by_phone(normalized_phone)
            if existing_lead:
                message = f"Existing CRM Lead found: {existing_lead.name} ({existing_lead.interest_status})"

        if status == "valid":
            valid_count += 1
        elif status == "duplicate":
            duplicate_count += 1
        elif status in ["review_needed", "opted_out"]:
            review_needed_count += 1
        else:
            invalid_count += 1

        validated_rows.append({
            "index": idx,
            "name": name or "Prospective Buyer",
            "phone_number": normalized_phone,
            "raw_phone": raw_phone,
            "email": email,
            "locality": locality,
            "budget": budget,
            "bhk": bhk,
            "notes": notes,
            "validation_status": status,
            "validation_message": message,
            "is_dnd": is_dnd,
        })

    summary = {
        "total_rows": len(validated_rows),
        "valid_rows": valid_count,
        "duplicate_rows": duplicate_count,
        "invalid_rows": invalid_count,
        "review_needed_rows": review_needed_count,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "ocr_status": "Ready",
    }

    return {"summary": summary, "rows": validated_rows}
