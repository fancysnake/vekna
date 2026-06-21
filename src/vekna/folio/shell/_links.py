import asyncio


async def run_bash(command: str, *, cwd: str | None = None) -> tuple[str, str, int]:
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await process.communicate()
    return (stdout or b"").decode(), (stderr or b"").decode(), process.returncode or 0
