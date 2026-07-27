from pydantic import BaseModel


class ShellResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
