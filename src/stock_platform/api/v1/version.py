from fastapi import APIRouter

router = APIRouter(
    prefix="/version",
    tags=["Version"],
)


@router.get("")
def version():
    return {
        "version": "0.1.0"
    }