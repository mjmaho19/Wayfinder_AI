from twilio.rest import Client
import os

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_PHONE = os.getenv("TWILIO_PHONE")

client = Client(ACCOUNT_SID, AUTH_TOKEN)


def send_sms(to_number, message):

    client.messages.create(
        body=message,
        from_=FROM_PHONE,
        to=to_number
    )