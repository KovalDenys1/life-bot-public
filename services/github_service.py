"""
GitHub file I/O with 60-second cache and retry logic.
All vault reads/writes go through here.
"""
import time
import logging
from github import GithubException
from config import gh, GITHUB_REPO

logger = logging.getLogger(__name__)

_file_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 60  # seconds


def get_repo():
    return gh.get_repo(GITHUB_REPO)


def sanitize_tables(content: str) -> str:
    """Remove blank lines inside markdown tables to prevent broken rendering in Obsidian."""
    lines = content.splitlines()
    result = []
    for i, line in enumerate(lines):
        if not line.strip():
            prev = result[-1].strip() if result else ''
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if prev.startswith('|') and nxt.startswith('|'):
                continue
        result.append(line)
    return '\n'.join(result)


def read_file(path: str) -> str | None:
    now = time.time()
    if path in _file_cache:
        cached_content, ts = _file_cache[path]
        if now - ts < CACHE_TTL:
            return cached_content
    try:
        content = get_repo().get_contents(path)
        text = content.decoded_content.decode("utf-8")
        _file_cache[path] = (text, now)
        return text
    except GithubException:
        return None


def read_file_tail(path: str, lines: int = 60) -> str | None:
    """Read a file but return only the last N lines (for large growing logs)."""
    content = read_file(path)
    if content is None:
        return None
    all_lines = content.splitlines()
    if len(all_lines) <= lines:
        return content
    return "\n".join(all_lines[:3] + ["..."] + all_lines[-lines:])


def write_file(path: str, content: str, message: str = "Bot update") -> bool:
    """Write a file to GitHub with up to 3 attempts. Returns True on success."""
    if path.endswith('.md'):
        content = sanitize_tables(content)

    last_exc = None
    for attempt in range(3):
        try:
            repo = get_repo()
            try:
                existing = repo.get_contents(path)
                repo.update_file(path, message, content, existing.sha)
            except GithubException as e:
                if e.status == 404:
                    repo.create_file(path, message, content)
                else:
                    raise
            _file_cache[path] = (content, time.time())
            return True
        except Exception as e:
            last_exc = e
            if attempt < 2:
                logger.warning(f"write_file attempt {attempt + 1} failed for {path}: {e}, retrying in {attempt + 1}s…")
                time.sleep(attempt + 1)

    logger.error(f"write_file failed after 3 attempts for {path}: {last_exc}")
    return False


def invalidate_cache(path: str) -> None:
    _file_cache.pop(path, None)
