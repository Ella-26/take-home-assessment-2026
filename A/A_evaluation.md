# Section A: Evaluation

Model used: `deepseek-flash`.

## 1. Where it still fails

No extraction errors were identified in the 12 final outputs. Test 3 ignored the prompt injection.

## 2. How consistent the runs were

All 12 outputs were valid JSON with the required fields. For each input, the extracted values matched across all three runs. Some evidence quotes differed in length or punctuation, while remaining exact quotes from the input.

## 3. Unclear requirements and what I decided

The requirements do not specify whether an unqualified "$" means USD or whether a city can establish the country. I treated "$3M" as USD and mapped unambiguous cities to countries. I left sector as null when the company’s business was not stated.

Test 4 source: https://wayve.ai/press/series-c/
