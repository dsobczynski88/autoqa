import os
import re
import json
import numpy as np
from tqdm.asyncio import tqdm_asyncio
import asyncio
import time
import ast
import pandas as pd
import flatdict
from typing import Any, Dict, List, Optional, Sequence, Union
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from openai import OpenAI
from openai.types.chat import ChatCompletion
from openai.types.chat.parsed_chat_completion import ParsedChatCompletion

def parse_llm_json_like(raw: str) -> Dict[str, Any]:
    """
    Robustly parses JSON-like strings produced by LLMs.
    Handles:
      - Escaped quotes
      - Python dict literals
      - Mixed quoting
    """

    if not raw or not isinstance(raw, str):
        raise ValueError("Input must be a non-empty string")

    text = raw.strip()

    # ----------------------------------------------------
    # Step 1: Unwrap if the entire payload is quoted
    # ----------------------------------------------------
    if (text.startswith("'") and text.endswith("'")) or \
       (text.startswith('"') and text.endswith('"')):
        text = text[1:-1]

    # Unescape common LLM escape patterns
    text = text.replace("\\'", "'").replace('\\"', '"')

    # ----------------------------------------------------
    # Step 2: Attempt strict JSON
    # ----------------------------------------------------
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ----------------------------------------------------
    # Step 3: Attempt Python literal parsing (SAFE)
    # ----------------------------------------------------
    try:
        result = ast.literal_eval(text)
        if isinstance(result, dict):
            return result
        raise ValueError("Parsed value is not a dictionary")
    except Exception:
        pass

    # ----------------------------------------------------
    # Step 4: Last-resort fixups → then JSON
    # ----------------------------------------------------
    repaired = text

    # Python → JSON boolean
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)

    # Convert single quotes to double quotes conservatively
    repaired = re.sub(r"(?<!\\)'", '"', repaired)

    return json.loads(repaired)


# -----------------------------------------------------------------------------
# Common utility functions for data processing
# -----------------------------------------------------------------------------
def load_input_data(input_file: str) -> pd.DataFrame:
    """
    Load CSV or Excel file into a pandas DataFrame.

    Args:
        input_file: Path to CSV or Excel file

    Returns:
        DataFrame with loaded data

    Raises:
        ValueError: If file extension is not supported or file path is invalid

    Example:
        >>> df = load_input_data("data/requirements.xlsx")
        >>> df = load_input_data("data/test_cases.csv")
    """
    if not input_file:
        raise ValueError("input_file is not provided")

    _, ext = os.path.splitext(input_file)
    ext = ext.lower()

    if ext == ".csv":
        return pd.read_csv(input_file)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(input_file)
    raise ValueError(f"Unsupported input file extension: {ext}")


def df_to_prompt_items(
    df: pd.DataFrame,
    columns: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
    """
    Convert each row of DataFrame into a dict suitable for processing.

    This utility function extracts specified columns from a DataFrame and converts
    each row into a dictionary. Keys are explicitly coerced to strings for
    compatibility with various processing functions.

    Args:
        df: Input DataFrame
        columns: List of column names to extract. If None, uses all columns.

    Returns:
        List of dictionaries, one per DataFrame row

    Raises:
        ValueError: If any specified columns are missing from the DataFrame

    Example:
        >>> df = pd.DataFrame({
        ...     "id": ["REQ-001", "REQ-002"],
        ...     "text": ["System shall...", "User shall..."],
        ...     "priority": ["high", "medium"]
        ... })
        >>> items = df_to_prompt_items(df, columns=["id", "text"])
        >>> # Returns: [
        >>> #   {"id": "REQ-001", "text": "System shall..."},
        >>> #   {"id": "REQ-002", "text": "User shall..."}
        >>> # ]
    """
    if columns is None:
        columns = df.columns.tolist()

    missing_cols = [c for c in columns if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing columns: {missing_cols}")

    records = df[columns].to_dict(orient="records")

    # Explicitly coerce keys to str to satisfy type checker and intended use
    return [{str(k): v for k, v in record.items()} for record in records]

def process_json_responses(
    responses: Sequence[Any],
    ids: Sequence[Any],
    prompt_type: str,
    ) -> List[Dict[str, Any]]:

    processed: List[Dict[str, Any]] = []

    for i, response in enumerate(responses):

        base_output: Dict[str, Any] = {
            "item_id": ids[i],
            "prompt_type": prompt_type,
        }

        # -------------------------------------------------
        # Handle None response
        # -------------------------------------------------
        if response is None:
            processed.append({
                **base_output,
                "error": "Prompt failed after retry",
            })
            continue

        # -------------------------------------------------
        # Extract content
        # -------------------------------------------------
        try:
            if (isinstance(response, ParsedChatCompletion)) or (isinstance(response, ChatCompletion)):
                content = response.choices[0].message.content
            elif isinstance(response, dict) and "response" in response:
                content = response["response"].content
            else:
                content = str(response)
        except Exception as e:
            processed.append({
                **base_output,
                "processing_error": str(e),
                "raw_response": str(response),
            })
            continue

        # -------------------------------------------------
        # Not JSON
        # -------------------------------------------------

        # -------------------------------------------------
        # Parse JSON (robust)
        # -------------------------------------------------
        try:
            response_json = parse_llm_json_like(content)
            if type(response_json) not in [str, dict]:
                processed.append(content)
                continue
        except Exception as e:
            processed.append({
                **base_output,
                "json_parse_error": str(e),
                "raw_response": content,
            })
            continue

        print(f"Response json: {response_json}")
        # -------------------------------------------------
        # Collect shared + row-level structures
        # -------------------------------------------------
        shared_flat: Dict[str, Any] = {}
        row_expanders: List[List[Dict[str, Any]]] = []

        for key, value in response_json.items():

            # ------------------------------
            # Case 1: dict → shared columns
            # ------------------------------
            if isinstance(value, dict):
                flat = flatdict.FlatDict(value, delimiter=".")
                shared_flat.update({f"{key}.{k}": v for k, v in flat.items()})

            # -------------------------------------------------------
            # Case 2: list of dicts → row-expanding structure
            # -------------------------------------------------------
            elif (
                isinstance(value, list)
                and value
                and all(isinstance(v, dict) for v in value)
            ):
                expanded_rows: List[Dict[str, Any]] = []
                for idx, item in enumerate(value):
                    flat = flatdict.FlatDict(item, delimiter=".")
                    expanded_rows.append(
                        {
                            f"{key}.{k}": v
                            for k, v in flat.items()
                        }
                    )
                row_expanders.append(expanded_rows)

            # ------------------------------
            # Case 3: scalar
            # ------------------------------
            else:
                shared_flat[key] = value

        # -------------------------------------------------
        # Combine shared + expanded rows
        # -------------------------------------------------

        if row_expanders:
            # Currently supports 1 expanding list cleanly
            for idx, row_payload in enumerate(row_expanders[0]):
                final_row = {
                    **base_output,
                    **shared_flat,
                    **row_payload,
                    "raw_response": content,
                }
                processed.append(final_row)
        else:
            processed.append({
                **base_output,
                **shared_flat,
                "raw_response": content,
            })

        # -------------------------------------------------
        # Token usage (if available)
        # -------------------------------------------------
        usage = getattr(response, "usage", None)
        if usage:
            last_rows = processed[-len(row_expanders[0]):] if row_expanders else [processed[-1]]
            for row in last_rows:
                try:
                    row.update(dict(usage))
                    for sub_key in ("prompt_tokens_details", "completion_tokens_details"):
                        sub = getattr(usage, sub_key, None)
                        if sub:
                            row.update(dict(sub))
                except Exception:
                    pass

    return processed

class OllamaPromptProcessor:
    def __init__(self, 
        client: ChatOllama,
        input_file: Optional[str] = None, 
        output_dir: str = ".", 
        model: str = "llama3",
        input_df: Optional[pd.DataFrame] = None,
        model_kwargs: Optional[Dict[str, Any]] = None):
        """
        Initialize the prompt processor.
        
        Args:
            input_file: Path to the input file (CSV, Excel, etc.)
            output_dir: Directory to save output results
            model: LLM model to use for processing
            pdf_directory: Directory containing PDF files for RAG (optional)
            use_rag: Whether to use RAG functionality
            input_df: Optional dataframe to use directly instead of loading from file
            model_kwargs: Additional kwargs for the LLM model
        
        Raises:
            ValueError: If neither input_file nor input_df is provided
        """
        self.client = client
        self.input_file = input_file
        self.output_dir = output_dir
        self.model = model
        self.input_df = input_df
        self.model_kwargs = model_kwargs or {
            "temperature": 0.3,
            "format": "json",
            "keep_alive": "1h"
            }
        self.last_port = None

        # Load data if needed
        if self.input_df is None and self.input_file:
            self.input_df = load_input_data(self.input_file)
        elif self.input_df is None and not self.input_file:
            raise ValueError("Either input_file or input_df must be provided")
        
    async def run_prompt_batch(self, 
        system_message: str, 
        user_message_template: str, 
        prompt_name: str, 
        items: List[Dict[str, Any]], 
        ids: List[Any] = None, 
        json_key: str = None,
        start_port: int = 11434,
        num_ports: int = 1) -> List[Dict]:
        """
        1-Format the input prompts via provided input items
        2-Collect the asynchronous tasks
        3-Run all prompts asynchronously through the rate-limited OpenAI backend
        4-Return a list of responses
        
        Args:
            system_message: System message for the LLM
            user_message_template: Template with {variable} placeholders
            prompt_name: Name of the prompt for tracking
            items: List of dictionaries with template variables
            ids: Optional identifiers for each item
            json_key: Optional key to extract from JSON response
            num_ports: Number of Ollama instances to use
            
        Returns:
            List of processed responses
        """
        # Use sequential IDs if none provided
        if ids is None:
            ids = list(range(len(items)))
        
        # Format all user messages
        formatted_messages = []
        for item in items:
            user_msg = user_message_template
            for key, value in item.items():
                placeholder = f"{{{key}}}"
                if placeholder in user_msg:
                    user_msg = user_msg.replace(placeholder, str(value))
            formatted_messages.append(user_msg)
        
        # Configure multiple Ollama instances
        PORTS=[]
        port_range=list(np.arange(0, num_ports, 1))
        for p in port_range:
            PORTS.append(start_port+p)
        self.last_port = PORTS[-1]
        
        models = [
            self.client(
                model=self.model,
                base_url=f"http://localhost:{port}",
                **self.model_kwargs
            )
            for port in PORTS
        ]
        
        # Create a shared counter for overall progress
        total_messages = len(formatted_messages)
        processed_count = 0
        
        # Create a lock for updating the counter
        counter_lock = asyncio.Lock()

        async def process_message(model, message):
            """Process a single message with retry logic"""
            nonlocal processed_count
            
            # Try with one retry on failure
            for attempt in range(2):
                try:
                    # Use SystemMessage and HumanMessage directly to avoid template issues
                    result = await model.ainvoke([
                        SystemMessage(content=system_message),
                        HumanMessage(content=message)
                    ])
                    
                    # Update the counter
                    async with counter_lock:
                        processed_count += 1
                        
                    return result
                except Exception as e:
                    if attempt == 0:
                        print(f"Error: {str(e)}. Retrying...")
                    else:
                        print(f"Retry failed. Skipping this message.")
                        # Update the counter even for failed messages
                        async with counter_lock:
                            processed_count += 1
                        return {}
        
        async def process_distributed(messages, models):
            """Distribute messages across available models with progress tracking"""
            # Calculate chunk size for each model
            num_models = len(models)
            try:
                # Original calculation that might cause ZeroDivisionError
                chunk_size = (len(messages) + num_models - 1) // num_models
            except ZeroDivisionError:
                # If num_models is 0 or division error occurs, set chunk_size to handle all messages
                raise
            
            # Create chunks of messages
            chunks = [
                messages[i:i + chunk_size] 
                for i in range(0, len(messages), chunk_size)
            ]
            
            # Create the main progress bar
            main_progress = tqdm_asyncio(
                total=total_messages,
                desc="Overall Progress",
                position=0,
                leave=True
            )
            
            # Process each chunk with a dedicated model
            async def process_chunk(model, chunk):
                results = []
                for msg in chunk:
                    print("Calling `process_message`")
                    result = await process_message(model, msg)
                    print(result)
                    results.append(result)
                    # Update the main progress bar
                    main_progress.update(1)
                return results
            
            # Run all chunks in parallel
            print(f"Processing {len(messages)} messages using {len(models)} Ollama instances...")
            results_nested = await asyncio.gather(*[
                process_chunk(models[i], chunks[i]) 
                for i in range(min(len(chunks), len(models)))
            ])
            
            # Close the progress bar
            main_progress.close()
            
            # Flatten results
            return [item for sublist in results_nested for item in sublist]
        
        # Process all messages in parallel with progress tracking
        start_time = time.time()
        responses = await process_distributed(formatted_messages, models)
        elapsed = time.time() - start_time
        print(f"Processed {len(responses)} messages in {elapsed:.2f}s")
        
        # Prepare results with IDs
        result_items = []
        for item_id, response in zip(ids, responses):
            if response is not None:
                result_items.append({
                    "id": item_id,
                    "response": response,
                    "prompt_name": prompt_name
                })
            else:
                print(f"Warning: Item with ID {item_id} failed to process")
        
        # Process JSON responses
        return result_items
        
        
# -----------------------------------------------------------------------------
# GraphProcessor - For running LangGraph graphs asynchronously
# -----------------------------------------------------------------------------
class GraphProcessor:
    """
    Process graph executions asynchronously using LangGraph runnables.

    Similar to PromptProcessor but designed for running LangGraph graphs instead of
    OpenAI API calls. Handles DataFrame input, graph execution, and result processing.
    """

    def __init__(
        self,
        graph_runnable: Any,
        input_file: Optional[str] = None,
        output_dir: str = "./output",
        input_df: Optional[pd.DataFrame] = None,
        graph_kwargs: Optional[Dict[str, Any]] = None,
        ) -> None:
        """
        Args:
            graph_runnable: LangGraph runnable instance (e.g., TestCaseReviewerRunnable)
            input_file: Optional CSV/Excel file path
            output_dir: Output directory for any saved results
            input_df: Preloaded DataFrame of input data
            graph_kwargs: Additional parameters to pass to graph execution
        """
        self.graph_runnable = graph_runnable
        self.input_file = input_file
        self.output_dir = output_dir
        self.input_df = input_df
        self.graph_kwargs = graph_kwargs or {}

        # Load data if needed
        if self.input_df is None and self.input_file:
            self.input_df = load_input_data(self.input_file)
        elif self.input_df is None and not self.input_file:
            raise ValueError("Either input_file or input_df must be provided")

    async def _run_graph(self, graph_input: Dict[str, Any]) -> Any:
        """
        Run a single graph execution asynchronously.

        Args:
            graph_input: Dictionary of input parameters for the graph
        Returns:
            The graph output (structure depends on graph implementation)
        """
        try:
            # Run the graph with provided input and any additional kwargs
            result = await self.graph_runnable.ainvoke(**graph_input, **self.graph_kwargs)
            return result
        except Exception as e:
            return {"error": str(e), "input": graph_input}

    async def run_graph_batch(
        self,
        items: Sequence[Dict[str, Any]],
        ids: Optional[Sequence[Any]] = None,
        graph_name: str = "graph_execution",
        ) -> List[Dict[str, Any]]:
        """
        Run multiple graph executions asynchronously.

        This is the graph equivalent of PromptProcessor.run_prompt_batch().

        Args:
            items: Sequence of input dictionaries for graph execution
            ids: Optional sequence of IDs for tracking results
            graph_name: Name/identifier for the graph type

        Returns:
            List of responses
        """
        ids = list(ids) if ids is not None else list(range(len(items)))

        print(f"🚀 Starting graph execution for {len(items)} items...")
        start_time = time.time()

        # Execute graph runs concurrently
        tasks = [self._run_graph(item) for item in items]
        results = await asyncio.gather(*tasks)

        elapsed = time.time() - start_time
        print(f"✅ Completed {len(results)} graph executions in {elapsed:.2f} seconds")
        return results

# -----------------------------------------------------------------------------
# OpenAIPromptProcessor
# -----------------------------------------------------------------------------
class OpenAIPromptProcessor:
    """
    Process prompts asynchronously using RateLimitOpenAIClient with token and request throttling.
    Handles prompt creation, OpenAI API calls, and JSON response normalization.
    """
    def __init__(
        self,
        client,
        input_file: Optional[str] = None,
        output_dir: str = "./output",
        model: str = "gpt-4o-mini",
        pdf_directory: Optional[str] = None,
        use_rag: bool = False,
        input_df: Optional[pd.DataFrame] = None,
        model_kwargs: Optional[Dict[str, Any]] = None,
        ) -> None:
        """
        Args:
            client: Initialized RateLimitOpenAIClient instance.
            input_file: Optional CSV/Excel file path.
            output_dir: Output directory for any saved results.
            model: OpenAI model name (e.g., "gpt-4o-mini").
            pdf_directory: Path for optional RAG context (future extension).
            use_rag: Whether to use retrieval-augmented generation components.
            input_df: Preloaded DataFrame of prompt data.
            model_kwargs: Parameters for OpenAI completions (temperature, max_tokens, etc.).
        """
        self.client = client
        self.input_file = input_file
        self.output_dir = output_dir
        self.model = model
        self.input_df = input_df
        self.model_kwargs = model_kwargs

        # Load data if needed
        if self.input_df is None and self.input_file:
            self.input_df = load_input_data(self.input_file)
        elif self.input_df is None and not self.input_file:
            raise ValueError("Either input_file or input_df must be provided")

    async def _call_openai_parse(self, system_message: str, user_prompt: str) -> str:
        """
        Make a single asynchronous call to the OpenAI API with proper rate limiting.

        Returns:
            The assistant message content (string) or an error JSON.
        """
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt},
        ]
        try:
            completion = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                **self.model_kwargs,
            )
            return completion
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def run_prompt_batch_parse(
        self,
        system_message: str,
        user_message_template: str,
        prompt_name: str,
        items: Sequence[Dict[str, Any]],
        ids: Optional[Sequence[Any]] = None,
        json_key: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
        """
        1-Format the input prompts via provided input items
        2-Collect the asynchronous tasks
        3-Run all prompts asynchronously through the rate-limited OpenAI backend
        4-Return a list of responses
        """
        ids = list(ids) if ids is not None else list(range(len(items)))

        formatted_prompts = []
        print(f"Items: {items}")
        for item in items:
            msg = user_message_template
            for k, v in item.items():
                msg = msg.replace(f"{{{k}}}", str(v))
            formatted_prompts.append(msg)

        # Execute async API calls concurrently
        tasks = [self._call_openai_parse(system_message, user_msg) for user_msg in formatted_prompts]
        responses = await asyncio.gather(*tasks)
        return responses

    async def _call_openai(self, system_message: str, user_prompt: str) -> str:
        """
        Make a single asynchronous call to the OpenAI API with proper rate limiting.

        Returns:
            The assistant message content (string) or an error JSON.
        """
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt},
        ]
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **self.model_kwargs,
            )
            return completion
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def run_prompt_batch(
        self,
        system_message: str,
        user_message_template: str,
        prompt_name: str,
        items: Sequence[Dict[str, Any]],
        ids: Optional[Sequence[Any]] = None,
        json_key: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
        """
        1-Format the input prompts via provided input items
        2-Collect the asynchronous tasks
        3-Run all prompts asynchronously through the rate-limited OpenAI backend
        4-Return a list of responses
        """
        ids = list(ids) if ids is not None else list(range(len(items)))

        formatted_prompts = []
        print(f"Items: {items}")
        for item in items:
            msg = user_message_template
            for k, v in item.items():
                msg = msg.replace(f"{{{k}}}", str(v))
            formatted_prompts.append(msg)

        # Execute async API calls concurrently
        tasks = [self._call_openai(system_message, user_msg) for user_msg in formatted_prompts]
        responses = await asyncio.gather(*tasks)
        return responses

class BasicOpenAIProcessor:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model
        self.previous_response_ids: List[str] = []
        self.previous_responses: List[str] = []

    def get_response(
        self,
        input: Union[List, str],
        print_response: bool = True,
        store: bool = True,  # Kept for backwards compatibility
        previous_response_id: Optional[str] = None,  # Kept for backwards compatibility
        **kwargs
        ):
        # Provide the essentials, then allow override via kwargs
        params = {
            "model": self.model,
            "input": input,
            "store": store,
            "previous_response_id": previous_response_id,
        }
        params.update(kwargs)  # allow all other supported/needed arguments

        response = self.client.responses.create(**params)
        self.previous_responses.append(response.output_text)
        self.previous_response_ids.append(response.id)
        if print_response:
            print("Printing `response.output_text`:\n\n", response.output_text)
        return response

    def get_structured_response(
        self,
        messages,
        response_format,
        **kwargs
        ):
        params = {
            "model": self.model,
            "messages": messages,
            "response_format": response_format,
        }
        params.update(kwargs)

        completion = self.client.beta.chat.completions.parse(**params)
        return completion.choices[0].message

    @staticmethod
    def check_structured_output(completion):
        # If the model refuses to respond, you will get a refusal message
        if getattr(completion, "refusal", False):
            print(completion.refusal)
        else:
            print(getattr(completion, "parsed", completion))
