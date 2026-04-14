from typing import Optional

from pydantic import BaseModel


class OpenTaskSourceDto(BaseModel):
    url: Optional[str] = None

