import pytest
from pydantic import ValidationError

from app.core.config import STAGING_DB_NAME, Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("APP_ENV", "MONGODB_URI", "MONGODB_DB_NAME", "ALLOW_EPHEMERAL_STORAGE"):
        monkeypatch.delenv(name, raising=False)


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_staging_with_its_database_and_uri_starts():
    s = settings(app_env="staging", mongodb_db_name=STAGING_DB_NAME, mongodb_uri="mongodb://staging.invalid")
    assert s.mongodb_db_name == "habita_ai_staging"


def test_staging_without_database_name_does_not_fall_back_to_preview():
    with pytest.raises(ValidationError, match="MONGODB_DB_NAME=habita_ai_staging"):
        settings(app_env="staging", mongodb_uri="mongodb://staging.invalid")


def test_staging_refuses_the_preview_database():
    with pytest.raises(ValidationError, match="MONGODB_DB_NAME"):
        settings(app_env="staging", mongodb_db_name="habita_ai", mongodb_uri="mongodb://staging.invalid")


@pytest.mark.parametrize("extra", [{}, {"allow_ephemeral_storage": True}])
def test_staging_refuses_a_process_local_store(extra):
    values = {"mongodb_uri": "mongodb://staging.invalid"} if extra else {}
    with pytest.raises(ValidationError, match="MONGODB_URI"):
        settings(app_env="staging", mongodb_db_name=STAGING_DB_NAME, **values, **extra)


def test_staging_variables_from_the_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("MONGODB_URI", "mongodb://staging.invalid")
    with pytest.raises(ValidationError, match="MONGODB_DB_NAME"):
        settings()
    monkeypatch.setenv("MONGODB_DB_NAME", STAGING_DB_NAME)
    assert settings().mongodb_db_name == STAGING_DB_NAME


def test_errors_do_not_echo_credentials():
    with pytest.raises(ValidationError) as error:
        settings(app_env="staging", mongodb_uri="mongodb://user:s3cret@staging.invalid")
    assert "s3cret" not in str(error.value)


def test_other_environments_keep_their_defaults():
    assert settings(app_env="preview").mongodb_db_name == "habita_ai"


class _Admin:
    def __init__(self, auth: dict) -> None:
        self._auth = auth

    async def command(self, command: dict) -> dict:
        assert command == {"connectionStatus": 1, "showPrivileges": True}
        return {"authInfo": self._auth, "ok": 1}


class _Client:
    def __init__(self, auth: dict) -> None:
        self.admin = _Admin(auth)


def _user(*resources: dict, actions: tuple[str, ...] = ("find", "insert", "update", "collMod")) -> dict:
    return {
        "authenticatedUsers": [{"user": "habita-staging", "db": "admin"}],
        "authenticatedUserPrivileges": [{"resource": r, "actions": list(actions)} for r in resources],
    }


async def test_staging_user_confined_to_its_database_is_accepted():
    from app.main import _require_confined_user

    staging = {"db": STAGING_DB_NAME, "collection": ""}
    await _require_confined_user(_Client(_user(staging, {"db": STAGING_DB_NAME, "collection": "system.js"})), STAGING_DB_NAME)


@pytest.mark.parametrize(
    "auth",
    [
        {"authenticatedUsers": [], "authenticatedUserPrivileges": []},  # no authentication at all
        _user({"db": STAGING_DB_NAME, "collection": ""}, {"db": "habita_ai", "collection": ""}),  # preview too
        _user({"db": "", "collection": ""}),  # every database
        _user({"db": STAGING_DB_NAME, "collection": ""}, {"cluster": True}),
        _user({"anyResource": True}),
        _user(),  # authenticated but no privileges
    ],
)
async def test_staging_user_reaching_beyond_its_database_is_refused(auth):
    from app.main import ConfigurationError, _require_confined_user

    with pytest.raises(ConfigurationError, match="habita_ai_staging"):
        await _require_confined_user(_Client(auth), STAGING_DB_NAME)


@pytest.mark.parametrize("action", ["createUser", "grantRole", "dropDatabase", "bypassDocumentValidation"])
async def test_staging_user_with_administrative_actions_is_refused(action):
    from app.main import ConfigurationError, _require_confined_user

    auth = _user({"db": STAGING_DB_NAME, "collection": ""}, actions=("find", "insert", action))
    with pytest.raises(ConfigurationError, match=action):
        await _require_confined_user(_Client(auth), STAGING_DB_NAME)
