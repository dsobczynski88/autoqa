# Prompt Templates

This directory contains Jinja2 templates for LLM prompts used in the RTM Review Agent.

## Overview

The prompt templates are loaded dynamically using Jinja2, allowing for:
- **Separation of concerns**: Prompts are separate from code logic
- **Easy maintenance**: Update prompts without modifying Python code
- **Template variables**: Customize prompts with dynamic content
- **Version control**: Track prompt changes independently

## Available Templates

### 1. `decomposer.jinja2`
Decomposes high-level requirements into atomic specifications.

**Purpose**: Transform ambiguous requirements into atomic, technical sub-function goals.

**Template Variables**: None (currently static)

**Usage**:
```python
from autoqa.components.rtm_review_agent_medtech.nodes import make_decomposer_node

node = make_decomposer_node(llm)
```

### 2. `summarizer.jinja2`
Summarizes raw test cases into structured format.

**Purpose**: Transform raw test data into structured summaries for coverage analysis.

**Template Variables**: None (currently static)

**Usage**:
```python
from autoqa.components.rtm_review_agent_medtech.nodes import make_summarizer_node

node = make_summarizer_node(llm)
```

### 3. `test_generator.jinja2`
Generates adversarial test cases to fill coverage gaps.

**Purpose**: Identify high-risk scenarios (Negative, Boundary, and Stress tests).

**Template Variables**: None (currently static)

**Usage**:
```python
from autoqa.components.rtm_review_agent_medtech.nodes import make_generator_node

node = make_generator_node(llm)
```

### 4. `coverage_evaluator.jinja2`
Evaluates test coverage against decomposed specifications.

**Purpose**: Perform gap analysis and identify escaped defect risks.

**Template Variables**: None (currently static)

**Usage**:
```python
from autoqa.components.rtm_review_agent_medtech.nodes import make_coverage_evaluator

node = make_coverage_evaluator(llm)
```

## Using Template Variables

To customize prompts with dynamic content, pass variables to the factory functions:

```python
from autoqa.components.rtm_review_agent_medtech.nodes import make_decomposer_node

# Pass custom variables
node = make_decomposer_node(
    llm,
    domain="cardiovascular devices",
    standard="IEC 60601-1"
)
```

Then update the template to use these variables:

```jinja2
### Role
Act as a Senior {{ domain }} Systems Engineer specializing in {{ standard }}.
```

## Direct Template Usage

You can also use the utility functions directly:

```python
from autoqa.utils import render_prompt, load_prompt_template

# Render a prompt with variables
prompt = render_prompt('decomposer.jinja2', domain='medical devices')

# Or load the template for more control
template = load_prompt_template('decomposer.jinja2')
prompt = template.render(domain='medical devices')
```

## Template Syntax

Templates use Jinja2 syntax:

- **Variables**: `{{ variable_name }}`
- **Conditionals**: `{% if condition %}...{% endif %}`
- **Loops**: `{% for item in items %}...{% endfor %}`
- **Comments**: `{# This is a comment #}`

Example:
```jinja2
### Role
Act as a {{ role_title }} specializing in {{ domain }}.

{% if include_examples %}
### Examples
- Example 1: {{ example_1 }}
- Example 2: {{ example_2 }}
{% endif %}
```

## Best Practices

1. **Keep prompts focused**: Each template should have a single, clear purpose
2. **Use descriptive names**: Template filenames should indicate their function
3. **Document variables**: Add comments in templates to explain expected variables
4. **Version control**: Commit prompt changes with descriptive messages
5. **Test changes**: Verify prompt modifications don't break functionality

## File Structure

```
autoqa/prompts/
├── README.md                    # This file
├── decomposer.jinja2           # Requirement decomposition prompt
├── summarizer.jinja2           # Test case summarization prompt
├── test_generator.jinja2       # Adversarial test generation prompt
└── coverage_evaluator.jinja2   # Coverage evaluation prompt
```

## Troubleshooting

### Template Not Found
If you get a `TemplateNotFound` error:
1. Verify the template file exists in `autoqa/prompts/`
2. Check the filename matches exactly (including `.jinja2` extension)
3. Ensure the file has read permissions

### Rendering Errors
If template rendering fails:
1. Check that all required variables are provided
2. Verify Jinja2 syntax is correct
3. Look for unclosed tags or brackets

### Import Errors
If you can't import the utility functions:
```python
# Correct import
from autoqa.utils import render_prompt

# Not from autoqa.components
```
