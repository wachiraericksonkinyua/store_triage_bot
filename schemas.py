from pydantic import BaseModel

class WebhookPayload(BaseModel):
    user_phone: str
    message: str

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this tool strictly when the customer explicitly asks to BUY, PLACE AN ORDER, DISPATCH, or requests a CALLBACK. Do NOT call this tool for general pricing or stock inquiries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "description": "e.g. Spare Part Order, Callback Request"},
                    "notes": {"type": "string", "description": "Car model and items ordered"},
                    "status": {"type": "string", "description": "AVAILABLE or NEEDS_HUMAN_ATTENTION"}
                },
                "required": ["intent", "notes"]
            }
        }
    }
]