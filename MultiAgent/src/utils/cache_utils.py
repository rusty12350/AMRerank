# src/utils/cache_utils.py

import json
import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache/")
CACHE_TYPES = {
    "brief_summary": CACHE_DIR / "brief_summaries/",
    "deep_research": CACHE_DIR / "deep_research_reports/"
}
CacheType = Literal["brief_summary", "deep_research"]


def get_safe_filename(library_name: str) -> str:
    """
    """
    safe_name = library_name.replace(":", "__").replace(".", "_")
    final_safe_name = "".join(c for c in safe_name if c.isalnum() or c in ('-', '_'))
    return final_safe_name if final_safe_name else "unnamed_library"


def get_cache_path(library_name: str, cache_type: CacheType) -> Path:
    cache_directory = CACHE_TYPES.get(cache_type)
    if not cache_directory:
        raise ValueError(f" {cache_type}")

    safe_filename = get_safe_filename(library_name)
    return cache_directory / f"{safe_filename}.json"


def load_from_cache(library_name: str, cache_type: CacheType) -> dict | None:
    cache_path = get_cache_path(library_name, cache_type)
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            logger.info(f" {cache_path}")
            return json.load(f)
    except Exception as e:
        logger.warning(f"{cache_path} {e}")
        return None


def save_to_cache(library_name: str, data: dict, cache_type: CacheType):
    cache_path = get_cache_path(library_name, cache_type)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f" {cache_path}")
    except IOError as e:
        logger.error(f"{cache_path} : {e}")



def check_cache_exists(library_name: str, cache_type: CacheType) -> bool:
    cache_path = get_cache_path(library_name, cache_type)
    return cache_path.exists()