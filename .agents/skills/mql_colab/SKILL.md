```markdown
# mql_colab Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches best practices and conventions for contributing to the `mql_colab` Python codebase. You'll learn about file naming, import/export styles, commit message patterns, and how to structure your code for consistency. While no specific frameworks or automated workflows are detected, the repository follows clear conventions that help maintain code quality and readability.

## Coding Conventions

### File Naming
- Use **snake_case** for all filenames.
  - Example: `data_loader.py`, `model_utils.py`

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import preprocess_data
    ```

### Export Style
- Use **named exports** (i.e., define specific functions/classes to be imported elsewhere).
  - Example:
    ```python
    def train_model(...):
        ...
    ```

### Commit Messages
- Use **conventional commit** format.
- Prefix commit messages with `feat`.
- Example:
  ```
  feat: add data preprocessing utilities for feature extraction
  ```

## Workflows

### Adding a New Feature
**Trigger:** When you want to introduce a new capability or module.
**Command:** `/add-feature`

1. Create a new Python file using snake_case (e.g., `new_feature.py`).
2. Implement your feature with named exports (functions/classes).
3. Use relative imports to access shared utilities.
4. Write a commit message starting with `feat:`.
5. Submit your changes for review.

### Refactoring Existing Code
**Trigger:** When improving or restructuring code without changing its external behavior.
**Command:** `/refactor-code`

1. Identify the code to refactor.
2. Update file and function names to follow snake_case if necessary.
3. Replace absolute imports with relative imports.
4. Ensure all exports are named.
5. Commit with a message like `feat: refactor [module] for clarity`.

## Testing Patterns

- Test files are expected to follow the `*.test.ts` pattern, though the testing framework is unknown.
- If adding tests, ensure they are named accordingly (e.g., `module_name.test.ts`).
- Place test files alongside the code they test or in a dedicated `tests/` directory if present.

## Commands
| Command         | Purpose                                       |
|-----------------|-----------------------------------------------|
| /add-feature    | Start the process of adding a new feature     |
| /refactor-code  | Begin a code refactor with conventions        |
```
