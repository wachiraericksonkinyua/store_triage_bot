from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class WebhookPayload(BaseModel):
    user_phone: str
    message: Optional[str] = ""
    image_url: Optional[str] = None

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "calculate_delivery",
            "description": "Call this tool ONLY when the user explicitly names a specific neighborhood, town, or location in Nairobi (e.g., CBD, Westlands, Kasarani). Do NOT call if no location name is present.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The specific neighborhood or area name mentioned by the user.",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this tool strictly when the customer explicitly asks to BUY, PLACE AN ORDER, DISPATCH, or requests a CALLBACK.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "e.g. Spare Part Order, Callback Request",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Car model and items ordered",
                    },
                    "status": {
                        "type": "string",
                        "description": "AVAILABLE or NEEDS_HUMAN_ATTENTION",
                    },
                },
                "required": ["intent", "notes"],
            },
        },
    },
]