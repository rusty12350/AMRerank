# ROLE
You are an expert software library analyst specializing in code dependency and migration.

# TASK
Your task is to analyze the raw JSON profile of a Java library provided below and distill it into a standardized, structured summary. You must focus on extracting its core purpose and technical identity.

# INSTRUCTIONS
1.  **core_function**: In a single, clear sentence, summarize the core technical problem this library solves.
2.  **key_apis**: From the `key_features` or other descriptions, extract a list of up to 3 of the most critical class names, interface names, or design patterns.
3.  **technical_domain**: From the `keywords_for_analysis` or other descriptions, extract a list of up to 3 of the most essential technical domain tags.

# RAW LIBRARY PROFILE (JSON INPUT)

# OUTPUT COMMAND
Directly output the raw JSON of `StandardizedProfile` without "```json" or any other markdown. The `StandardizedProfile` interface is defined as follows:
```json
{
  "core_function": "string",
  "key_apis": ["string", "..."],
  "technical_domain": ["string", "..."]
}