""" Hey use kelay pratek veles api key manually 
nako load karayla ekdach config file set kela ki automatic api call hoyla 
"""
import os
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

if not SARVAM_API_KEY:
    raise ValueError("SARVAM_API_KEY is not set in the environment variables.")