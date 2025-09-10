import os
import logging
import requests
import base64
import xml.etree.ElementTree as ET

from langchain_core.tools import tool
from langchain.chains.summarize import load_summarize_chain
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.llms.llm import get_llm_by_type


CONTENT_LENGTH_THRESHOLD = 8000

README_LINE_LIMIT = 30

DEFAULT_TRUNCATION_LIMIT = 16000
POM_TRUNCATION_LIMIT_BEFORE_SUMMARY = 16000

ISSUE_SUMMARIZATION_THRESHOLD = 6000



logger = logging.getLogger(__name__)


def _extract_pom_key_sections(xml_content: str) -> str:
    """
    A helper function to extract key sections from pom.xml content.
    """
    try:
        # Remove namespaces to simplify parsing
        xml_content = xml_content.replace('xmlns="http://maven.apache.org/POM/4.0.0"', '')
        root = ET.fromstring(xml_content)

        key_sections = []
        # Define the XML tags we care about
        tags_to_find = ['parent', 'properties', 'dependencyManagement', 'dependencies']

        for tag in tags_to_find:
            element = root.find(tag)
            if element is not None:
                # Convert the found XML element back to a string and add it to the list
                key_sections.append(ET.tostring(element, encoding='unicode'))

        if not key_sections:
            return "Note: The pom.xml is too long, but no key sections (parent, properties, dependencyManagement, dependencies) were found to summarize."

        return "\n".join(key_sections)
    except ET.ParseError:
        logger.warning("Could not parse pom.xml, returning a snippet of the file instead.")
        # Fallback to returning the beginning of the file if XML parsing fails
        return xml_content[:CONTENT_LENGTH_THRESHOLD]


@tool
def read_github_file(repo_and_path: str) -> str:
    """
    Reads the raw content of a single file from a public GitHub repository.
    If the file is too long, it will be intelligently extracted and summarized based on its type (pom.xml, README.md, etc.).
    The input argument must be a string in the format 'owner/repository:path/to/file'.
    """
    logger.info(f"--- [GitHub ReadFile Tool] Task: '{repo_and_path}' ---")

    # (Input cleaning and parsing)
    try:
        cleaned_input = repo_and_path.strip().strip("'\"")
        repo_str, file_path = cleaned_input.split(':', 1)
        owner, repo = repo_str.split('/', 1)
    except ValueError:
        return "Error: Invalid input format. Please ensure the format is 'owner/repository:path/to/file'."

    try:
        github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
        if not github_token:
            return "Error: GITHUB_PERSONAL_ACCESS_TOKEN not found in environment variables."

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {github_token}",
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()
        if 'content' not in data:
            return f"Error: 'content' not found in API response. '{file_path}' might be a directory, not a file."

        file_content_decoded = base64.b64decode(data['content']).decode('utf-8')

    except requests.exceptions.RequestException as e:
        error_message = f"Error: GitHub API call failed. Repository '{repo_str}' or file '{file_path}' may not exist, or the Token is invalid. Details: {e}"
        logger.error(error_message)
        return error_message
    except Exception as e:
        error_message = f"Error: An unknown error occurred while fetching file content: {e}"
        logger.error(error_message, exc_info=True)
        return error_message

    if len(file_content_decoded) < CONTENT_LENGTH_THRESHOLD:
        logger.info(
            f"--- [GitHub ReadFile Tool] File content is short ({len(file_content_decoded)} chars), returning raw content. ---")
        return file_content_decoded
    else:
        logger.info(
            f"--- [GitHub ReadFile Tool] File content is too long ({len(file_content_decoded)} chars), starting smart extraction and summarization. ---")

        content_to_summarize = ""
        if file_path.lower().endswith('pom.xml'):
            logger.info("--- [POM Stage 1/3] Extracting key sections from pom.xml.")
            extracted_content = _extract_pom_key_sections(file_content_decoded)
            logger.info(f"--- [POM Stage 1/3] Extraction complete. Length: {len(extracted_content)} chars.")

            content_for_summary = extracted_content
            truncation_note = ""

            if len(extracted_content) > POM_TRUNCATION_LIMIT_BEFORE_SUMMARY:
                logger.info(
                    f"--- [POM Stage 2/3] Extracted content is still too long. Truncating to {POM_TRUNCATION_LIMIT_BEFORE_SUMMARY} chars before summary.")
                content_for_summary = extracted_content[:POM_TRUNCATION_LIMIT_BEFORE_SUMMARY]
                truncation_note = f"The extracted content was then truncated to {POM_TRUNCATION_LIMIT_BEFORE_SUMMARY} chars before final summarization."
            else:
                logger.info("--- [POM Stage 2/3] Extracted content is within the limit. No truncation needed.")

            logger.info("--- [POM Stage 3/3] Proceeding to final LLM summarization.")
            summarizer_llm = get_llm_by_type("basic")
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=200)
            docs = [Document(page_content=x) for x in text_splitter.split_text(content_for_summary)]

            if not docs: return "Note: The pom.xml was processed, but no effective content was left for final summarization."

            summary_chain = load_summarize_chain(llm=summarizer_llm, chain_type="map_reduce")
            summary_result = summary_chain.invoke(docs)
            final_summary = summary_result.get("output_text", "[Summarization Failed: No output text]")

            return f"Note: The original pom.xml was too long. It was processed as follows:\n1. Key sections were extracted.\n2. {truncation_note or 'No truncation was needed.'}\n3. The result was summarized by an LLM:\n\n{final_summary}"

        elif file_path.lower().endswith('readme.md'):
            logger.info(
                f"--- [GitHub ReadFile Tool] Detected README.md, extracting first {README_LINE_LIMIT} lines. ---")
            content_to_summarize = "\n".join(file_content_decoded.splitlines()[:README_LINE_LIMIT])
        else:
            logger.info(
                f"--- [GitHub ReadFile Tool] Unknown file type, truncating to {DEFAULT_TRUNCATION_LIMIT} characters. ---")
            content_to_summarize = file_content_decoded[:DEFAULT_TRUNCATION_LIMIT]

        try:
            summarizer_llm = get_llm_by_type("basic")

            text_splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=200)
            docs = [Document(page_content=x) for x in text_splitter.split_text(content_to_summarize)]

            if not docs:
                return "Note: The original file was too long, but no effective content could be extracted for summarization."

            summary_chain = load_summarize_chain(llm=summarizer_llm, chain_type="map_reduce")
            summary_result = summary_chain.invoke(docs)

            processed_content = summary_result.get("output_text", "[Summarization Failed: No output text]")

            logger.info(
                f"--- [GitHub ReadFile Tool] Summarization complete. Length: {len(processed_content)} chars. ---")
            return f"Note: The original file was too long. Here is an intelligent summary of its key parts:\n\n{processed_content}"

        except Exception as e:
            error_message = f"Error: An error occurred during content summarization: {e}"
            logger.error(error_message, exc_info=True)
            return f"Error: Failed to summarize the file. Here is a preview of the beginning of the file:\n\n{file_content_decoded[:2000]}..."


@tool
def get_github_issue(repo_and_issue_number: str) -> str:
    """
    Fetches details for a single issue from a GitHub repository. If the issue body is too long, it will be automatically summarized.
    The input must be a string in the format 'owner/repository:issue_number'.
    For example: 'langchain-ai/langchain:19998'.
    """
    logger.info(f"--- [GitHub GetIssue Tool] Task: '{repo_and_issue_number}' ---")

    try:
        repo_str, issue_number_str = repo_and_issue_number.strip().strip("'\"").split(':', 1)
        owner, repo = repo_str.split('/', 1)
        if not issue_number_str.isdigit():
            raise ValueError("The issue number must be a valid integer.")
        issue_number = int(issue_number_str)
    except ValueError as e:
        return f"Error: Invalid input format. Expected 'owner/repository:issue_number'. Details: {e}"

    github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not github_token:
        return "Error: GITHUB_PERSONAL_ACCESS_TOKEN is not configured in the environment."

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {github_token}"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        issue_title = data.get('title', 'No Title')
        issue_body = data.get('body', '')
        issue_state = data.get('state', 'unknown')
        issue_labels = [label['name'] for label in data.get('labels', [])]
        author = data.get('user', {}).get('login', 'unknown author')

        processed_body = issue_body
        summary_note = ""

        if len(issue_body) > ISSUE_SUMMARIZATION_THRESHOLD:
            logger.info(f"Issue body is too long ({len(issue_body)} chars). Starting summarization.")
            summary_note = "\n[NOTE: The original issue body was too long and has been summarized below.]"

            try:
                summarizer_llm = get_llm_by_type("basic")
                if summarizer_llm is None:
                    raise ImportError("Summarizer LLM could not be loaded.")

                text_splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=200)
                docs = [Document(page_content=x) for x in text_splitter.split_text(issue_body)]

                summary_chain = load_summarize_chain(llm=summarizer_llm, chain_type="map_reduce")
                summary_result = summary_chain.invoke(docs)

                processed_body = summary_result.get("output_text",
                                                    "Summarization failed: Could not extract output text.")
                logger.info("Summarization successful.")

            except Exception as e:
                logger.error(f"Error during summarization: {e}", exc_info=True)
                processed_body = f"Summarization failed. Showing preview:\n\n{issue_body[:2000]}..."

        formatted_output = (
            f"Details for Issue #{issue_number} (State: {issue_state}):\n"
            f"Repository: {owner}/{repo}\n"
            f"Author: {author}\n"
            f"Labels: {', '.join(issue_labels) or 'None'}\n"
            f"Title: {issue_title}\n"
            f"------------------ Body{summary_note} ------------------\n"
            f"{processed_body.strip() if processed_body else 'This issue has no body content.'}"
        )
        return formatted_output

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return f"Error: The specified issue was not found. Please check if repository '{owner}/{repo}' and issue #{issue_number} exist."
        return f"Error: An HTTP error occurred: {e}"
    except Exception as e:
        return f"Error: An unexpected error occurred: {e}"