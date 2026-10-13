"""`get_store` (SPEC-03 §4.2): the dev store needs nothing private, and a private store needs private settings that
name a database and an object root apart from the main ones (C1, INV-01). Nothing here connects anywhere: the
settings are synthetic and engines connect lazily."""

import pytest

from crawlerai.core.settings import Settings
from crawlerai.db.models import PrivateSplit
from crawlerai.eval.store import (
    DevEvalStore,
    PrivateCredentialsMissing,
    PrivateEvalStore,
    PrivateStoreNotSeparate,
    get_store,
)

MAIN_DB = "postgresql+asyncpg://app:pw@db.example.test:5432/crawlerai"
PRIVATE_DB = "postgresql+asyncpg://custodian:pw@db.example.test:5432/crawlerai_eval_private"


def _settings(**private: str) -> Settings:
    return Settings.model_validate({"database_url": MAIN_DB, "object_store": "fs:///srv/objects", **private})


def test_the_dev_store_needs_no_private_settings() -> None:
    store = get_store("dev", _settings())

    assert isinstance(store, DevEvalStore)
    assert store.split == "dev"


@pytest.mark.parametrize("split", ["hidden", "fresh"])
@pytest.mark.parametrize(
    "private",
    [
        {},
        {"eval_private_database_url": PRIVATE_DB},
        {"eval_private_object_store": "fs:///srv/private"},
    ],
)
def test_hidden_and_fresh_need_both_private_settings(split: PrivateSplit, private: dict[str, str]) -> None:
    with pytest.raises(PrivateCredentialsMissing, match="expected on any other machine"):
        get_store(split, _settings(**private))


@pytest.mark.parametrize("split", ["hidden", "fresh"])
def test_a_private_store_serves_its_split(split: PrivateSplit) -> None:
    store = get_store(
        split, _settings(eval_private_database_url=PRIVATE_DB, eval_private_object_store="fs:///srv/eval")
    )

    assert isinstance(store, PrivateEvalStore)
    assert store.split == split


@pytest.mark.parametrize(
    ("database_url", "object_store", "reason"),
    [
        (MAIN_DB.replace("app:pw", "custodian:pw"), "fs:///srv/eval", "is the main database"),
        (PRIVATE_DB, "fs:///srv/objects", "overlaps the main one"),
        (PRIVATE_DB, "fs:///srv/objects/eval/hidden", "overlaps the main one"),
        (PRIVATE_DB, "fs:///srv", "overlaps the main one"),
    ],
)
def test_private_settings_must_name_a_separate_database_and_object_root(
    database_url: str, object_store: str, reason: str
) -> None:
    with pytest.raises(PrivateStoreNotSeparate, match=reason):
        get_store("hidden", _settings(eval_private_database_url=database_url, eval_private_object_store=object_store))
