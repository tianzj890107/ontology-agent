"""Bundled skills that ship with Open Claude."""

from .registry import Skill, get_registry


def _register(skill: Skill):
    get_registry().register(skill)


# ---------------------------------------------------------------------------
# /commit - Generate git commit
# ---------------------------------------------------------------------------

COMMIT_PROMPT = """Review all staged and unstaged changes, then create a git commit.

Steps:
1. Run `git status` to see all changes
2. Run `git diff` to see unstaged changes and `git diff --cached` to see staged changes
3. Run `git log --oneline -5` to see recent commit style
4. Analyze the changes and draft a concise commit message:
   - Summarize the nature (feature, fix, refactor, docs, test, etc.)
   - Focus on the "why" rather than the "what"
   - Keep first line under 72 chars
5. Stage relevant files (prefer specific files over `git add -A`)
6. Create the commit

IMPORTANT:
- Do NOT commit files that contain secrets (.env, credentials, etc.)
- Do NOT use --no-verify or skip hooks
- Do NOT amend existing commits unless explicitly asked
- If pre-commit hooks fail, fix the issue and create a NEW commit
"""


def register_commit():
    _register(Skill(
        name="commit",
        description="Generate a git commit from current changes",
        when_to_use="When the user asks to commit, create a commit, or save changes to git",
        user_invocable=True,
        argument_hint="Optional: commit message hint",
        source="bundled",
        get_prompt=lambda args: COMMIT_PROMPT + (f"\nUser hint: {args}" if args else ""),
    ))


# ---------------------------------------------------------------------------
# /simplify - Review and simplify code
# ---------------------------------------------------------------------------

SIMPLIFY_PROMPT = """Review the changed code for quality, reuse, and efficiency.

Steps:
1. Check git diff to see what changed
2. Look for:
   - Code that could reuse existing utilities/functions
   - Unnecessary complexity or over-engineering
   - Premature abstractions or dead code
   - Missing error handling at system boundaries
   - Security issues (injection, XSS, etc.)
3. Fix any issues found directly in the code
4. Keep fixes minimal - only fix actual problems, don't refactor working code
"""


def register_simplify():
    _register(Skill(
        name="simplify",
        description="Review changed code for quality and simplify",
        when_to_use="When user asks to review, simplify, or clean up code",
        user_invocable=True,
        source="bundled",
        get_prompt=lambda args: SIMPLIFY_PROMPT + (f"\nFocus on: {args}" if args else ""),
    ))


# ---------------------------------------------------------------------------
# /review - Review a PR or diff
# ---------------------------------------------------------------------------

REVIEW_PROMPT = """Review code changes for bugs, security issues, and quality.

Steps:
1. If a PR number is given, fetch it with `gh pr view <number>` and `gh pr diff <number>`
2. Otherwise, review `git diff` for current changes
3. Look for:
   - Bugs and logic errors
   - Security vulnerabilities (OWASP top 10)
   - Performance issues
   - Missing error handling
   - Breaking API changes
4. Provide a concise summary of findings with file:line references
"""


def register_review():
    _register(Skill(
        name="review",
        description="Review code changes or a pull request",
        when_to_use="When user asks to review code, a PR, or a diff",
        user_invocable=True,
        argument_hint="PR number or description of what to review",
        source="bundled",
        get_prompt=lambda args: REVIEW_PROMPT + (f"\nReview target: {args}" if args else ""),
    ))


# ---------------------------------------------------------------------------
# /test - Run tests
# ---------------------------------------------------------------------------

TEST_PROMPT = """Find and run the project's test suite.

Steps:
1. Detect the project type and test framework:
   - Python: pytest, unittest, nose
   - Node.js: jest, mocha, vitest
   - Go: go test
   - Rust: cargo test
   - etc.
2. Run the appropriate test command
3. If tests fail, analyze the output and suggest fixes
4. If no test framework is found, inform the user
"""


def register_test():
    _register(Skill(
        name="test",
        description="Find and run the project's tests",
        when_to_use="When user asks to run tests, check tests, or verify code",
        user_invocable=True,
        argument_hint="Optional: specific test file or pattern",
        source="bundled",
        get_prompt=lambda args: TEST_PROMPT + (f"\nRun specifically: {args}" if args else ""),
    ))


# ---------------------------------------------------------------------------
# /explain - Explain code
# ---------------------------------------------------------------------------

EXPLAIN_PROMPT = """Explain the specified code or file clearly and concisely.

Steps:
1. Read the file or code section specified
2. Explain:
   - What it does at a high level
   - Key functions/classes and their purpose
   - Important patterns or design decisions
   - How it fits into the broader project (if relevant)
3. Keep explanations concise, use bullet points
4. Tailor depth to the complexity of the code
"""


def register_explain():
    _register(Skill(
        name="explain",
        description="Explain code or a file",
        when_to_use="When user asks to explain, describe, or walk through code",
        user_invocable=True,
        argument_hint="File path or code description",
        source="bundled",
        get_prompt=lambda args: EXPLAIN_PROMPT + (f"\nExplain: {args}" if args else ""),
    ))


# ---------------------------------------------------------------------------
# /fix - Fix a bug or error
# ---------------------------------------------------------------------------

FIX_PROMPT = """Diagnose and fix the reported bug or error.

Steps:
1. Understand the problem from the user's description or error output
2. Search for relevant code using Grep/Glob
3. Read the relevant files
4. Identify the root cause
5. Implement the fix with minimal changes
6. Verify the fix makes sense (run tests if available)

IMPORTANT:
- Fix the root cause, not just symptoms
- Make minimal changes - don't refactor unrelated code
- Preserve existing behavior for unaffected cases
"""


def register_fix():
    _register(Skill(
        name="fix",
        description="Diagnose and fix a bug or error",
        when_to_use="When user reports a bug, error, or something broken",
        user_invocable=True,
        argument_hint="Error message or bug description",
        source="bundled",
        get_prompt=lambda args: FIX_PROMPT + (f"\nProblem: {args}" if args else ""),
    ))


# ---------------------------------------------------------------------------
# Initialize all bundled skills
# ---------------------------------------------------------------------------

def init_bundled_skills():
    """Register all bundled skills."""
    register_commit()
    register_simplify()
    register_review()
    register_test()
    register_explain()
    register_fix()
