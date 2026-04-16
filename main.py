import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import requests
from supabase import create_client, Client


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
        # Navigate the JSON structure Meta sends
        value = payload['entry'][0]['changes'][0]['value']
        messages = value.get('messages')
        
        if messages:
            msg = messages[0]
            sender_number = msg.get("from") # This is the user's phone number
            
            if msg.get("type") == "text":
                user_text = msg["text"]["body"]
                
                # --- NEW: SUPABASE LOOKUP ---
                # Search for the user by their phone number
                # Clean the incoming number just in case
                clean_number = sender_number.replace("+", "")

                # Search for the user
                user_profile = supabase.table("profiles") \
                .select("*") \
                .or_(f"patient_phone.ilike.%{clean_number}%,attendant_phone.ilike.%{clean_number}%") \
                .execute()

                if user_profile.data:
                    patient_name = user_profile.data[0]['patient_name']
                    response_text = f"Welcome back, {patient_name}! How can I help with your health today?"
                else:
                    response_text = "I don't recognize this number. Please register via our web form first!"
                
                # Send the response back to WhatsApp
                send_template_message(sender_number, response_text)

    except Exception as e:
        print(f"Error processing message: {e}")

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