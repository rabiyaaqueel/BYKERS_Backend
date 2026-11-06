"""SMS Gateway and Real-Time OTP Delivery Service.

Supports:
1. ConsoleSMSProvider: Dev & CI test logger (safe fallback, no external network calls required).
2. Fast2SMSProvider: Real-time SMS delivery to any Indian mobile number via Fast2SMS Quick OTP API.
3. TwilioSMSProvider: Real-time SMS delivery via Twilio REST API.
"""

import abc
import logging
import re
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("bykers.sms")


class SMSProvider(abc.ABC):
    """Abstract interface for sending SMS messages and OTP codes."""

    @abc.abstractmethod
    async def send_otp(self, phone: str, otp: str) -> bool:
        """Sends a 6-digit OTP to the recipient phone number.

        Args:
            phone: Normalized E.164 phone number (e.g. "+919876543210").
            otp: The 6-digit OTP code string (e.g. "492817").

        Returns:
            bool: True if dispatched successfully, False otherwise.
        """
        pass


class ConsoleSMSProvider(SMSProvider):
    """Fallback / Dev SMS provider that logs OTP to the console instead of sending real SMS."""

    async def send_otp(self, phone: str, otp: str) -> bool:
        logger.info(
            "[SMS:CONSOLE] Real-time OTP simulation for recipient %s: Code is [%s]",
            phone,
            otp,
        )
        return True


class Fast2SMSProvider(SMSProvider):
    """Fast2SMS API Provider for real-time SMS delivery in India (Quick OTP route).

    Fast2SMS Quick OTP delivers within 3-5 seconds across Indian telecom networks.
    Requires FAST2SMS_API_KEY in configuration.
    """

    API_URL = "https://www.fast2sms.com/dev/bulkV2"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def send_otp(self, phone: str, otp: str) -> bool:
        # Extract 10-digit Indian mobile number
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("91") and len(digits) == 12:
            phone_10 = digits[2:]
        elif len(digits) == 10:
            phone_10 = digits
        else:
            phone_10 = digits[-10:]

        headers = {
            "authorization": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "variables_values": otp,
            "route": "otp",
            "numbers": phone_10,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.API_URL, headers=headers, json=payload)
                data = response.json()
                if response.status_code == 200 and data.get("return") is True:
                    logger.info("[SMS:FAST2SMS] OTP sent successfully to %s", phone)
                    return True
                logger.error(
                    "[SMS:FAST2SMS] Gateway error: status=%s response=%s",
                    response.status_code,
                    data,
                )
                if settings.SMS_FALLBACK_TO_CONSOLE:
                    logger.warning("[SMS:FAST2SMS] Falling back to console log: OTP [%s]", otp)
                    return True
                return False
        except Exception as exc:
            logger.exception("[SMS:FAST2SMS] Exception dispatching OTP to %s: %s", phone, exc)
            if settings.SMS_FALLBACK_TO_CONSOLE:
                logger.warning("[SMS:FAST2SMS] Exception fallback to console log: OTP [%s]", otp)
                return True
            return False


class TwilioSMSProvider(SMSProvider):
    """Twilio SMS Gateway provider for global delivery."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.api_url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        )

    async def send_otp(self, phone: str, otp: str) -> bool:
        message_body = (
            f"Your BYKERS verification code is {otp}. Valid for "
            f"{settings.OTP_EXPIRES_MINUTES} minutes."
        )
        data = {
            "To": phone,
            "From": self.from_number,
            "Body": message_body,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.api_url,
                    data=data,
                    auth=(self.account_sid, self.auth_token),
                )
                if response.status_code in (200, 201):
                    logger.info("[SMS:TWILIO] OTP sent successfully to %s", phone)
                    return True
                logger.error(
                    "[SMS:TWILIO] Gateway error: status=%s response=%s",
                    response.status_code,
                    response.text,
                )
                if settings.SMS_FALLBACK_TO_CONSOLE:
                    logger.warning("[SMS:TWILIO] Falling back to console log: OTP [%s]", otp)
                    return True
                return False
        except Exception as exc:
            logger.exception("[SMS:TWILIO] Exception dispatching OTP to %s: %s", phone, exc)
            if settings.SMS_FALLBACK_TO_CONSOLE:
                logger.warning("[SMS:TWILIO] Exception fallback to console log: OTP [%s]", otp)
                return True
            return False


def get_sms_provider(override_provider: Optional[str] = None) -> SMSProvider:
    """Factory returning the active SMS Provider based on configuration."""
    provider_name = (override_provider or settings.SMS_PROVIDER).lower().strip()

    if provider_name == "fast2sms":
        if settings.FAST2SMS_API_KEY:
            return Fast2SMSProvider(api_key=settings.FAST2SMS_API_KEY)
        logger.warning(
            "SMS_PROVIDER is 'fast2sms' but FAST2SMS_API_KEY not configured. Using Console."
        )
        return ConsoleSMSProvider()

    if provider_name == "twilio":
        if (
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and settings.TWILIO_FROM_NUMBER
        ):
            return TwilioSMSProvider(
                account_sid=settings.TWILIO_ACCOUNT_SID,
                auth_token=settings.TWILIO_AUTH_TOKEN,
                from_number=settings.TWILIO_FROM_NUMBER,
            )
        logger.warning("SMS_PROVIDER is 'twilio' but credentials not configured. Using Console.")
        return ConsoleSMSProvider()

    return ConsoleSMSProvider()
