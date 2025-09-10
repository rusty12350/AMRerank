import logging
from typing import Annotated, Dict, Any, Optional  # 新增 Optional

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig  # 【核心修改1】导入 RunnableConfig
from .decorators import log_io

from langchain.chains.summarize import load_summarize_chain
from langchain.text_splitter import RecursiveCharacterTextSplitter
from src.crawler.crawler import Crawler
from src.llms.llm import get_llm_by_type
from src.config.configuration import Configuration  # 【核心修改2】导入 Configuration 类

logger = logging.getLogger(__name__)


@tool
@log_io
def crawl_tool(
        url: Annotated[str, "The url to crawl."],
        config: Annotated[Optional[RunnableConfig], "The RunnableConfig for this execution."] = None
) -> str:
    """Use this to crawl a url and get its readable content. Long content will be summarized."""
    try:
        crawler = Crawler()
        article = crawler.crawl(url)
        return {"url": url, "crawled_content": article.to_markdown()[:1000]}
    except BaseException as e:
        error_msg = f"Failed to crawl. Error: {repr(e)}"
        logger.error(error_msg)
        return error_msg