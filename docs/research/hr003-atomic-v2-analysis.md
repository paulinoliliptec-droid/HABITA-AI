# atomic-v2 protocol and floor raise — analysis only (NOT done; owner decision 2026-11-02: don't raise now)

## Why it would be needed
The hotfix (`hr003/td003-hotfix`, `f6a63a2`) makes the verifier stricter but keeps the protocol name `atomic-v1`.
Reports written by the published verifier (`main` `f7d05b5`) and by the hotfix are indistinguishable by protocol.
Consequences:
1. **Rollback:** if the hotfix is deployed and then rolled back to `f7d05b5`, that revision can again commit VERIFIED
   with the false-VERIFIED paths the hotfix closes; the floor (`atomic-v1`) and the server validator accept it.
2. **History:** VERIFIED reports committed before the hotfix may contain a sentence the hotfix would refuse; nothing
   marks them.

## What raising to atomic-v2 does (existing mechanism, `app/maintenance.py migrate-floor`)
- Code change (small): `protocol.PROTOCOLS = ("statement-v1", "atomic-v1", "atomic-v2")`, `verifier.PROTOCOL =
  "atomic-v2"`; `DEFAULT_FLOOR` follows `CURRENT`.
- Data change (owner's word, per database): `migrate-floor atomic-v2 <operator> <reason>` — dry run first (prints the
  plan), then `--apply --backup-manifest <file>` with a verified backup. In one transaction: the validator admits
  only `atomic-v2`; the stored floor is `atomic-v2` with `atomic-v1` and `statement-v1` known-unsafe; every VERIFIED
  report of `atomic-v1` and its matter get `superseded_protocol: "atomic-v1"`; an audit record is written. Nothing is
  deleted.

## Effects on atomic-v1 reports
- Each flagged matter reads as `superseded_assessment` (`schemas/permit.py`): the UI shows the re-verification note
  (`PermitResult.tsx`), the shared report model never presents it as VERIFIED (`report/builder.py`), so the PDF,
  map label, graph and voice show "pending confirmation" instead of "verified".
- Known affected: staging `pm_6c61911b…`, original `pm_9654159b…`, the HR-009 real-run VERIFIED matters, and any
  demo matter the owner verified since 30/10. Exact counts need a read of each database (not done: real data).
- The owner's demo would need those matters re-run (paid Muse calls) to show VERIFIED again.

## Migration risks
| Risk | Mitigation |
|---|---|
| A revision older than the hotfix still serving traffic writes `atomic-v1` VERIFIED after the raise → refused by the validator (availability loss, not a safety loss) | route traffic to the hotfix revision and untag older revisions first (the documented MU-9 order) |
| Raise applied before the hotfix is live → every new VERIFIED refused | deploy first, raise second |
| Demo matters lose VERIFIED | re-run them after the raise (budgeted under TD-033) |
| The application user lacks `collMod` | the existing migration users (`habitaStagingMigrate`, preview equivalent), temporary credentials |
| A wrong database | dry run prints the database name and counts; `--apply` needs the backup manifest of that database |

## Compatibility
Hotfix code reads `atomic-v1` and `atomic-v2` reports alike; the published code reads `atomic-v2` reports (schema
unchanged) but cannot write them once the floor is raised. The frontend needs no change (`superseded_assessment`
already exists).

## Safe rollback plan
- **Before the raise** (hotfix live, floor `atomic-v1`): rollback = traffic back to the previous revision, as usual.
  Safety drops back to the published level while rolled back (the known false-VERIFIED paths return).
- **After the raise:** rollback to `f7d05b5` keeps the service up but it can't commit VERIFIED (validator); safety
  doesn't drop. The floor is never lowered (no command exists); a fix goes forward.
- **Recommendation:** publish the hotfix first with the floor unchanged; raise to `atomic-v2` as a separate, later
  decision once the hotfix has run cleanly and the demo matters can be re-verified.
