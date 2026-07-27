import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

AYUTECH_STORE_ID = "ayutech"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)