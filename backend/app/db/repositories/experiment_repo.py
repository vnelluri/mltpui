"""Repository for Experiment and ExperimentRun entities."""
from __future__ import annotations

from typing import List, Optional, Tuple

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Experiment, ExperimentRun, Keys


class ExperimentRepository:
    def __init__(self) -> None:
        self.table = get_table()

    # ── Experiments ─────────────────────────────────────────────────────
    def _exp_item(self, exp: Experiment) -> dict:
        return {
            "entityType": "Experiment",
            **Keys.experiment(exp.experimentId),
            **Keys.experiment_gsi(exp.tenantId, exp.createdAt, exp.experimentId),
            **exp.model_dump(),
        }

    def create_experiment(self, exp: Experiment) -> Experiment:
        self.table.put_item(
            Item=clean_item(self._exp_item(exp)),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return exp

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        resp = self.table.get_item(Key=Keys.experiment(experiment_id))
        item = strip_internal(resp.get("Item"))
        return Experiment(**item) if item else None

    def list_experiments_by_tenant(self, tenant_id: str) -> List[Experiment]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"EXP_TENANT#{tenant_id}"),
            ScanIndexForward=False,
        )
        return [Experiment(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_all_experiments(self) -> List[Experiment]:
        resp = self.table.scan(
            FilterExpression="entityType = :t",
            ExpressionAttributeValues={":t": "Experiment"},
        )
        return [Experiment(**strip_internal(i)) for i in resp.get("Items", [])]

    # ── Runs ────────────────────────────────────────────────────────────
    def _run_item(self, run: ExperimentRun) -> dict:
        return {
            "entityType": "ExperimentRun",
            **Keys.run(run.experimentId, run.runId),
            **Keys.run_gsi(run.tenantId, run.runId),
            **run.model_dump(),
        }

    def create_run(self, run: ExperimentRun) -> ExperimentRun:
        self.table.put_item(
            Item=clean_item(self._run_item(run)),
            ConditionExpression="attribute_not_exists(SK)",
        )
        return run

    def get_run(self, experiment_id: str, run_id: str) -> Optional[ExperimentRun]:
        resp = self.table.get_item(Key=Keys.run(experiment_id, run_id))
        item = strip_internal(resp.get("Item"))
        return ExperimentRun(**item) if item else None

    def list_runs(self, experiment_id: str) -> List[ExperimentRun]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"EXPERIMENT#{experiment_id}")
            & Key("SK").begins_with("RUN#"),
        )
        return [ExperimentRun(**strip_internal(i)) for i in resp.get("Items", [])]

    def get_run_by_id(self, tenant_id: str, run_id: str) -> Optional[ExperimentRun]:
        """Look up a run by id alone (via the tenant+runId GSI)."""
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"RUN_TENANT#{tenant_id}")
            & Key("GSI1SK").eq(f"RUN#{run_id}"),
        )
        items = resp.get("Items", [])
        if not items:
            return None
        return ExperimentRun(**strip_internal(items[0]))

    def next_run_number(self, tenant_id: str) -> int:
        """Next sequential number for human-friendly run ids (run-0001, …).

        Run ids must be unique per TENANT (get_run_by_id resolves via the
        RUN_TENANT GSI), so the counter is tenant-wide. Backed by an atomic
        counter item (same pattern as JobRepository.next_job_number) —
        DynamoDB's ADD is race-free and has no ordering/padding ceiling.
        """
        resp = self.table.update_item(
            Key={"PK": f"COUNTER#run#{tenant_id}", "SK": f"COUNTER#run#{tenant_id}"},
            UpdateExpression="ADD #n :one",
            ExpressionAttributeNames={"#n": "n"},
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["n"])

    def count_runs(self, experiment_id: str) -> int:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"EXPERIMENT#{experiment_id}")
            & Key("SK").begins_with("RUN#"),
            Select="COUNT",
        )
        return int(resp.get("Count", 0))

    def update_run(self, run: ExperimentRun) -> ExperimentRun:
        self.table.put_item(
            Item=clean_item(self._run_item(run)),
            ConditionExpression="attribute_exists(SK)",
        )
        return run
