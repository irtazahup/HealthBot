import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import requests

load_dotenv()

app = FastAPI()

# Credentials from your .env
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = "med_companion_secret_2024" # Choose a string for verification

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
    # print("handle_messages payload:", payload)  # Debugging line
    # Check if this is a WhatsApp message
    if "object" in payload and payload["object"] == "whatsapp_business_account":
        for entry in payload.get("entries", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                
                if messages:
                    msg = messages[0]
                    sender_number = msg.get("from")
                    
                    # Logic for text messages
                    if msg.get("type") == "text":
                        text_body = msg["text"]["body"]
                        print(f"Received: '{text_body}' from {sender_number}")
                        
                        # A simple auto-reply for testing
                        send_simple_message(sender_number, f"Hello! I received: {text_body}")

    return {"status": "success"}

def send_simple_message(to, text):
    print(f"Sending message to {to}: {text}")  # Debugging line
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()