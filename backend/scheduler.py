"""Slot validation and site visit booking engine for real estate appointments."""

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from backend.crm import (
    Appointment,
    create_appointment,
    get_appointments,
    update_appointment,
    log_audit,
)


SALES_SPECIALISTS = [
    "Rohit Verma (Senior Property Specialist)",
    "Ananya Sharma (Senior Residential Advisor)",
    "Vikram Malhotra (Luxury Estate Consultant)",
    "Kavita Deshmukh (Site Visit Coordinator)",
]


def parse_natural_date(date_text: str) -> tuple[str, bool]:
    """Parse natural date expressions into YYYY-MM-DD format.

    Returns:
        (formatted_date, is_confirmed_date)
    """
    text = (date_text or "").strip().lower()
    now = datetime.now()

    # Exact date pattern YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text, True

    # DD/MM/YYYY or DD-MM-YYYY
    match_dmy = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", text)
    if match_dmy:
        d, m, y = match_dmy.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}", True

    if "today" in text:
        return now.strftime("%Y-%m-%d"), True
    if "tomorrow" in text:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d"), True

    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for idx, day in enumerate(days_of_week):
        if day in text:
            today_idx = now.weekday()
            days_ahead = (idx - today_idx) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week's day
            target = now + timedelta(days=days_ahead)
            return target.strftime("%Y-%m-%d"), True

    if "this weekend" in text or "weekend" in text:
        # Defaults to upcoming Saturday
        today_idx = now.weekday()
        days_to_sat = (5 - today_idx) % 7
        if days_to_sat == 0 and now.hour > 14:
            days_to_sat = 7
        target = now + timedelta(days=days_to_sat)
        return target.strftime("%Y-%m-%d"), True

    # Ambiguous date
    return (now + timedelta(days=2)).strftime("%Y-%m-%d"), False


def parse_natural_time(time_text: str) -> tuple[str, bool]:
    """Parse natural time expressions into HH:MM AM/PM format.

    Returns:
        (formatted_time, is_valid_slot)
    """
    text = (time_text or "").strip().lower()

    if "morning" in text:
        return "11:00 AM", True
    if "afternoon" in text:
        return "03:00 PM", True
    if "evening" in text:
        return "05:00 PM", True

    match_time = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if match_time:
        hour = int(match_time.group(1))
        minute = int(match_time.group(2) or 0)
        ampm = (match_time.group(3) or "").lower()

        if not ampm:
            if hour in range(9, 12):
                ampm = "am"
            elif hour in range(1, 8):
                ampm = "pm"
            elif hour in range(12, 19):
                ampm = "pm"
                if hour > 12:
                    hour -= 12
            else:
                ampm = "am"

        # Validate operating window: 10:00 AM to 06:30 PM
        military_hour = hour if ampm == "am" else (hour + 12 if hour != 12 else 12)
        if ampm == "am" and hour == 12:
            military_hour = 0

        is_operating_hours = (10 <= military_hour < 18) or (military_hour == 18 and minute <= 30)
        formatted = f"{hour:02d}:{minute:02d} {ampm.upper()}"
        return formatted, is_operating_hours

    return "11:00 AM", True


def validate_and_book_appointment(
    lead_id: int,
    requested_date_raw: str,
    requested_time_raw: str,
    project_name: str = "Krishna's AI Property - Wakad",
    meeting_type: str = "Site Visit",
    customer_notes: str = "",
    campaign_id: int | None = None,
) -> dict[str, Any]:
    """Validate requested appointment slot against operating rules and book appointment.

    Returns confirmed or pending status with confirmation code and assigned specialist.
    """
    date_str, date_is_exact = parse_natural_date(requested_date_raw)
    time_str, time_is_valid_slot = parse_natural_time(requested_time_raw)

    existing_appts = get_appointments()
    same_slot_count = len([
        a for a in existing_appts
        if a.requested_date == date_str and a.requested_time == time_str and a.status == "confirmed"
    ])

    specialist_idx = (lead_id or 0) % len(SALES_SPECIALISTS)
    specialist = SALES_SPECIALISTS[specialist_idx]

    # Slot availability: max 3 concurrent appointments per hour
    if date_is_exact and time_is_valid_slot and same_slot_count < 3:
        status = "confirmed"
        notes = f"Validated slot ({same_slot_count + 1}/3 capacity). Assigned to {specialist}."
    else:
        status = "pending"
        notes = (
            f"Tentative request awaiting manual manager confirmation. "
            f"(Date exact: {date_is_exact}, Within hours: {time_is_valid_slot}, Slot count: {same_slot_count})"
        )

    if customer_notes:
        notes = f"{notes} | Customer note: {customer_notes}"

    appt = create_appointment(
        lead_id=lead_id,
        campaign_id=campaign_id,
        project_name=project_name,
        meeting_type=meeting_type,
        requested_date=date_str,
        requested_time=time_str,
        assigned_salesperson=specialist,
        customer_notes=notes,
        status=status,
    )

    log_audit("APPOINTMENT_SCHEDULED", "Appointment", str(appt.id), f"Status: {status}, Date: {date_str} {time_str}")

    return {
        "appointment_id": appt.id,
        "status": status,
        "confirmation_code": appt.confirmation_code,
        "date": date_str,
        "time": time_str,
        "confirmed_date_time": appt.confirmed_date_time,
        "assigned_salesperson": specialist,
        "meeting_type": meeting_type,
        "message": (
            f"Site visit successfully confirmed for {date_str} at {time_str}. Confirmation Code: {appt.confirmation_code}"
            if status == "confirmed"
            else f"Site visit request recorded for {date_str} at {time_str}. Pending sales manager confirmation."
        ),
    }


def reschedule_site_visit(appt_id: int, new_date_raw: str, new_time_raw: str) -> dict[str, Any]:
    """Reschedule an existing appointment."""
    date_str, _ = parse_natural_date(new_date_raw)
    time_str, _ = parse_natural_time(new_time_raw)

    appt = update_appointment(
        appt_id=appt_id,
        status="rescheduled",
        new_date=date_str,
        new_time=time_str,
        notes=f"Rescheduled to {date_str} at {time_str}",
    )
    return {
        "appointment_id": appt.id,
        "status": appt.status,
        "new_date": date_str,
        "new_time": time_str,
        "confirmed_date_time": appt.confirmed_date_time,
    }


def cancel_site_visit(appt_id: int, reason: str = "Customer requested cancellation") -> dict[str, Any]:
    """Cancel an existing appointment."""
    appt = update_appointment(
        appt_id=appt_id,
        status="cancelled",
        notes=f"Cancelled: {reason}",
    )
    return {
        "appointment_id": appt.id,
        "status": appt.status,
        "reason": reason,
    }
