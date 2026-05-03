"""
generate_session.py
Run this LOCALLY (not on Railway) to generate your Telegram session string.
Then set TELEGRAM_SESSION_STRING in Railway environment variables.

Usage: python generate_session.py
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", input("Enter API_ID: ")))
    api_hash = os.getenv("TELEGRAM_API_HASH", input("Enter API_HASH: "))
    phone = os.getenv("TELEGRAM_PHONE", input("Enter phone (+628xxx): "))
    
    print("\nGenerating session string...")
    print("You will receive a code on Telegram.\n")
    
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start(phone=phone)
    
    session_string = client.session.save()
    
    print("\n" + "=" * 60)
    print("✅ SESSION STRING GENERATED!")
    print("=" * 60)
    print(f"\n{session_string}\n")
    print("=" * 60)
    print("\n📋 Next steps:")
    print("1. Copy the session string above")
    print("2. In Railway → Variables → Add:")
    print("   TELEGRAM_SESSION_STRING = <paste here>")
    print("3. Deploy your app\n")
    
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
