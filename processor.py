import os
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

from brain import ask_health_agent

load_dotenv()

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def send_simple_message(to, text):
    url = f"https://graph.facebook.com/v25.0/{os.getenv('PHONE_NUMBER_ID')}/messages"
    headers = {
        "Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def process_whatsapp_webhook(payload):
    try:
        value = payload['entry'][0]['changes'][0]['value']
        messages = value.get('messages')
        
        if not messages:
            return

        msg = messages[0]
        sender_number = msg.get("from")
        clean_number = sender_number.replace("+", "")

        # 1. Identity Check
        user_profile = supabase.table("profiles").select("*") \
            .or_(f"patient_phone.ilike.%{clean_number}%,attendant_phone.ilike.%{clean_number}%") \
            .execute()

        if not user_profile.data:
            send_simple_message(sender_number, "I don't recognize this number. Please register first!")
            return

        patient_data = user_profile.data[0]
        patient_id = patient_data['id']
        patient_name = patient_data['patient_name']

        # 2. Handle BUTTON CLICKS (Adherence)
        if msg.get("type") == "interactive":
            button_reply = msg['interactive']['button_reply']
            button_id = button_reply['id'] 
            status = "taken" if "taken_" in button_id else "skipped"
            reminder_id = button_id.replace("taken_", "").replace("skipped_", "")
            
            existing_log = supabase.table("adherence_logs").select("*").eq("reminder_id", reminder_id).execute()

            if existing_log.data:
                current_status = existing_log.data[0]['status']
                send_simple_message(sender_number, f"This was already marked as *{current_status}*.")
                return

            supabase.table("adherence_logs").insert({
                "profile_id": patient_id,
                "reminder_id": reminder_id,
                "status": status,
                "scheduled_time": datetime.now().isoformat(),
                "responded_at": datetime.now().isoformat()
            }).execute()

            ack_text = "✅ Great! Stay healthy." if status == "taken" else "⚠️ Noted. Stay safe!"
            send_simple_message(sender_number, ack_text)

        # 3. Handle TEXT MESSAGES (AI Intelligence)
        elif msg.get("type") == "text":
            user_text = msg["text"]["body"]

            # A. Save User Message to Conversations
            supabase.table("conversations").insert({
                "profile_id": patient_id,
                "role": "user",
                "content": user_text
            }).execute()

            # B. Fetch Medication Data
            med_query = supabase.table("medications").select("med_name, dosage").eq("profile_id", patient_id).execute()
            med_context = str(med_query.data) if med_query.data else "No active medications."

            # C. Fetch Adherence Logs (Last 7 Days)
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            adherence_query = supabase.table("adherence_logs") \
                .select("status, scheduled_time, reminders(reminder_time)") \
                .eq("profile_id", patient_id) \
                .gte("scheduled_time", seven_days_ago) \
                .execute()
            adherence_context = str(adherence_query.data) if adherence_query.data else "No recent logs."

            # D. Fetch Chat History (Last 5 messages)
            history_query = supabase.table("conversations") \
                .select("role, content") \
                .eq("profile_id", patient_id) \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()
            chat_history = history_query.data[::-1] # Reverse to get chronological order

            # E. Generate AI Response
            ai_reply = ask_health_agent(user_text, patient_name, med_context, adherence_context, chat_history)
            
            # F. Save Assistant Response & Send
            supabase.table("conversations").insert({
                "profile_id": patient_id,
                "role": "assistant",
                "content": ai_reply
            }).execute()
            
            send_simple_message(sender_number, ai_reply)

    except Exception as e:
        print(f"Error in background processor: {e}")