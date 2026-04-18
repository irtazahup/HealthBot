import os
from datetime import datetime, date
from dotenv import load_dotenv
from supabase import create_client, Client
import requests
from apscheduler.schedulers.blocking import BlockingScheduler

load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
# Setup Supabase
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def _parse_iso_date(raw_value):
    if not raw_value:
        return None
    try:
        return date.fromisoformat(str(raw_value))
    except ValueError:
        return None


def _is_active_window(start_date_raw, end_date_raw, today_date):
    start_date = _parse_iso_date(start_date_raw)
    end_date = _parse_iso_date(end_date_raw)

    if not start_date or not end_date:
        return False

    return start_date <= today_date <= end_date

def send_medication_reminder(to_number, med_name, reminder_id):
    url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    print(f"Sending reminder for {med_name} to {to_number} with reminder ID {reminder_id}")
    
    # This is the "Interactive" message with buttons
    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": f"💊 Time for your medicine: *{med_name}*"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"taken_{reminder_id}", # We embed the ID to know WHICH reminder was taken
                            "title": "Taken ✅"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"skipped_{reminder_id}",
                            "title": "Skip ❌"
                        }
                    }
                ]
            }
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    print(f"Full Meta Error: {response.json()}") # Add this line!
    print(f"Reminder sent to {to_number}. Status: {response.status_code}")

def check_reminders():
    now = datetime.now()
    current_time = now.strftime("%H:%M:00") # Format: 08:00:00
    today_date = now.date()
    today_iso = today_date.isoformat()

    print(f"Checking for reminders at {current_time}...")

    # Query: Find reminders where time matches AND current date is between start/end dates
    # We join with medications and profiles to get the phone number
    query = supabase.table("reminders").select(
        "id, reminder_time, medications!inner(med_name, start_date, end_date, profiles!inner(patient_phone))"
    ).eq("reminder_time", current_time) \
     .lte("medications.start_date", today_iso) \
     .gte("medications.end_date", today_iso) \
     .execute()

    for r in query.data:
        med = r['medications']
        # Defensive check in code as a second safety layer.
        if _is_active_window(med.get('start_date'), med.get('end_date'), today_date):
            phone = med['profiles']['patient_phone'].replace("+", "")
            send_medication_reminder(phone, med['med_name'], r['id'])

# Setup the background loop
scheduler = BlockingScheduler()
scheduler.add_job(check_reminders, 'cron', second=0) # Runs exactly at the start of every minute

if __name__ == "__main__":
    print("Reminder Heartbeat Started...")
    scheduler.start()