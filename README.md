# TOR PDF Extractor (PostgreSQL + OpenAI Batch API)

This project automates the extraction of "Evidence for Submission" (Section 3) from TOR PDF documents. It extracts relevant text using regex, processes it via the OpenAI Batch API to structure it into JSON, and stores the final results in a PostgreSQL database.

## Features

- **Text Extraction**: Automatically scans `input_pdfs/` and extracts the specific "Evidence for Submission" section using regex.
- **OpenAI Batch API**: efficient, cost-effective processing of multiple files.
- **PostgreSQL Integration**: Saves extracted structured data directly into a PostgreSQL database (`batch_data.batch_json` table).
- **Auto Pilot Mode**: "Fire and forget" mode that handles submission, polling, and saving in one go.
- **Deduplication**: Checks the database to skip files that have already been processed.

## Project Structure

- **`input_pdfs/`**: Place your source PDF files here.
- **`main.py`**: The core script handling extraction, API communication, and database operations.
- **`batch_input_pg.jsonl`**: (Generated) Temporary JSONL file used for OpenAI Batch submission.
- **`current_batch_id.txt`**: (Generated) Stores the active Batch ID for tracking status.
- **`.env`**: Configuration file for API keys and database credentials.

## Setup and Installation

This project uses **uv** for Python package management.

### 1. Install uv

**Windows (PowerShell):**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS/Linux:**
```bash
curl -lsSf https://astral.sh/uv/install.sh | sh
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory and configure your credentials:

```env
# OpenAI
OPENAI_API_KEY=your_openai_api_key_here

# PostgreSQL Database
DB_HOST=localhost
DB_NAME=postgres
DB_USER=postgres
DB_PASS=password
```

### 3. Install Dependencies

Sync the project dependencies:

```bash
uv sync
```

## How to Run

Run the script using `uv run`:

```bash
uv run main.py
```

### Main Menu Options

The script provides an interactive CLI with three modes:

1.  **Submit Only (Send Job)**
    -   Scans `input_pdfs/`.
    -   Extracts text and filters out files already in the DB.
    -   Creates a batch file and submits it to OpenAI.
    -   Saves the Batch ID to `current_batch_id.txt`.

2.  **Check & Save (Receive Job)**
    -   Reads the Batch ID from `current_batch_id.txt`.
    -   Checks the job status with OpenAI.
    -   If `completed`, downloads the results and inserts them into the database (`batch_data.batch_json`).

3.  **Auto Pilot**
    -   Combines both steps.
    -   Submits the job and enters a loop (polling every 2 minutes).
    -   Automatically downloads and saves results when the job finishes.

## Database Schema

The script automatically initializes the schema if it doesn't exist:

```sql
CREATE SCHEMA IF NOT EXISTS batch_data;

CREATE TABLE IF NOT EXISTS batch_data.batch_json(
    project_id varchar(255) primary key not null, -- derived from filename
    json jsonb,                                   -- extracted data
    created_at timestamp not null default current_timestamp
);
```
