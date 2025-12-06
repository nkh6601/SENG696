
## Prerequisites

### Required Software

1. **Python**: Version ≥3.10, <3.14
   - Download from [python.org](https://www.python.org/downloads/)

2. **MongoDB**: Version 6.0 or higher
   - Download from [mongodb.com](https://www.mongodb.com/try/download/community)
   - **Important**: MongoDB must be running before starting the application

3. **Git** (optional, for cloning):
   - Download from [git-scm.com](https://git-scm.com/downloads)

### API Keys

- **OpenAI API Key**: Required for LLM inference
  - Get your key from [platform.openai.com](https://platform.openai.com/api-keys)

---

## Installation

### Step 1: Clone or Download the Repository

```bash
git clone <repository-url>
cd dnd_mas_host
```

Or download and extract the ZIP file.

### Step 2: Install UV (Python Package Manager)

```bash
pip install uv
```

### Step 3: Install Dependencies

Navigate to the project directory and install all dependencies:

```bash
cd .\SENG696\dnd_mas_host
crewai install
```

Or manually with UV:

```bash
uv pip install -r requirements.txt
```

### Step 4: Install Additional Dependencies

Install PySimpleGUI and MongoDB driver:

```bash
pip install PySimpleGUI pymongo sentence-transformers
```
### Step 5: Restore the docker container

Go to .\SENG696\mongodb3, and unzip the mongodb-complete-20251205_232602.rar

Running the docker desktop, and execute the restore.ps1 script. The script should be teh same folder with the images.

```powershell
.\restore.ps1
```


## License

[Specify your license here]

---

## Credits

- **CrewAI Framework**: [crewai.com](https://crewai.com)
- **D&D 5E SRD**: [5e-bits/5e-database](https://github.com/5e-bits/5e-database)
- **Campaign Design**: Custom "Humantown: Rescue from the Town of Slimes"

---

**Ready to adventure? Run the application and start your journey!**

```bash
python -m dnd_mas_host.interface
```
