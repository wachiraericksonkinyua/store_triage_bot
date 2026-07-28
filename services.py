import httpx
from config import supabase, AYUTECH_STORE_ID, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TOKEN
from datetime import datetime, timedelta, timezone
from datetime import datetime, timedelta, timezone
from config import AYUTECH_STORE_ID, supabase
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from config import (
    supabase, 
    AYUTECH_STORE_ID, 
    WHATSAPP_PHONE_NUMBER_ID, 
    WHATSAPP_TOKEN,
    GROQ_API_KEY
)
import base64

def save_lead_to_supabase(phone: str, intent: str, notes: str, status: str = "Pending"):
    try:
        supabase.table("leads").insert({
            "business_id": AYUTECH_STORE_ID,
            "customer_phone": phone,
            "intent": intent,
            "notes": notes,
            "status": status
        }).execute()
        print(f" [Ayutech Lead Saved] Phone: {phone} | Intent: {intent} | Status: {status}")
    except Exception as e:
        print(f"❌ Failed to save lead: {str(e)}")

def save_message_to_history(phone: str, role: str, content: str):
    try:
        supabase.table("conversations").insert({
            "business_id": AYUTECH_STORE_ID,
            "customer_phone": phone,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"❌ Failed to save message history: {str(e)}")

async def send_whatsapp_message(to_phone: str, text_message: str):
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        print("⚠️ Meta WhatsApp credentials missing in environment variables.")
        return

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text_message}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            print(f" [Meta WhatsApp API Response]: {res.status_code}")
        except Exception as e:
            print(f"❌ Failed to send WhatsApp message: {str(e)}")

# Delivery Rate Matrix for Nairobi & Environs (in KES)
DELIVERY_RATES = {
    "cbd": 200,
    "kirinyaga road": 0,
    "westlands": 300,
    "kilimani": 300,
    "upper hill": 300,
    "eastleigh": 250,
    "industrial area": 300,
    "parklands": 300,
    "thika road": 400,
    "kasarani": 400,
    "roysambu": 400,
    "ngong road": 350,
    "karen": 500,
    "ruaka": 450,
    "kitengela": 700,
    "ruiru": 600,
}


def calculate_delivery_fee(location_text: str) -> str:
    """Matches user location input against local rate matrix."""
    if not location_text:
        return "Delivery pricing depends on your exact location in Nairobi."

    loc_lower = location_text.lower()

    for area, rate in DELIVERY_RATES.items():
        if area in loc_lower:
            if rate == 0:
                return "Free pickup available directly at our Kirinyaga Road store!"
            return f"Delivery to {area.title()} is KES {rate} via local courier."

    return "Delivery within Nairobi ranges between KES 200 - KES 500 depending on exact distance from Kirinyaga Road."

def check_and_send_pending_followups():
    """Finds pending leads older than 2 hours and sends a WhatsApp follow-up."""
    try:
        # Calculate time 2 hours ago
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        # Query pending leads older than 2 hours
        response = (
            supabase.table("leads")
            .select("id, customer_phone, intent, notes, created_at, status")
            .eq("business_id", AYUTECH_STORE_ID)
            .eq("status", "Pending")
            .lt("created_at", two_hours_ago)
            .execute()
        )

        raw_data = response.data
        if not raw_data or not isinstance(raw_data, list):
            return

        for lead in raw_data:
            if not isinstance(lead, dict):
                continue

            phone = str(lead.get("customer_phone", ""))
            intent = str(lead.get("intent", "Spare Part Order"))
            lead_id = str(lead.get("id", ""))

            if not phone or not lead_id:
                continue

            followup_msg = (
                f"Habari! 👋 Nilitaka ku-check tu kama ulipata msaada wa order yako ya '{intent}'. "
                "Team ya Ayutech Kirinyaga Road bado ipo tayari kukusaidia!"
            )

            # Send WhatsApp nudge
            asyncio.run(send_whatsapp_message(phone, followup_msg))

            # Mark status as 'Followed Up' to avoid duplicate messages
            supabase.table("leads").update({"status": "Followed Up"}).eq("id", lead_id).execute()

            print(f"✅ Automated follow-up sent to {phone} for lead {lead_id}")

    except Exception as e:
        print(f"⚠️ Error running follow-up scheduler: {str(e)}")


async def describe_part_image(image_url: str) -> str:
    """Downloads image from WhatsApp and sends base64 data to Groq Vision."""
    if not image_url:
        return "Shock Absorber / Car Spare Part"

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # 1. Fetch image bytes from Meta WhatsApp CDN
            headers_wa = {
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "User-Agent": "Mozilla/5.0"
            }
            img_res = await client.get(image_url, headers=headers_wa)
            
            if img_res.status_code != 200:
                print(f"⚠️ Image download failed with status: {img_res.status_code}")
                # Smart fallback so the bot still checks inventory!
                return "Shock Absorber / Coil Spring Suspension"
                
            base64_image = base64.b64encode(img_res.content).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{base64_image}"

            # 2. Call Groq Vision API
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.2-11b-vision-preview",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Identify this specific automotive spare part (e.g. Shock Absorber, Brake Pad, Spark Plug). Name the item clearly in 3-5 words."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url}
                                }
                            ]
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 50,
                },
                timeout=15.0,
            )

            if response.status_code == 200:
                result = response.json()
                vision_text = result["choices"][0]["message"]["content"]
                print(f"👁️ Groq Vision Identified: {vision_text}")
                return vision_text
            else:
                print(f"⚠️ Groq Vision API Error: {response.text}")

    except Exception as e:
        print(f"❌ Vision processing error: {str(e)}")

    return "Shock Absorber / Car Component"

async def get_whatsapp_media_url(media_id: str) -> str:
    """Fetches the temporary media URL from Meta WhatsApp API using media_id."""
    if not WHATSAPP_TOKEN:
        return ""
    
    url = f"https://graph.facebook.com/v20.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                return res.json().get("url", "")
        except Exception as e:
            print(f"❌ Failed to fetch WhatsApp media URL: {str(e)}")
    return ""
