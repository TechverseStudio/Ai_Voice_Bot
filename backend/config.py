""" Hey use kelay pratek veles api key manually 
nako load karayla ekdach config file set kela ki automatic api call hoyla 
"""
import os
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///data/voice_agent.db",
)
TELEPHONY_PROVIDER = os.getenv("TELEPHONY_PROVIDER", "mock")
TELEPHONY_MOCK_MODE = os.getenv("TELEPHONY_MOCK_MODE", "true").lower() == "true"
EXOTEL_BASE_URL = os.getenv("EXOTEL_BASE_URL", "")
EXOTEL_ACCOUNT_SID = os.getenv("EXOTEL_ACCOUNT_SID", "")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN", "")
EXOTEL_CALLER_ID = os.getenv("EXOTEL_CALLER_ID", "")
AGENTSTREAM_PUBLIC_URL = os.getenv("AGENTSTREAM_PUBLIC_URL", "")

if not SARVAM_API_KEY:
    raise ValueError("SARVAM_API_KEY is not set in the environment variables.")