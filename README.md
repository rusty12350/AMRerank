
---

# [AMRerank]

A project for library migration.

## Directory Structure

- `IRF/`: Contains source code for the Interpretable Framework.
    
- `MultiAgent/`: Contains source code for the Multi-Agent System.
    
- `Result/`: Stores the output results from the **AMRerank** model.
    
- `Result(+label)/`: Stores the output results from the **AMRerank'** model.
    
- `libWithResult/`: Contains processed library data where original names are transformed for compatibility.
    
    - File naming convention: `.` is replaced with `_`, and `:` is replaced with `__`.
        
    - The `biref_description` file within this directory serves as the library profile.
        
    - Files named after a library contain the results from the research team.
        

---

## Setup & Installation

1. **Prerequisites**:
    
    - **Python `3.12`** or higher is recommended.
        
    - This project uses `uv` for package management.
        
2. Install Dependencies:
    
    The project dependencies are managed by pyproject.toml and uv.lock. Use the following command to install them:
    
    Bash
    
    ```
    uv sync
    ```
    
3. Configuration:
    
    You must configure the environment variables and settings locally.
    
    - Create the environment file: `cp .env.example .env` and then fill in your credentials in the `.env` file.
        
    - Create the configuration file: `cp conf.yaml.example conf.yaml` and adjust settings in the `conf.yaml` file as needed.
        

---

## Usage

Bash

```
# Example command to run the main script
python main.py 
```