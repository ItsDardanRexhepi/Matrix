"""Email notification channel via SMTP."""

from __future__ import annotations

import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from runtime.notifications.base import Channel

logger = logging.getLogger(__name__)


class EmailChannel(Channel):
    name = "email"

    @property
    def available(self) -> bool:
        cfg = self._channel_config
        return all(cfg.get(k) for k in ("smtp_host", "smtp_user", "smtp_pass", "to"))

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing SMTP credentials or 'to' address")
        cfg = self._channel_config

        def _send_sync() -> dict:
            import smtplib
            subject_prefix = {"error": "[ALERT] ", "warn": "[WARN] ", "info": "[INFO] ", "success": "[OK] "}.get(level, "")
            subject = cfg.get("subject", f"{subject_prefix}0pnMatrx Notification")
            msg = MIMEMultipart()
            msg["From"] = cfg.get("from", cfg["smtp_user"])
            msg["To"] = cfg["to"] if isinstance(cfg["to"], str) else ", ".join(cfg["to"])
            msg["Subject"] = subject
            msg.attach(MIMEText(message, "plain"))
            try:
                host = cfg["smtp_host"]
                port = int(cfg.get("smtp_port", 587))
                use_ssl = bool(cfg.get("use_ssl", False))
                server = smtplib.SMTP_SSL(host, port) if use_ssl else smtplib.SMTP(host, port)
                try:
                    if not use_ssl:
                        server.starttls()
                    server.login(cfg["smtp_user"], cfg["smtp_pass"])
                    server.send_message(msg)
                finally:
                    server.quit()
                return {"status": "ok", "channel": "email"}
            except Exception as exc:
                return {"status": "error", "channel": "email", "error": str(exc)}

        return await asyncio.get_event_loop().run_in_executor(None, _send_sync)
