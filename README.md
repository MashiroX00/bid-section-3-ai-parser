# PDF Evidence Extractor

This project automates the extraction of "Evidence for Submission" (Section 3) from PDF documents (specifically TOR documents) and structures the data into JSON format using the OpenAI Batch API.

## Project Structure

- **`input_pdfs/`**: Place your source PDF files here. The script will scan this directory for files to process.
- **`output_jsons/`**: The processed data will be saved here as individual JSON files corresponding to each input PDF.
- **`main.py`**: The main application script. It handles text extraction using regex, interacts with the OpenAI Batch API, and manages file input/output.
- **`batch_input_filtered.jsonl`**: (Generated) The temporary batch file created by the script to send requests to OpenAI.
- **`current_batch_id.txt`**: (Generated) Stores the ID of the currently active OpenAI Batch job to allow for status checking and result retrieval.
- **`pyproject.toml` / `uv.lock` / `.python-version`**: Configuration files for the [uv](https://github.com/astral-sh/uv) package manager and Python dependency management.

## Setup and Installation

This project uses **uv** for fast and reliable Python package management.

### 1. Install uv

If you haven't installed `uv` yet, you can do so by following the instructions [here](https://github.com/astral-sh/uv) or running:

**Windows (PowerShell):**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS/Linux:**
```bash
curl -lsSf https://astral.sh/uv/install.sh | sh
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory and add your OpenAI API Key:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Install Dependencies

Sync the project dependencies using `uv`:

```bash
uv sync
```

## How to Run

You can run the script directly using `uv run`. This will automatically handle the virtual environment and dependencies.

```bash
uv run main.py
```

### Usage Workflow

The script provides an interactive menu with two main options:

1.  **Scan PDFs & Submit Batch (Prepare & Upload)**
    -   Select this option to process new files in the `input_pdfs/` folder.
    -   The script will extract the relevant text from the PDFs.
    -   It will create a batch job and submit it to OpenAI.
    -   A Batch ID will be saved to `current_batch_id.txt`.

2.  **Check Status & Download Results**
    -   Select this option to check the status of the submitted batch job.
    -   If the job is `completed`, it will download the results and save them to the `output_jsons/` folder.
    -   If the job is still `in_progress`, wait a while and try again.

### Note on File Processing
- **Skipping Existing Files**: By default, the script is set to `SKIP_EXISTING = True`. It will skip PDFs that already have a corresponding JSON file in the `output_jsons/` folder to save costs and time.