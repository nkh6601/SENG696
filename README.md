
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
### Step 6: Adding API key to the .env file

Go to .\SENG696\dnd_mas_host, and modify the openapi field to allow API call. Other models should work, but they have not been tested.

OPENAI_API_KEY=xxxxxx

---

## Credits

- **CrewAI Framework**: [crewai.com](https://crewai.com)
- **D&D 5E SRD**: [5e-bits/5e-database](https://github.com/5e-bits/5e-database)
- **Campaign Design**: Custom "Humantown: Rescue from the Town of Slimes"

## Remark

- This project uses Claude Code in the implementation, especially for the overall flow.

## License
Below is the legal information of the Dungeon and Dragon System Reference Document:
Legal Information
The System Reference Document 5.2.1 (“SRD 5.2.1”) is provided to you free of charge by Wizards
of the Coast LLC (“Wizards”) under the terms of the Creative Commons Attribution 4.0
International License (“CC-BY-4.0”). You are free to use the content in this document in any
manner permitted under CC-BY-4.0, provided that you include the following attribution statement
in any of your work: This work includes material from the System Reference Document 5.2.1 (“SRD
5.2.1”) by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1
is licensed under the Creative Commons Attribution 4.0 International License, available at
https://creativecommons.org/licenses/by/4.0/ legalcode. Please do not include any other
attribution to Wizards or its parent or a􀆯iliates other than that provided above. You may, however,
include a statement on your work indicating that it is “compatible with fifth edition” or “5E
compatible.” Section 5 of CC-BY-4.0 includes a Disclaimer of Warranties and Limitation of Liability
that limits our liability to you.
Below is the legal information of the https://github.com/5e-bits/5e-database:
MIT License
Copyright (c) [2018-2020] [Adrian Padua, Christopher Ward]
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN
AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

**Ready to adventure? Run the application and start your journey!**

```bash
python -m dnd_mas_host.interface
```
