# Security policy

## Reporting a problem

Please report security problems privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**.

The package reads rule files and tables you give it, writes SQL and YAML, and opens no network connections. Problems worth a private report:

- A rule file that makes the loader or a compiler execute code, read files, or emit SQL other than a single read-only `SELECT` (for example through quoting in string literals or identifiers).
- A difference between backends that an outsider could steer: input that one backend flags and another silently does not.
- Inputs that make the Python evaluator or the Sigma reference interpreter use time or memory far out of proportion to their size.

Include a minimal rule and synthetic rows that reproduce it. Never send real customer data, even redacted. You should get an acknowledgement within five working days. Fixes land on `main` with a regression test and a CHANGELOG entry that credits you unless you ask not to be named.

A rule that misses a fraud pattern, or flags too much, is not a security issue; open a normal issue.

## Supported versions

This is a 0.x project. Only the latest commit on `main` gets fixes.
