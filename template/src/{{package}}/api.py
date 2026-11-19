from fastapi import APIRouter

from .models import NoteIn, NoteOut
from .tools import add_note, list_notes

router = APIRouter()


@router.get("/notes")
async def get_notes() -> list[NoteOut]:
    return await list_notes()


@router.post("/notes")
async def post_note(body: NoteIn) -> NoteOut:
    return await add_note(body.text)
