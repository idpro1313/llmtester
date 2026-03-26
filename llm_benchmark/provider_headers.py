"""Дополнительные заголовки для OpenAI-compatible API с шлюзами вроде Cloud.ru (WWW-Authenticate: X-API-KEY)."""


def x_api_key_headers(api_key: str) -> dict[str, str]:
    k = (api_key or "").strip()
    if not k:
        return {}
    return {"X-API-KEY": k}
