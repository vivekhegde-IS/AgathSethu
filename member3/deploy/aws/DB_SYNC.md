# Copy the local database to AWS and use AWS from localhost

Result: one database (AWS `aghat_sethu`) used by the website, the mobile app and
your local backend. Backups of both sides are taken first, so either can be put back.

Server: `15.134.181.203` (aghatsethu.duckdns.org), key `~/.ssh/aghat-key.pem`.
Windows commands are PowerShell; server commands run after `ssh`.

## 0. Allow SSH from your current IP (AWS console)
EC2 (region **Melbourne, ap-southeast-4**) → Instances → your instance → **Security** tab →
security group → **Edit inbound rules** → SSH / 22 → Source **My IP** → **Save rules**.
Test: `ssh -i $HOME\.ssh\aghat-key.pem ubuntu@15.134.181.203 hostname`

## 1. Put the same code on AWS (schemas must match)
GitHub has migrations up to 008; local is at 009 and this work adds 010.
```powershell
cd "C:\Users\vivek\Downloads\major project\routine try -makkan\aghat_updation"
git status                      # check what you are committing (leave out screenshots / .bkit)
git add member3 .gitignore
git commit -m "feat: live crash answers from the app, owner/authority live updates"
git push origin main
```
On the server:
```bash
ssh -i ~/.ssh/aghat-key.pem ubuntu@15.134.181.203
sudo bash /opt/aghat/AgathSethu/member3/deploy/aws/setup_server.sh   # pulls, migrates to 010, restarts
sudo -u postgres psql -d aghat_sethu -tAc "select version_num from alembic_version"   # must print 010
psql --version
```

## 2. Back up AWS (server, still in ssh)
```bash
sudo mkdir -p /var/backups/aghat
sudo -u postgres pg_dump -Fc aghat_sethu | sudo tee /var/backups/aghat/aws_before_sync_$(date +%F_%H%M).dump > /dev/null
ls -lh /var/backups/aghat
```
Download a copy (Windows):
```powershell
scp -i $HOME\.ssh\aghat-key.pem "ubuntu@15.134.181.203:/var/backups/aghat/aws_before_sync_*.dump" .\db_backups\
```
(Local backup already exists: `db_backups\local_Aghat_Sethu_20261120_163914.dump`.)

## 3. Export local data (Windows)
Data only (COPY rows), so it loads into the server's schema whatever its Postgres version.
```powershell
cd "C:\Users\vivek\Downloads\major project\routine try -makkan\aghat_updation\member3\backend"
.\.venv\Scripts\python -m alembic upgrade head          # local -> 010, same as AWS
$env:PGPASSWORD = "<your local postgres password from backend\.env>"
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h localhost -U postgres -d Aghat_Sethu `
    --data-only --exclude-table-data=alembic_version --no-owner --no-privileges `
    -f ..\..\db_backups\local_data_for_aws.sql
scp -i $HOME\.ssh\aghat-key.pem ..\..\db_backups\local_data_for_aws.sql ubuntu@15.134.181.203:/tmp/
```

## 4. Replace the AWS data with the local data (server)
```bash
sudo systemctl stop aghat-backend
sudo -u postgres psql -d aghat_sethu -c 'DO $$ DECLARE t text; BEGIN FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = $q$public$q$ AND tablename <> $q$alembic_version$q$ LOOP EXECUTE format($q$TRUNCATE TABLE %I CASCADE$q$, t); END LOOP; END $$;'
sudo -u postgres env PGOPTIONS='-c session_replication_role=replica' psql -d aghat_sethu -f /tmp/local_data_for_aws.sql 2>&1 | grep -i error
sudo -u postgres psql -d aghat_sethu -tAc "select 'users', count(*) from users union all select 'vehicles', count(*) from vehicles union all select 'incidents', count(*) from incidents union all select 'fines', count(*) from fines"
sudo systemctl start aghat-backend
curl -s https://aghatsethu.duckdns.org/api/health
rm /tmp/local_data_for_aws.sql
```
Expected counts (local today): users 43, vehicles 37, incidents 169, fines 20.
Errors about `transaction_timeout` or `\restrict` only (pg_dump 18 vs an older server psql) are harmless;
any other error → restore the AWS backup (section 7) and send me the output.

## 5. Copy evidence files (optional)
The database stores file paths; images/clips stay on disk. Copy your local evidence
folder to `/var/lib/aghat-data` on the server if old fines/crashes should show their pictures there.

## 6. Use the AWS database from localhost
Server Postgres stays closed to the internet; localhost reaches it through SSH.

Database password (server):
```bash
sudo grep DATABASE_URL /opt/aghat/AgathSethu/member3/backend/.env
```
Tunnel (Windows, keep this window open while you work):
```powershell
ssh -i $HOME\.ssh\aghat-key.pem -N -L 5433:127.0.0.1:5432 ubuntu@15.134.181.203
```
`member3\backend\.env`:
```ini
# DATABASE_URL=postgresql+psycopg://postgres:<local pw>@localhost:5432/Aghat_Sethu   # local (revert = swap back)
DATABASE_URL=postgresql+psycopg://aghat:<server pw>@localhost:5433/aghat_sethu
```
Restart the local backend. Anything you do on localhost is now live data.
Notes: queries go to Melbourne, so localhost is a bit slower; if your IP changes, redo step 0.
Tests are unaffected (they only run against `*_test` databases).

## 7. Revert
- **Localhost back to its own DB:** swap the two `DATABASE_URL` lines and restart (the local DB was not changed).
- **AWS back to before the copy:**
  ```bash
  sudo systemctl stop aghat-backend
  sudo -u postgres pg_restore --clean --if-exists -d aghat_sethu /var/backups/aghat/aws_before_sync_<time>.dump
  sudo systemctl start aghat-backend
  ```
- **Local DB from its backup:**
  `& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -h localhost -U postgres --clean --if-exists -d Aghat_Sethu .\db_backups\local_Aghat_Sethu_20261120_163914.dump`
