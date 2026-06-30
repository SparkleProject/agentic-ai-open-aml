from aml.core.config import Settings
from aml.services.auth.jwt_provider import JWTAuthProvider
from aml.services.auth.provider import AuthProvider


def get_auth_provider(settings: Settings) -> AuthProvider:
    name = settings.auth_provider.lower()

    if name == "jwt":
        return JWTAuthProvider(
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
            access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
            refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
        )

    if name in ("cognito", "keycloak"):
        raise NotImplementedError(f"Auth provider '{name}' is not yet implemented. Use 'jwt'.")

    msg = f"Unknown auth provider: {name}"
    raise ValueError(msg)
