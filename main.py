import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import requests
from supabase import create_client, Client
from datetime import datetime

load_dotenv()

app = FastAPI()

# Credentials from your .env
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = "med_companion_secret_2024" # Choose a string for verification
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize the Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.get("/")
async def root():
    return {"message": "Health Agent Backend is Running"}

# --- STEP 1: WEBHOOK VERIFICATION (For Meta Dashboard) ---
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return Response(content=challenge, media_type="text/plain")
    
    return Response(content="Verification failed", status_code=403)

# --- STEP 2: INCOMING MESSAGE HANDLER ---
@app.post("/webhook")
async def handle_messages(request: Request):
    payload = await request.json()
    
    try:
        value = payload['entry'][0]['changes'][0]['value']
        messages = value.get('messages')
        
        if not messages:
            return {"status": "no messages"}

        msg = messages[0]
        sender_number = msg.get("from")
        clean_number = sender_number.replace("+", "")

        # 1. Identity Check
        user_profile = supabase.table("profiles").select("*") \
            .or_(f"patient_phone.ilike.%{clean_number}%,attendant_phone.ilike.%{clean_number}%") \
            .execute()

        if not user_profile.data:
            send_template_message(sender_number, "I don't recognize this number. Please register first!")
            return {"status": "unrecognized"}

        patient_data = user_profile.data[0]
        patient_id = patient_data['id']
        patient_name = patient_data['patient_name']

        # 2. Handle BUTTON CLICKS (Adherence)
       # 2. Handle BUTTON CLICKS (Adherence)
        # 2. Handle BUTTON CLICKS (Adherence)
        if msg.get("type") == "interactive":
            button_reply = msg['interactive']['button_reply']
            button_id = button_reply['id'] 
            
            status = "taken" if "taken_" in button_id else "skipped"
            reminder_id = button_id.replace("taken_", "").replace("skipped_", "")
            
            # Use the current time to check against the scheduled slot
            # Note: We query based on reminder_id since that's unique per slot anyway
            existing_log = supabase.table("adherence_logs") \
                .select("*") \
                .eq("reminder_id", reminder_id) \
                .execute()

            if existing_log.data:
                # User already clicked a button for this specific reminder
                current_status = existing_log.data[0]['status']
                send_template_message(sender_number, f"This was already marked as *{current_status}*.")
                return {"status": "already_responded"}

            # If no log exists, proceed with the insert using your schema columns
            supabase.table("adherence_logs").insert({
                "profile_id": patient_id,
                "reminder_id": reminder_id,
                # medication_id is in your schema, we should probably grab it or leave it null
                "status": status,
                "scheduled_time": datetime.now().isoformat(), # This matches your unique constraint
                "responded_at": datetime.now().isoformat()
            }).execute()

            ack_text = "✅ Great! Stay healthy." if status == "taken" else "⚠️ Noted. Stay safe!"
            send_template_message(sender_number, ack_text)
        # 3. Handle TEXT MESSAGES (AI Query)
        elif msg.get("type") == "text":
            user_text = msg["text"]["body"]
            
            # # Use Gemini to answer
            # prompt = f"Patient {patient_name} asks: {user_text}. Context: This is a healthcare bot."
            # gemini_response = model.generate_content(prompt) # Assuming 'model' is initialized
            
            send_template_message(sender_number, "Sorry, AI response is not implemented yet. But I got your message!")

    except Exception as e:
        print(f"Error: {e}")

    return {"status": "success"}


def send_template_message(to,text):
    url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text}  # This is where your 'Welcome back' string goes
    }
    response = requests.post(url, headers=headers, json=data)
    print(f"Meta API Response: {response.json()}")
    return response.json()