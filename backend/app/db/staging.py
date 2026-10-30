"""Staging database confinement: one rule shared by the backend's startup check and the secret-creation script.

A separate secret does not prove separate credentials, so the user behind a staging URI is judged by the privileges
MongoDB reports for it (``connectionStatus`` with ``showPrivileges``).
"""

# Exactly the actions of the built-in readWrite role on MongoDB 7.0 and 8.0.34 (the Atlas cluster's version),
# extracted from both servers. Anything else is refused: collMod can replace the MU-9 validator (only the migration
# user may, through apply-validator), bypassDocumentValidation skips it, killAnyCursor reaches other users, and the
# dbAdmin/dbOwner/userAdmin actions administer the database. A newer server adding an action fails closed, naming it.
ALLOWED_ACTIONS = frozenset({
    "changeStream", "cleanupStructuredEncryptionData", "collStats", "compactStructuredEncryptionData",
    "convertToCapped", "createCollection", "createIndex", "createSearchIndexes", "dbHash", "dbStats", "dropCollection",
    "dropIndex", "dropSearchIndex", "find", "insert", "killCursors", "listCollections", "listIndexes",
    "listSearchIndexes", "planCacheRead", "remove", "renameCollectionSameDB", "update", "updateSearchIndex",
})  # fmt: skip

# What the backend needs at startup and in use (collections, indexes, reads and writes, the MU-9 validator check),
# on the whole database: grants limited to some collections would fail on the others.
REQUIRED_ACTIONS = frozenset({
    "createCollection", "createIndex", "find", "insert", "listCollections", "listIndexes", "remove", "update",
})


def confinement_problem(auth_info: dict, db_name: str) -> str | None:
    """Why the authenticated user is not confined to readWrite on ``db_name``, or None if it is."""
    if not auth_info.get("authenticatedUsers"):
        return f"Staging needs an authenticated MongoDB user limited to {db_name}."
    privileges = auth_info.get("authenticatedUserPrivileges", [])
    # A privilege without a "db" is a cluster or anyResource grant; "" means every database.
    reach = {str(p.get("resource", {}).get("db", "<cluster or any resource>")) for p in privileges}
    if reach != {db_name}:
        return f"Staging MongoDB user must be limited to {db_name}; it reaches {sorted(reach)}."
    actions = {a for p in privileges for a in p.get("actions", [])}
    if extra := actions - ALLOWED_ACTIONS:
        return f"Staging MongoDB user on {db_name} holds actions beyond readWrite: {sorted(extra)}."
    database_wide = {
        a for p in privileges if p.get("resource", {}).get("collection") == "" for a in p.get("actions", [])
    }
    if missing := REQUIRED_ACTIONS - database_wide:
        return f"Staging MongoDB user on {db_name} lacks actions the backend needs: {sorted(missing)}."
    return None
