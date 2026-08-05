import requests

MICROSOFT_LOGIN_URL = "https://login.microsoftonline.com"


def refresh_microsoft_token(credentials: dict) -> dict:
    """Get a new token for the configured refresh token.

    Request the token from the refresh proxy if `refresh_proxy_url` is configured.
    Request the token directly from Microsoft identity platform in all other cases,
    with the configured app registration.

    Return the full token, because a caller can need more than the access token.
    """
    refresh_proxy_url = credentials.get("refresh_proxy_url")

    if refresh_proxy_url:
        response = requests.post(
            refresh_proxy_url,
            headers={"Authorization": credentials["refresh_proxy_url_auth"]},
            json={
                "grant_type": "refresh_token",
                "refresh_token": credentials["refresh_token"],
            },
        )

        response.raise_for_status()
        return response.json()

    tenant_id = credentials.get("tenant_id") or "common"
    response = requests.post(
        f"{MICROSOFT_LOGIN_URL}/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": credentials["refresh_token"],
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
        },
    )

    response.raise_for_status()
    return response.json()
