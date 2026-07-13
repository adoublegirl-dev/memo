"""WorkBuddy 历史会话同步导入 Memo（前台执行，可中断续传）。"""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memo.services import WorkBuddySource
from memo.core.engine import engine

engine.init()

source = WorkBuddySource()
files = source.list_sessions()
print(f'WorkBuddy sessions: {len(files)}')

total = 0
for i, f in enumerate(files):
    msgs = source.read_messages(f)
    turns = source.extract_turns(msgs)
    if not turns:
        continue

    session = engine.start_session(title=source.get_session_title(f), agent_id=source.agent_id)

    for turn in turns:
        if len(turn) > 5000:
            turn = turn[:5000]
        try:
            r = engine.remember_conversation(
                session_id=session.id, conversation=turn,
                context_rounds=2, auto_extract=True, skip_cas=True,
            )
            total += 1
            if total % 10 == 0:
                print(f'  [{total}] {r["title"][:50]}')
        except Exception as e:
            print(f'  SKIP: {e}')

    engine.end_session(session.id)

    if (i + 1) % 5 == 0:
        print(f'Progress: {i+1}/{len(files)} sessions, {total} memories')

print(f'Done: {total} memories from {len(files)} sessions')
