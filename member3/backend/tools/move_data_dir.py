"""Move the backend's files to another folder (e.g. Google Drive for desktop).

    python tools/move_data_dir.py "G:\\My Drive\\AghatSethuData"            # dry run: shows what would happen
    python tools/move_data_dir.py "G:\\My Drive\\AghatSethuData" --apply    # copy, verify, update DB + .env
    python tools/move_data_dir.py --check                                  # only report missing evidence files
    python tools/move_data_dir.py --fix-paths                              # only re-point evidence_files at DATA_DIR

What --apply does, in order:
  1. refuses to run while the backend is listening on port 8001 (stop it first)
  2. COPIES (never moves) runtime/incident_evidence, runtime/recordings,
     runtime/routine_violations, runtime/live_anpr and static/ to the target,
     and checks every copy by SHA-256
  3. updates evidence_files.path in PostgreSQL to the new location (one
     transaction); rows whose image exists nowhere are left as they are
  4. sets DATA_DIR=<target> in backend/.env (the old file is kept as .env.bak)
The originals are never deleted; remove them yourself once the website works.
Fine / partial-plate / unmatched snapshots are stored relative to static/, so
they need no database change.
"""

import hashlib
import re
import shutil
import socket
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.core.config import data_dir  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402

FOLDERS = ["runtime/incident_evidence", "runtime/recordings", "runtime/routine_violations",
           "runtime/live_anpr", "static"]
EVIDENCE_REL = re.compile(r"runtime[\\/]incident_evidence[\\/](.+)$", re.IGNORECASE)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backend_running(port: int = 8001) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def evidence_rows(db):
    return db.execute(text("select id, path from evidence_files")).all()


def in_root(path: str, root: Path) -> Path | None:
    """The same incident/junction/file under `root`, if it exists there."""
    m = EVIDENCE_REL.search(path)
    if not m:
        return None
    candidate = root / "runtime" / "incident_evidence" / Path(*re.split(r"[\\/]", m.group(1)))
    return candidate if candidate.is_file() else None


def resolve_evidence(path: str, roots: list[Path]) -> Path | None:
    """The stored path if it exists, else the same file under one of `roots`."""
    if Path(path).is_file():
        return Path(path)
    for root in roots:
        found = in_root(path, root)
        if found:
            return found
    return None


def repoint(target: Path) -> None:
    """Point every evidence_files row at its copy under `target` (one transaction).
    The copy under target wins even when the old file still exists."""
    db = SessionLocal()
    moved = already = missing = 0
    try:
        for row_id, path in evidence_rows(db):
            found = in_root(path, target)
            if found is None:
                missing += 1
            elif str(found) == path:
                already += 1
            else:
                db.execute(text("update evidence_files set path = :p where id = :i"), {"p": str(found), "i": row_id})
                moved += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"evidence_files: {moved} path(s) updated, {already} already correct, "
          f"{missing} row(s) whose image is not under {target} left unchanged")


def check():
    db = SessionLocal()
    rows = evidence_rows(db)
    ok = fixable = gone = 0
    for _, path in rows:
        if Path(path).is_file():
            ok += 1
        elif resolve_evidence(path, [data_dir()]):
            fixable += 1
        else:
            gone += 1
    db.close()
    print(f"evidence_files rows: {len(rows)} | file at stored path: {ok} | "
          f"missing at stored path but present in {data_dir()}: {fixable} | missing everywhere: {gone}")


def main():
    if "--check" in sys.argv:
        check()
        return
    if "--fix-paths" in sys.argv:
        repoint(data_dir().resolve())
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    apply = "--apply" in sys.argv
    source = data_dir().resolve()
    target = Path(args[0]).expanduser().resolve()
    if target == source:
        sys.exit("The target is already the current DATA_DIR.")
    if apply and backend_running():
        sys.exit("The backend is running on port 8001. Stop it first, then run this again.")

    print(f"from: {source}\nto:   {target}\n")
    files = [(p, target / p.relative_to(source))
             for folder in FOLDERS if (source / folder).exists()
             for p in (source / folder).rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p, _ in files)
    print(f"{len(files)} files, {total / 1e6:.1f} MB to copy")
    if target.drive and shutil.disk_usage(target.anchor).free < total * 1.1:
        sys.exit("Not enough free space at the target.")
    if not apply:
        check()
        print("\nDry run only. Add --apply to copy, verify, update the database and .env.")
        return

    bad = 0
    for i, (src, dst) in enumerate(files, 1):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not (dst.exists() and dst.stat().st_size == src.stat().st_size):
            shutil.copy2(src, dst)
        if sha256(src) != sha256(dst):
            print("VERIFY FAILED:", dst)
            bad += 1
        if i % 200 == 0:
            print(f"  {i}/{len(files)} copied", flush=True)
    if bad:
        sys.exit(f"{bad} file(s) failed verification. Nothing in the database or .env was changed.")
    print(f"copied and verified {len(files)} files")

    repoint(target)

    env = BACKEND / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    if env.exists():
        shutil.copy2(env, env.with_suffix(".env.bak"))
    lines = [line for line in lines if not line.startswith("DATA_DIR=")] + [f"DATA_DIR={target}"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"set DATA_DIR={target} in {env} (previous version: .env.bak)")
    print("\nStart the backend again. The originals are still in the old folders; delete them once the website works.")


if __name__ == "__main__":
    main()
