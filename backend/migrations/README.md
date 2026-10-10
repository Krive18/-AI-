# Database principals and permissions

Use four separate MySQL principals. Never share their credentials or grant one
principal the responsibilities of another.

- **Migration principal:** runs Alembic schema migrations only. It receives the
  minimum schema DDL privileges for the application database and does not receive
  `CREATE ROLE`, `DROP ROLE`, `ROLE_ADMIN`, or table `GRANT OPTION` merely to run
  Alembic.
- **Grant/security-administration principal:** runs
  `sql/runtime_audit_privileges.sql.template` after Alembic. For MySQL 8, the
  template needs global `CREATE ROLE`, global `DROP ROLE`, `ROLE_ADMIN`, and
  `SELECT, INSERT ... WITH GRANT OPTION` on the target `audit_log` table plus
  `SELECT, INSERT, UPDATE ... WITH GRANT OPTION` on the target `user_account`
  table. Because it
  also uses `SET DEFAULT ROLE ... TO` another account, it needs global `CREATE USER`
  or `UPDATE` on the `mysql.default_roles` system table. It does not perform the
  post-grant authorization audit.
- **Read-only auditor:** is independent from the grant/security-administration
  principal and performs the post-grant authorization audit. It receives only
  `SELECT ON mysql.*` and the minimum connection privilege, and receives no DCL,
  role-administration, or application-table write privilege.
- **Runtime principal:** receives only its dedicated runtime role. It must have no
  direct database privileges and no other granted roles. The role receives only
  `SELECT, INSERT, UPDATE` on `user_account`; `SELECT, INSERT` on append-only
  `audit_log`, `task_event`, `ai_usage_record`, and timeline/media tables; and
  `SELECT, INSERT, UPDATE` on mutable `translation_project` and
  `translation_task`; and `SELECT, INSERT, UPDATE` on mutable provider
  configuration. Immutable provider versions and price records receive only
  `SELECT, INSERT`. Never grant DELETE, schema DDL, or UPDATE to append-only
  tables.
  Never grant it `DELETE`, schema-level DDL, `GRANT OPTION`, database-wide
  `UPDATE`, or `UPDATE`/`DELETE` on the append-only audit table.

The independent read-only auditor performs the post-grant authorization audit before
the runtime deployment proceeds. MySQL 8 requires `SELECT` on the `mysql` system
schema to execute `SHOW GRANTS FOR` another account or role. The auditor must run the
following checks after the template has completed, and verify that neither result
contains runtime `UPDATE`, `DELETE`, DDL, or grant-administration capabilities:

```sql
SHOW GRANTS FOR __RUNTIME_PRINCIPAL__;
SHOW GRANTS FOR `__RUNTIME_ROLE__`;
```

`__RUNTIME_PRINCIPAL__` remains a complete quoted MySQL account expression; the
runtime principal never receives the auditor's `mysql` schema read access.

The grant template deliberately drops and recreates its dedicated runtime role. Run
it only with the grant/security-administration principal, never with the migration
or runtime principal. Never store database credentials in this repository or this
document.
