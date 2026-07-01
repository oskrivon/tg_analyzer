"""Proxy parsing utilities."""

from typing import Optional
from urllib.parse import urlparse
import python_socks


def parse_proxy(proxy_str: str) -> Optional[dict]:
    """
    Parse proxy string into Telethon proxy config.

    Formats supported:
        - socks5://user:pass@host:port (URL format with auth)
        - socks5://host:port (URL format without auth)
        - host:port:user:pass (legacy format with auth)
        - host:port (legacy format without auth)

    Returns:
        dict with proxy_type, addr, port, and optionally username/password
        None if format is invalid
    """
    if not proxy_str:
        return None

    proxy_str = proxy_str.strip()

    # Handle URL format (socks5://user:pass@host:port)
    if proxy_str.startswith(("socks5://", "socks4://", "http://")):
        parsed = urlparse(proxy_str)

        proxy_type = python_socks.ProxyType.SOCKS5
        if parsed.scheme == "socks4":
            proxy_type = python_socks.ProxyType.SOCKS4
        elif parsed.scheme == "http":
            proxy_type = python_socks.ProxyType.HTTP

        result = {
            "proxy_type": proxy_type,
            "addr": parsed.hostname,
            "port": parsed.port,
        }

        if parsed.username:
            result["username"] = parsed.username
        if parsed.password:
            result["password"] = parsed.password

        return result

    # Handle legacy format (host:port:user:pass or host:port)
    parts = proxy_str.split(":")

    if len(parts) == 4:
        host, port, user, password = parts
        return {
            "proxy_type": python_socks.ProxyType.SOCKS5,
            "addr": host,
            "port": int(port),
            "username": user,
            "password": password,
        }
    elif len(parts) == 2:
        host, port = parts
        return {
            "proxy_type": python_socks.ProxyType.SOCKS5,
            "addr": host,
            "port": int(port),
        }
    else:
        return None
