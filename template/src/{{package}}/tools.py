from sqlalchemy import select

from homelab_common import audit, db, tool

from .models import Note, NoteOut


@tool
async def add_note(text: str) -> NoteOut:
    """Add a note."""
    async with db.session() as s:
        note = Note(text=text)
        s.add(note)
        await s.flush()
        await s.refresh(note)
        await audit.record(
            s,
            action="note.add",
            target=("note", str(note.id)),
            after=audit.changes(None, note),
            summary=f"Added note {note.id}",
        )
        return NoteOut.model_validate(note)


@tool
async def list_notes() -> list[NoteOut]:
    """List all notes, newest first."""
    async with db.session() as s:
        rows = (await s.execute(select(Note).order_by(Note.id.desc()))).scalars().all()
        return [NoteOut.model_validate(row) for row in rows]
