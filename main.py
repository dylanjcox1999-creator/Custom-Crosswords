"""
Custom Crosswords Daily — backend API

Endpoints:
  POST /generate_puzzle   { "topic": str, "num_words": int? }
  GET  /on_this_day       ?date=YYYY-MM-DD (optional, defaults to today)

Run locally:
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=sk-ant-...
  uvicorn main:app --reload
"""
import sys
import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from compact_lib import compact_search
from claude_wordbank import generate_word_bank
from historical_events import get_events_for_date
from hints import get_hint, VALID_TIERS
