import httpx
from config import supabase, AYUTECH_STORE_ID, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TOKEN
from datetime import datetime, timedelta, timezone
from datetime import datetime, timedelta, timezone
from config import AYUTECH_STORE_ID, supabase
import asyncio

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