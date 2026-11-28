"""Delete one exact-name quiz score in one room, with a local SQLite backup."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

ROOT = Path(__file__).resolve().parents[1]


def delete_score(database, room, name):
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError('Quiz database not found on this PC.')
    if not room or not name:
        raise ValueError('Room and exact nickname are required.')
    # mode=rw prevents accidentally creating an empty database at a wrong path.
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=15)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            rows = db.execute('SELECT player,points FROM scores WHERE room=? AND name=?',
                              (str(room), name)).fetchall()
            if not rows:
                db.rollback()
                return None
            if len(rows) != 1:
                raise ValueError('More than one player has this exact nickname. Nothing deleted.')
            player, points = rows[0]
            backup_dir = database.parent / 'backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
            backup = backup_dir / f'before-score-delete-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3'
            # A second read connection can snapshot while BEGIN IMMEDIATE holds
            # the writer reservation; backing up the write connection can hang.
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=15)) as reader, \
                    closing(sqlite3.connect(backup)) as target:
                reader.backup(target)
            db.execute('DELETE FROM scores WHERE room=? AND player=? AND name=?',
                       (str(room), player, name))
            db.commit()
            return points, backup
        except Exception:
            db.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--room', required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    try:
        result = delete_score(ROOT / '.quiz/quiz.sqlite3', args.room, args.name)
    except (ValueError, sqlite3.Error, OSError) as error:
        raise SystemExit(str(error))
    if result is None:
        print(f'일치하는 점수 기록이 없습니다: {args.name} (방 {args.room})')
        return
    points, backup = result
    print(f'점수 삭제 완료: {args.name} · {points}점 (방 {args.room})')
    print(f'백업: {backup}')


if __name__ == '__main__':
    main()
