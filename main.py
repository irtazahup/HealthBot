import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import requests
from supabase import create_client, Client
from datetime import datetime
from processor import process_whatsapp_webhook
from fastapi import BackgroundTasks

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


@app.post("/webhook")
async def handle_messages(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    
    # Check if this is a message event (not a status update)
    value = payload.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {})
    if "messages" in value:
        # HAND OFF TO BACKGROUND
        background_tasks.add_task(process_whatsapp_webhook, payload)
    
    # RETURN 200 OK IMMEDIATELY
    return {"status": "success"}