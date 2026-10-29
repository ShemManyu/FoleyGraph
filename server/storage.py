import logging
import sqlite3
import threading
import zlib
from pathlib import Path

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential

from server.models import Project, now

logger = logging.getLogger("foleygraph")


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def prepare_commit(before: Project, after: Project, remember: bool) -> Project:
    after = after.model_copy(deep=True)
    after.revision = before.revision + 1
    after.updated_at = now()
    if remember:
        after.undo_revisions = [*before.undo_revisions, before.revision][-20:]
    return Project.model_validate(after.model_dump())


class LocalStore:
    kind = "sqlite"

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS projects "
                "(owner TEXT, id TEXT, revision INTEGER, payload TEXT, PRIMARY KEY(owner,id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS history "
                "(owner TEXT, id TEXT, revision INTEGER, payload TEXT, PRIMARY KEY(owner,id,revision))"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def check(self):
        with self.connect() as db:
            db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()

    def list(self, owner: str) -> list[Project]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM projects WHERE owner=? ORDER BY rowid DESC LIMIT 100", (owner,)
            ).fetchall()
        return sorted(
            (Project.model_validate_json(row[0]) for row in rows),
            key=lambda project: project.updated_at,
            reverse=True,
        )

    def get(self, owner: str, project_id: str) -> Project:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM projects WHERE owner=? AND id=?", (owner, project_id)
            ).fetchone()
        if row is None:
            raise NotFound("Project not found in this browser workspace.")
        return Project.model_validate_json(row[0])

    def create(self, owner: str, project: Project) -> Project:
        with self.connect() as db:
            db.execute(
                "INSERT INTO projects VALUES (?,?,?,?)",
                (owner, project.id, project.revision, project.model_dump_json()),
            )
        return project

    def commit(self, owner: str, before: Project, after: Project, remember: bool = True) -> Project:
        after = prepare_commit(before, after, remember)
        with self.lock, self.connect() as db:
            cursor = db.execute(
                "UPDATE projects SET payload=?,revision=? WHERE owner=? AND id=? AND revision=?",
                (after.model_dump_json(), after.revision, owner, before.id, before.revision),
            )
            if cursor.rowcount != 1:
                raise Conflict("The project changed. Reload it before applying this edit.")
            if remember:
                db.execute(
                    "INSERT OR REPLACE INTO history VALUES (?,?,?,?)",
                    (owner, before.id, before.revision, before.model_dump_json()),
                )
            if after.undo_revisions:
                placeholders = ",".join("?" for _ in after.undo_revisions)
                db.execute(
                    f"DELETE FROM history WHERE owner=? AND id=? AND revision NOT IN ({placeholders})",
                    (owner, before.id, *after.undo_revisions),
                )
            else:
                db.execute("DELETE FROM history WHERE owner=? AND id=?", (owner, before.id))
        return after

    def historical(self, owner: str, project_id: str, revision: int) -> Project:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM history WHERE owner=? AND id=? AND revision=?",
                (owner, project_id, revision),
            ).fetchone()
        if row is None:
            raise NotFound("This undo version is no longer available.")
        return Project.model_validate_json(row[0])

    def delete(self, owner: str, project_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM projects WHERE owner=? AND id=?", (owner, project_id))
            db.execute("DELETE FROM history WHERE owner=? AND id=?", (owner, project_id))


class AzureStore:
    kind = "azure_table"

    def __init__(self, account: str, table: str):
        self.service = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
        )
        self.table = self.service.get_table_client(table)

    def check(self):
        next(iter(self.table.query_entities("PartitionKey eq 'health'", results_per_page=1)), None)

    @staticmethod
    def entity(owner: str, project: Project, row_key: str | None = None):
        payload = zlib.compress(project.model_dump_json().encode())
        if len(payload) > 60_000:
            raise ValueError("This project exceeds the Table Storage document limit.")
        return {
            "PartitionKey": owner,
            "RowKey": row_key or project.id,
            "kind": "history" if row_key else "project",
            "revision": project.revision,
            "payload": payload,
        }

    @staticmethod
    def decode(entity):
        return Project.model_validate_json(zlib.decompress(entity["payload"]))

    def list(self, owner: str):
        rows = self.table.query_entities(
            "PartitionKey eq @owner and kind eq 'project'", parameters={"owner": owner}
        )
        return sorted(
            (self.decode(row) for row in rows), key=lambda project: project.updated_at, reverse=True
        )[:100]

    def get(self, owner: str, project_id: str):
        try:
            return self.decode(self.table.get_entity(owner, project_id))
        except ResourceNotFoundError as exc:
            raise NotFound("Project not found in this browser workspace.") from exc

    def create(self, owner: str, project: Project):
        self.table.create_entity(self.entity(owner, project))
        return project

    def commit(self, owner: str, before: Project, after: Project, remember: bool = True):
        after = prepare_commit(before, after, remember)
        try:
            current = self.table.get_entity(owner, before.id)
            if current["revision"] != before.revision:
                raise Conflict("The project changed. Reload it before applying this edit.")
            operations = [
                (
                    "update",
                    self.entity(owner, after),
                    {
                        "mode": UpdateMode.REPLACE,
                        "etag": current.metadata["etag"],
                        "match_condition": MatchConditions.IfNotModified,
                    },
                )
            ]
            if remember:
                operations.append(
                    (
                        "upsert",
                        self.entity(owner, before, f"{before.id}:v{before.revision:010d}"),
                        {"mode": UpdateMode.REPLACE},
                    )
                )
            self.table.submit_transaction(operations)
        except HttpResponseError as exc:
            if exc.status_code in (404, 409, 412):
                raise Conflict("The project changed. Reload it before applying this edit.") from exc
            raise
        try:
            retained = {f"{before.id}:v{revision:010d}" for revision in after.undo_revisions}
            rows = self.table.query_entities(
                "PartitionKey eq @owner and RowKey ge @start and RowKey lt @end",
                parameters={
                    "owner": owner,
                    "start": f"{before.id}:v",
                    "end": f"{before.id}:w",
                },
                select=["RowKey"],
            )
            for row in rows:
                if row["RowKey"] not in retained:
                    self.table.delete_entity(owner, row["RowKey"])
        except HttpResponseError:
            logger.warning("Undo history cleanup deferred; the project edit was committed.")
        return after

    def historical(self, owner: str, project_id: str, revision: int):
        return self.get(owner, f"{project_id}:v{revision:010d}")

    def delete(self, owner: str, project_id: str):
        self.table.delete_entity(owner, project_id)
        rows = self.table.query_entities(
            "PartitionKey eq @owner and RowKey ge @start and RowKey lt @end",
            parameters={"owner": owner, "start": f"{project_id}:v", "end": f"{project_id}:w"},
            select=["RowKey"],
        )
        for row in rows:
            self.table.delete_entity(owner, row["RowKey"])
