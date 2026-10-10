from dataclasses import dataclass

from app.modules.account.schemas import AccountRecord
from app.modules.auth.sessions import SessionData


@dataclass(frozen=True, slots=True)
class LoginResult:
    account: AccountRecord
    session_token: str
    session: SessionData
