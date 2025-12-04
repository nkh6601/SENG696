# Implementation Plan: PySimpleGUI Interface Agent for D&D MAS

## Executive Summary

Create a Python class (`InterfaceAgent`) using PySimpleGUI that controls the GUI component for the D&D Multi-Agent System. The interface runs in the main thread while HostFlow executes in a background thread, with bidirectional blocking communication for user input collection and narrative display.

**Key Design Decisions**:
- **Threading Model**: HostFlow runs in background thread, GUI blocks main thread
- **Blocking Pattern**: GUI waits for flow at specific interaction points (difficulty check, prompt input)
- **Display Format**: Simple chatbot with speaker labels (Narrator/Player/NPC names)
- **Dependencies**: MongoDB connection check on startup
- **Persistence**: In-memory only (lost on shutdown)

## Research Findings

### From Codebase Exploration

**Current Flow Integration Points**:
1. **Input Collection** (Step 1): `HostState.prompt_text` - User's action prompt
2. **Difficulty Display** (Step 4): `HostState.Action_difficulty` - DC from Judge
3. **Difficulty Check** (Step 5): `HostState.difficulty_check` - d20 roll result (currently auto-rolled at line 193)
4. **Narrative Output** (Step 11): `HostState.final_output` - Main narrative text

**HostFlow is Blocking/Synchronous**:
- `flow.kickoff()` blocks until all 11 steps complete (~30+ seconds with LLM calls)
- Each crew.kickoff() is synchronous (MongoDB vector search + LLM)
- `flow_complete` flag stops flow after Step 11 (line 330)

**Two Blocking Points Identified**:
1. **Step 4 → Step 5 Transition**: Display difficulty, wait for user decision (proceed or cancel)
2. **Step 11 → Next Loop**: Display narrative, wait for next prompt

### From PySimpleGUI Research

**Threading Pattern** ([PySimpleGUI Multi-threading Docs](https://docs.pysimplegui.com/en/latest/documentation/module/multithreading/)):
- GUI must run in main thread (tkinter restriction)
- Background work in separate thread
- Use `window.write_event_value()` to send data from thread to GUI
- Use `threading.Event` or `queue.Queue` for GUI → thread communication

**Key Constraint**: Cannot make GUI calls from background thread except `write_event_value()`

## Architecture

### Component Structure

```
┌─────────────────────────────────────────────────────────┐
│                     Main Thread                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │          InterfaceAgent (PySimpleGUI)             │  │
│  │  • window.read() event loop                       │  │
│  │  • Display conversation history                   │  │
│  │  • Collect user input (prompts, decisions)        │  │
│  │  • Show game state (HP, location, difficulty)     │  │
│  ├───────────────────────────────────────────────────┤  │
│  │           Processor Component                      │  │
│  │  • Conversation history (List[ConversationEntry]) │  │
│  │  • Game state tracking (HP, venue, stage)         │  │
│  │  • Thread coordination (queues, events)           │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ↕
              (Queues + threading.Event)
                         ↕
┌─────────────────────────────────────────────────────────┐
│                  Background Thread                       │
│  ┌───────────────────────────────────────────────────┐  │
│  │         HostFlow Execution Wrapper                │  │
│  │  • Create HostFlow instance                       │  │
│  │  • Set initial state from queues                  │  │
│  │  • Call flow.kickoff()                            │  │
│  │  • Extract result state                           │  │
│  │  • Send updates via window.write_event_value()    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Data Structures

**ConversationEntry** (Pydantic model):
```python
class ConversationEntry(BaseModel):
    speaker: str  # "Narrator", "Player", NPC name
    text: str
    timestamp: str
    entry_type: str  # "narrative", "prompt", "system", "difficulty", "roll"
```

**InterfaceState** (internal to InterfaceAgent):
```python
class InterfaceState(BaseModel):
    # Game state
    campaign: str = "Humantown"
    player: str = "Adventurer"
    player_class: str = "Fighter"
    character_hp: int = 20
    character_max_hp: int = 20
    current_stage: str = ""
    current_venue: str = ""

    # Conversation
    conversation_history: List[ConversationEntry] = []

    # Thread coordination
    flow_running: bool = False
    awaiting_difficulty_decision: bool = False
    current_difficulty: Optional[int] = None
```

### Threading Communication Pattern

**GUI → Flow Thread**:
- `prompt_queue: queue.Queue()` - User prompts
- `decision_queue: queue.Queue()` - Difficulty check decisions (True/False/rewrite)
- `shutdown_event: threading.Event()` - Graceful shutdown signal

**Flow Thread → GUI**:
- `window.write_event_value('-FLOW-UPDATE-', data)` - Flow state updates
- `window.write_event_value('-AWAIT-DECISION-', difficulty)` - Request difficulty decision
- `window.write_event_value('-FLOW-COMPLETE-', final_output)` - Narrative ready
- `window.write_event_value('-FLOW-ERROR-', error_msg)` - Error handling

## Implementation Details

### File Structure

```
src/dnd_mas_host/
├── interface/
│   ├── __init__.py
│   ├── interface_agent.py      # Main InterfaceAgent class
│   ├── models.py                # ConversationEntry, InterfaceState
│   └── layout.py                # PySimpleGUI layout definition
└── main.py                      # Modified for GUI integration
```

### InterfaceAgent Class

**File**: `src/dnd_mas_host/interface/interface_agent.py`

```python
import queue
import threading
from typing import Optional, List
import PySimpleGUI as sg
from pydantic import BaseModel, Field

from dnd_mas_host.interface.models import ConversationEntry, InterfaceState
from dnd_mas_host.interface.layout import create_layout
from dnd_mas_host.main import HostFlow


class InterfaceAgent:
    """
    Interface Agent - GUI component for D&D MAS.

    Architecture:
    - Listener: PySimpleGUI event loop (main thread)
    - Processor: Conversation history, game state, thread coordination
    - No Reasoning LLM (pure interface component)

    Threading:
    - Main thread: GUI event loop (window.read())
    - Background thread: HostFlow execution
    - Communication: Queues + window.write_event_value()
    """

    def __init__(self):
        self.state = InterfaceState()

        # Thread coordination
        self.prompt_queue = queue.Queue()
        self.decision_queue = queue.Queue()
        self.shutdown_event = threading.Event()
        self.flow_thread: Optional[threading.Thread] = None

        # GUI components
        self.window: Optional[sg.Window] = None

    def check_mongodb_connection(self) -> bool:
        """Check MongoDB is running before starting GUI"""
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure

        try:
            client = MongoClient(
                "mongodb://127.0.0.1:27017/",
                serverSelectionTimeoutMS=5000
            )
            client.admin.command('ping')
            return True
        except ConnectionFailure:
            return False

    def start(self):
        """Main entry point - start GUI and game loop"""
        # Check MongoDB
        if not self.check_mongodb_connection():
            sg.popup_error(
                "MongoDB Connection Error",
                "Cannot connect to MongoDB at mongodb://127.0.0.1:27017/",
                "Please ensure MongoDB is running in Docker Desktop."
            )
            return

        # Create window
        self.window = sg.Window(
            f"D&D MAS - {self.state.campaign}",
            create_layout(),
            finalize=True,
            resizable=True
        )

        # Display welcome message
        self._add_to_conversation("Narrator", "Welcome to Humantown...", "narrative")
        self._update_conversation_display()

        # Start event loop
        self._event_loop()

    def _event_loop(self):
        """Main GUI event loop (runs in main thread)"""
        while True:
            event, values = self.window.read()

            if event == sg.WIN_CLOSED or event == 'Exit':
                self._shutdown()
                break

            elif event == '-SUBMIT-PROMPT-':
                self._handle_prompt_submit(values['-PROMPT-INPUT-'])

            elif event == '-PROCEED-CHECK-':
                self._handle_difficulty_decision(True)

            elif event == '-CANCEL-CHECK-':
                self._handle_difficulty_decision(False)

            elif event == '-FLOW-UPDATE-':
                self._handle_flow_update(values[event])

            elif event == '-AWAIT-DECISION-':
                self._handle_await_decision(values[event])

            elif event == '-FLOW-COMPLETE-':
                self._handle_flow_complete(values[event])

            elif event == '-FLOW-ERROR-':
                self._handle_flow_error(values[event])

    def _handle_prompt_submit(self, prompt_text: str):
        """User submitted a prompt"""
        if not prompt_text.strip():
            return

        # Add to conversation
        self._add_to_conversation("Player", prompt_text, "prompt")
        self._update_conversation_display()

        # Clear input
        self.window['-PROMPT-INPUT-'].update('')

        # Disable input while flow runs
        self.window['-PROMPT-INPUT-'].update(disabled=True)
        self.window['-SUBMIT-PROMPT-'].update(disabled=True)

        # Start flow in background thread
        self.state.flow_running = True
        self.flow_thread = threading.Thread(
            target=self._run_flow_thread,
            args=(prompt_text,),
            daemon=True
        )
        self.flow_thread.start()

    def _run_flow_thread(self, prompt_text: str):
        """Execute HostFlow in background thread"""
        try:
            # Create flow instance
            flow = HostFlow()

            # Set initial state
            flow.state.prompt_text = prompt_text
            flow.state.current_venue = self.state.current_venue
            flow.state.current_stage = self.state.current_stage
            flow.state.campaign = self.state.campaign
            flow.state.player = self.state.player
            flow.state.player_class = self.state.player_class
            flow.state.character_hp = self.state.character_hp
            flow.state.character_max_hp = self.state.character_max_hp

            # MODIFIED FLOW EXECUTION:
            # We need to intercept at Step 4→5 transition to get user input
            # This requires modifying HostFlow.perform_check() to read from queue

            # Run flow (blocks until complete or awaiting input)
            result = flow.kickoff()

            # Extract final state
            self.window.write_event_value('-FLOW-COMPLETE-', {
                'final_output': flow.state.final_output,
                'character_hp': flow.state.character_hp,
                'current_venue': flow.state.current_venue,
                'current_stage': flow.state.current_stage,
                'npc_reactions': flow.state.npc_reactions_completed
            })

        except Exception as e:
            self.window.write_event_value('-FLOW-ERROR-', str(e))

    def _handle_await_decision(self, data: dict):
        """Flow is waiting for difficulty check decision"""
        difficulty = data['difficulty']

        # Display difficulty to user
        self._add_to_conversation(
            "System",
            f"Difficulty Check Required: DC {difficulty}",
            "difficulty"
        )
        self._update_conversation_display()

        # Show decision buttons
        self.state.awaiting_difficulty_decision = True
        self.state.current_difficulty = difficulty
        self.window['-DIFFICULTY-PANEL-'].update(visible=True)
        self.window['-DIFFICULTY-TEXT-'].update(f"DC {difficulty}")

    def _handle_difficulty_decision(self, proceed: bool):
        """User decided on difficulty check"""
        if not self.state.awaiting_difficulty_decision:
            return

        # Hide decision panel
        self.window['-DIFFICULTY-PANEL-'].update(visible=False)
        self.state.awaiting_difficulty_decision = False

        if proceed:
            # Perform d20 roll
            import random
            roll = random.randint(1, 20)

            # Display roll result
            success = roll >= self.state.current_difficulty
            result_text = f"🎲 You rolled: {roll} (DC {self.state.current_difficulty}) - {'Success!' if success else 'Failed!'}"
            self._add_to_conversation("System", result_text, "roll")
            self._update_conversation_display()

            # Send decision to flow thread
            self.decision_queue.put({'proceed': True, 'roll': roll})
        else:
            # User wants to cancel/rewrite
            self._add_to_conversation("System", "Action cancelled. Please enter a new prompt.", "system")
            self._update_conversation_display()

            # Re-enable input
            self.window['-PROMPT-INPUT-'].update(disabled=False)
            self.window['-SUBMIT-PROMPT-'].update(disabled=False)

            # Signal flow to abort
            self.decision_queue.put({'proceed': False})
            self.state.flow_running = False

    def _handle_flow_complete(self, data: dict):
        """Flow completed - display narrative"""
        # Update game state
        self.state.character_hp = data['character_hp']
        self.state.current_venue = data['current_venue']
        self.state.current_stage = data['current_stage']

        # Display main narrative
        self._add_to_conversation("Narrator", data['final_output'], "narrative")

        # Display NPC reactions
        for reaction in data['npc_reactions']:
            npc_name = reaction['npc_name']
            reaction_text = reaction['reaction']
            self._add_to_conversation(npc_name, reaction_text, "narrative")

        self._update_# r/Beekeeping 2021-09-05 BeeLuv: This cool wax pattern means, what?


Ok-Eggplant-4306: Take this with a grain of salt—just a hunch. Feels like they've created more cell depth because they've got an especially large worker bee.


BeeLuv: Does it imply they are not happy with the foundation and are ignoring it while building something else?

They've drawn all the other frames in the two hive boxes, but not this one.  All the other frames have capped honey on both sides.


bigryanb: Cross comb with no foundation. Will happen when just starting to build.


Humburgerman: Does that frame not have foundation? Looks like they are pulling comb perpendicular to the others. Sometimes happens with a frame without foundation and some variability in how the box is stored. Not a big deal, they will keep going with what they have started usually.


@Humburgerman BeeLuv: The frame has foundation.  They are building this odd wax off the base of the frame, perpendicular to the foundation sheets.  And yes, this is the only frame without comb drawn on both sides of foundation (comb drawn with capped honey, that is) in the entire hive!   Odd little buggers.

So, they will likely just keep this up, and I need to pay attention when doing inspections to avoid squishing too many.  Or should I scrape this strange comb off and not let them build it?


@BeeLuv NumCustosApes: Scrape it off, but note the location.  Then level your hive.  Bees always plumb their comb to gravity.  When they start drawing comb in the wrong direction, off the bottom of a frame, or off of strange places it is usually a sign that the hive is out of level.  However, sometimes they just do weird shit.  Make sure that whatever is under the hive is strong enough to support the hive weight, including the honey weight.  if it is weak then it can settle and then rotate the hive out of level.


@NumCustosApes BeeLuv: Thank you!  I'll go out today and check.


@NumCustosApes BeeLuv: This was it!  The hive is on legs rather than cement blocks, and it is absolutely not level any more.  (Dog used to dig holes by the legs last year, and dug so much it started squirting water out one of the holes…). https://i.imgur.com/p4Pq6zE.jpg

Thank you, thank you!


# (8) 2021-09-11 TrivAndLetDie: Any reason I shouldn't combine these weak hives?


TrivAndLetDie: These are two weak colonies that came up through winter (late spring here in Southern Hemisphere). The first is queenless and has just lost its final batch of brood (and naturally gained some drone layers). The second has a virgin queen that's failed to mate after two weeks of perfect weather. Neither makes it into the centre of a ten frame deep, but together they'd make a solid colony.

At this stage is there any reason I shouldn't unite them? Will they accept an introduced queen, or should I try and raise a new one from a healthy colony? Or am I wasting my time and should cut my losses?


lessthaninteresting: I'm not very experienced but my guess is you wouldn't see them fight the way they probably should since they're both weak. I would try uniting without a newspaper in the middle and see if there's any dead bees lying around tomorrow. If they tolerate each other then they can share and you can introduce a mated queen. Fingers crossed that works out


DCMann2: In my opinion it's not worth trying to save them. Weak hive + weak hive = weak hive. IMO you should start over with a better, healthier stock. If there's no brood except for drone brood I'd kill them and order a package.

If you really want to try and save them you could combine them and see if they'll accept a new queen, but I don't think it'll be worth your time


bigryanb: Your perspective of weak is a great question. Doesn't look bad, but I also am looking through a single lens [camera].

Check if there's any open brood when you move to combine. Remove known dead queens. Just put a single sheet of news paper with holes poked in it, in between the boxes. The box with the best frame to frame coverage, you can put on the bottom. Combine at this time of the year if the hive would be a "normal size box full" with both together.

You may want to wait to evaluate frame coverage, too, if your season is shifting a lot. Just keep the viable hive and freeze the other until you make the determination to combine or not. It won't hurt anything.

If the bees are all old girls, time won't make things any better. I'd combine and get a queen in there quick.


TrivAndLetDie: Update: I united the colonies via newspaper, and they're currently sharing the warmest hive box. After reading through some comments here I took a look through my stocked supers and realized one already had a fresh batch of larva and eggs.

So rather than buying in a queen to gamble on their acceptance, I've given the girls two frames of all stage brood. I'll keep an eye on the frames and hopefully in a few weeks I'll be restocking with a proven queen.

Thanks for the advice everyone!


@DCMann2 TrivAndLetDie: Appreciate the honesty. If they both had existing queens I'd certainly consider this, but with one queenless and the other currently not laying a time/financial analysis seems to give this a chance. I'd be forking out for a queen at this point anyway, but at least a few hundred bees could take pressure off whatever brood pattern she gets started.


@lessthaninteresting ibleedbigred: Or just add a newspaper in the middle and they won't fight at all.


@ibleedbigred lessthaninteresting: That was my point, that they're both weak enough that they'd probably just be happy to have the company


@lessthaninteresting ibleedbigred: I know that's what you said but I'm saying, use newspaper, ensure they get along and the stronger one doesn't just kill all the other bees. Why take the chance?


@TrivAndLetDie NumCustosApes: Can you put a couple of frames of brood from a strong hive into the hive with the virgin queen.  She may be taking longer to develop.  With more bees she'll have a better chance.  It sounds like you have more than just these two hives so the booster will make the weak hives stronger than the sum of two weak hives.


@NumCustosApes TrivAndLetDie: Certainly could give that a try. If I leave them united overnight I assume it'd be easier to introduce a new frame - or are the acceptance rates pretty similar?


# How to Compile and Install an OpenMP-Enabled OpenCV-4.5.1.tar.gz on a Linux Device

## 1. Introduction

### 1.1. Introduction

**OpenCV**, which stands for Open Source Computer Vision, is a [library](https://en.wikipedia.org/wiki/Library_%28computer_science%29) of [programming functions](https://en.wikipedia.org/wiki/Subroutine) mainly aimed at real-time [computer vision](https://en.wikipedia.org/wiki/Computer_vision). OpenCV was initially developed by [Intel](https://en.wikipedia.org/wiki/Intel), and was later supported by [Willow Garage](https://en.wikipedia.org/wiki/Willow_Garage) and [Itseez](https://en.wikipedia.org/wiki/Itseez). The library is [cross-platform](https://en.wikipedia.org/wiki/Cross-platform_software) and [free for use](https://en.wikipedia.org/wiki/Free_and_open-source_software) under the [open-source](https://en.wikipedia.org/wiki/Free_software) [Apache 2 License](https://en.wikipedia.org/wiki/Apache_License). Starting with 2011, OpenCV features [GPU](https://en.wikipedia.org/wiki/GPU) [acceleration](https://en.wikipedia.org/wiki/Hardware_acceleration) for real-time operations.
> From [OpenCV From Wikipedia](https://en.wikipedia.org/wiki/OpenCV)
>
> OpenCV official website: [https://opencv.org](https://opencv.org/)

**OpenMP** (Open Multi-Processing) is an [application programming interface](https://en.wikipedia.org/wiki/Application_programming_interface) (API) that supports [multi-platform](https://en.wikipedia.org/wiki/Multi-platform) [shared memory](https://en.wikipedia.org/wiki/Shared_memory) [multiprocessing](https://en.wikipedia.org/wiki/Multiprocessing) [programming](https://en.wikipedia.org/wiki/Programming_model) in [C](https://en.wikipedia.org/wiki/C_%28programming_language%29), [C++](https://en.wikipedia.org/wiki/C%2B%2B), and [Fortran](https://en.wikipedia.org/wiki/Fortran), on most [platforms](https://en.wikipedia.org/wiki/Computing_platform), [instruction set architectures](https://en.wikipedia.org/wiki/Instruction_set_architecture) and [operating systems](https://en.wikipedia.org/wiki/Operating_system), including [Solaris](https://en.wikipedia.org/wiki/Oracle_Solaris), [AIX](https://en.wikipedia.org/wiki/IBM_AIX), [HP-UX](https://en.wikipedia.org/wiki/HP-UX), [Linux](https://en.wikipedia.org/wiki/Linux), [macOS](https://en.wikipedia.org/wiki/MacOS), and [Windows](https://en.wikipedia.org/wiki/Microsoft_Windows). It consists of a set of [compiler directives](https://en.wikipedia.org/wiki/Directive_%28programming%29), library routines, and [environment variables](https://en.wikipedia.org/wiki/Environment_variable) that influence run-time behavior.
> From [OpenMP From Wikipedia](https://en.wikipedia.org/wiki/OpenMP)

| Versoin | Year | C/C++ Support           |
| ----    | ---- | -----------             |
| 1.0     | 1997 | [Fortran Support](https://www.openmp.org/specifications/)|
| 2.0     | 2000 | [Fortran Support](https://www.openmp.org/specifications/)|
| 2.5     | 2005 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 3.0     | 2008 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 3.1     | 2011 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 4.0     | 2013 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 4.5     | 2015 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 5.0     | 2018 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 5.1     | 2020 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |
| 5.2     | 2021 | [C/C++ & Fortran Support](https://www.openmp.org/specifications/) |

> OpenMP official website: [https://www.openmp.org](https://www.openmp.org/)

### 1.2. Reason to build OpenCV-4.5.1 with OpenMP and GTK for GUI support with Ubuntu 18.04.4 LTS

While I was on a project about  [Haar Cascade Face Detection OpenCV](https://docs.opencv.org/3.4/db/d28/tutorial_cascade_classifier.html) on `Ubuntu 18.04` with `OpenCV 4.5.1` (OpenCV 4.5.1 From Source Code) which I installed by following this page [How to install OpenCV 4.5.1](https://docs.opencv.org/4.5.1/d7/d9f/tutorial_linux_install.html), I found that `cv2.imshow()` did not work well. So I searched online, I found a post: [GTK+2.x toolkit has been deprecated when compile OpenCV4.0.0 from source #13681](https://github.com/opencv/opencv/issues/13681).

After I read comments from [alalek](https://github.com/alalek), I found that this problem is because there are many graphics subsystem backends supported by `OpenCV`, but the suggested UI backend is `Qt5`.

Additionally `Haar Face Detection` was running slow, so I searched online, I found this [Multithreaded face detection with OpenCV and Python](https://medium.com/analytics-vidhya/multithreaded-face-detection-with-opencv-and-python-c7c850f37dab) and this [Multi-Threading and Parallel Programming With OpenMP 4.5](https://www.labri.fr/perso/eyraud/pmwiki/uploads/Teaching/3-OpenMP.pdf). By following the tutorial from [Multi-Threading and Parallel Programming With OpenMP 4.5](https://www.labri.fr/perso/eyraud/pmwiki/uploads/Teaching/3-OpenMP.pdf), I enabled the OpenMP support for `OpenCV 4.5.1` on `Ubuntu 18.04`.

## 2. The Result

| Video Resolution | Before OpenMP + Qt5 support | After Openmp + Qt5 support|
| ----             | ----                        | ---- |
| 1280 x 720       | **18 FPS**                  | **28 FPS** |

## 3. Requirements

- Device: Linux, Intel or AMD CPU Devices
- OS: Ubuntu 18.04.4 LTS

## 4. Environment

| Item     |  Value     |
| ----     | ----       |
| Device   | Oracle VM VirtualBox |
| OS       | Ubuntu 18.04.4 LTS |
| Compiler | gcc (Ubuntu 7.5.0-3ubuntu1~18.04) 7.5.0 |
| OpenCV   | 4.5.1 |
| Python   | 3.8.5 |

**Compiling from Source requires `g++` >= 4.9 or `clang` >=  3.4**

## 5. Prerequisite

- Understand [GNU make (ref manual)](https://www.gnu.org/software/make/manual/make.html)
- Understand [CMake Tutorial](https://cmake.org/cmake/help/latest/guide/tutorial/index.html)
- [How to use Docker](https://docs.docker.com/engine/reference/run/)

I used VirtualBox to create an Ubuntu 18.04.4 LTS Environment.

Here are the steps:

## 6. Make a Build Fodler

```Bash
# Navigate to OpenCV source code folder
cd ${HOME}/opencv-4.5.1

# Make a Build Folder under OpenCV source code folder
mkdir build
cd build
```

## 7. Decide Build Options

Below are my build options, please change based on your device:

```Bash
# cmake options
CMAKE_OPTIONS='-D BUILD_TIFF=ON
            -D WITH_CUDA=OFF
            -D ENABLE_AVX=OFF
            -D WITH_OPENGL=OFF
            -D WITH_OPENCL=OFF
            -D WITH_IPP=OFF
            -D WITH_TBB=ON
            -D WITH_EIGEN=ON
            -D WITH_V4L=OFF
            -D WITH_VTK=OFF
            -D BUILD_TESTS=OFF
            -D BUILD_PERF_TESTS=OFF
            -D OPENCV_GENERATE_PKGCONFIG=ON
            -D CMAKE_BUILD_TYPE=RELEASE
            -D CMAKE_INSTALL_PREFIX=/usr/local
            -D PYTHON2_PACKAGES_PATH=/lib/python2.7/dist-packages
            -D PYTHON3_PACKAGES_PATH=/lib/python3/dist-packages
            -D OPENCV_EXTRA_MODULES_PATH=${HOME}/opencv_contrib-4.5.1/modules
            -D WITH_QT=ON
            -D WITH_OPENMP=ON'
# make options (change based your device)
BUILD_THREAD='4'
```

| Item                          | Description                              |
| ----                          | ----                                     |
| `${HOME}/opencv-4.5.1`        | OpenCV-4.5.1 source code path            |
| `${HOME}/opencv_contrib-4.5.1/modules` | OpenCV-4.5.1 contrib folder    |
| `BUILD_TIFF=ON`               | Only build `.tiff` (This is optional)    |
| `WITH_CUDA=OFF`               | Because my device does not support CUDA, so I set it off. |
| `ENABLE_AVX=OFF`              | Because my VM does not support AVX, so I set it off.  |
| `WITH_OPENGL=OFF`             | Because my VM does not support OpenGL, so I set it off.  |
| `WITH_OPENCL=OFF`             | Because my VM does not support OpenCL, so I set it off.  |
| `WITH_IPP=OFF`                | Because my VM does not support IPP, so I set it off.  |
| `WITH_TBB=ON`                 | Turn on the TBB support  |
| `WITH_EIGEN=ON`               | Turn on the EIGEN support |
| `WITH_V4L=OFF`                | Because my VM does not support V4L, so I set it off. |
| `WITH_VTK=OFF`                | This is optional, I don't use VTK, so I set it off. |
| `BUILD_TESTS=OFF`             | Turn off all OpenCV tests while building the source code. (This will reduce the building time)|
| `BUILD_PERF_TESTS=OFF`        | Turn off all Perf tests while building the source code. (This will reduce the building time)|
| `OPENCV_GENERATE_PKGCONFIG=ON`| Generating .pc file, so you can use `pkg-config` to add the OpenCV library to C/C++ project |
| `CMAKE_BUILD_TYPE=RELEASE`    | Builing Release version of OpenCV library     |
| `CMAKE_INSTALL_PREFIX=/usr/local` | Installing OpenCV to `/usr/local` |
| `PYTHON2_PACKAGES_PATH=/lib/python2.7/dist-packages` | Python 2.7 library installation path |
| `PYTHON3_PACKAGES_PATH=/lib/python3/dist-packages` | Python 3 library installation path |
| `OPENCV_EXTRA_MODULES_PATH=${HOME}/opencv_contrib-4.5.1/modules` | OpenCV-4.5.1 contrib folder |
| `WITH_QT=ON` | Build with Qt support [Tutorial](http://eric-yuan.me/qt-opencv-highgui/) |
| `WITH_OPENMP=ON` | Build with OpenMP support |
| `BUILD_THREAD='4'` | This is a number for `make -j <Number>`, it is a number based on your device CPU threads. It is the number to let the `make` command to use how many concurrent jobs. In my VM, I have 4 threads, so I set it to 4 here. |

> Note:
>
> I added these two paths **PYTHON2_PACKAGES_PATH** and **PYTHON3_PACKAGES_PATH** because I have two Python Versions (2.7 and 3.8.5) in my VM. So the installed binary files **cv2.cpython.so** (build from Python 3) and **cv2.so** (build from Python 2.7) from `OpenCV 4.5.1` can be installed to different locations.
>
> As to **BUILD_THREAD='4'**, you can get this value by running this command `grep -c ^processor /proc/cpuinfo`.
>
> The `pkg-config` only works when you have the `OPENCV_GENERATE_PKGCONFIG=ON` for cmake building option (see `cmake` options above). For more information, check out [How to get OpenCV info with pkg-config: Tutorial](https://www.learnopencv.com/how-to-use-opencv-with-gcc-in-c-or-cpp/)

**About CMake Build Options**

The CMake build options are case insensitive and can be found in the OpenCV source code folder.

For example, here's a CMake option `WITH_OPENMP`:

```Shell
# Search STRING "OPENMP" under this directory - pwd = ${HOME}/opencv-4.5.1
grep --color -rnis --context=3 "WITH_OPENMP" .
```

These options are all under [`./CMakeLists.txt`](https://github.com/opencv/opencv/blob/master/CMakeLists.txt):

```Shell
--
8-#    https://github.com/opencv/opencv/wiki/How_to_contribute#making-a-good-pull-request
9-#
10-# For bugs and feature requests visit the tracker:
11-#    https://github.com/opencv/opencv/issues
12-#
13-# ============================================================================== =
14-
15:# Search packages for host system instead of packages for target system
16-# in case of cross compilation these macro should be defined by toolchain file
17-if(NOT COMMAND find_host_package)
18-  macro(find_host_package)
19-    find_package(${ARGN})
20-  endmacro()
--
92-
93-# Save libs and executables in the same place
94-set(EXECUTABLE_OUTPUT_PATH "${CMAKE_BINARY_DIR}/bin" CACHE PATH "Output directory for applications" )
95-
96-if(ANDROID OR APPLE_FRAMEWORK)
97-  set(OPENCV_DOC_INSTALL_PATH doc)
98-else()
99:  set(OPENCV_DOC_INSTALL_PATH share/doc/opencv4)
100-endif()
101-
102-
103-# ----------------------------------------------------------------------------
104-# Path for additional modules
105-# ----------------------------------------------------------------------------
--
164-
165-OCV_OPTION(BUILD_JAVA                "Build Java support"                               (ANDROID OR NOT ANDROID_EXECUTABLE) IF (ANDROID OR NOT WINRT) )
166-OCV_OPTION(BUILD_OBJC                "Build Objective-C support"                        ON IF APPLE_FRAMEWORK )
167-OCV_OPTION(BUILD_FAT_JAVA_LIB        "Create fat java wrapper containing the core and contrib modules" ON  IF (NOT BUILD_SHARED_LIBS AND CMAKE_COMPILER_IS_GNUCXX AND BUILD_JAVA AND OPENCV_EXTRA_MODULES_PATH) )
168-OCV_OPTION(BUILD_opencv_python2      "Build Python 2.x bindings"                        (NOT WINRT) IF (PYTHONINTERP_FOUND OR PYTHON_DEFAULT_AVAILABLE OR PYTHON2_FOUND OR PYTHON2_EXECUTABLE) )
169-OCV_OPTION(BUILD_opencv_python3      "Build Python 3.x bindings"                        (NOT WINRT) IF (PYTHONINTERP_FOUND OR PYTHON_DEFAULT_AVAILABLE OR PYTHON3_FOUND OR PYTHON3_EXECUTABLE) )
170-
171:OCV_OPTION(BUILD_ANDROID_EXAMPLES    "Build examples for Android platform"              ON  IF ANDROID )
172-OCV_OPTION(BUILD_DOCS                "Create build rules for OpenCV Documentation"      ON )
173-OCV_OPTION(BUILD_EXAMPLES            "Build all examples"                               OFF )
174-OCV_OPTION(BUILD_PACKAGE             "Enables 'make package_source' command"            ON )
175-OCV_OPTION(BUILD_PERF_TESTS          "Build performance tests"                          ON  IF (NOT IOS) )
176-OCV_OPTION(BUILD_TESTS               "Build accuracy & regression tests"                ON  IF (NOT IOS) )
--
243-OCV_OPTION(WITH_GSTREAMER            "Include Gstreamer support"                        ON  IF (UNIX AND NOT APPLE AND NOT ANDROID AND NOT IOS AND NOT WINRT) )
244-OCV_OPTION(WITH_GSTREAMER_0_10       "Enable Gstreamer 0.10 support (instead of 1.x)"   OFF )
245-OCV_OPTION(WITH_GTK                  "Include GTK support"                              ON  IF (UNIX AND NOT APPLE AND NOT ANDROID AND NOT IOS) )
246-OCV_OPTION(WITH_GTK_2_X              "Use GTK version 2"                                OFF IF (UNIX AND NOT APPLE AND NOT ANDROID AND NOT IOS) )
247-OCV_OPTION(WITH_IPP                  "Include Intel IPP support"                        (NOT MINGW) IF (X86_64 OR X86) AND NOT WINRT AND NOT APPLE_FRAMEWORK AND NOT ARM_LINUX )
248-OCV_OPTION(WITH_HALIDE               "Include Halide support"                           OFF )
249-OCV_OPTION(WITH_VULKAN               "Include Vulkan support"                           OFF )
250:OCV_OPTION(WITH_INF_ENGINE           "Include Intel Inference Engine support"           OFF )
251-OCV_OPTION(WITH_NGRAPH               "Include Intel nGraph support"                     OFF )
252-OCV_OPTION(WITH_JASPER               "Include JPEG2K support (Jasper)"                  OFF ) # see #16494
253-OCV_OPTION(WITH_OPENJPEG             "Include JPEG2K support (OpenJPEG)"                ON  IF (NOT IOS) )
254-OCV_OPTION(WITH_JPEG                 "Include JPEG support"                             ON)
255-OCV_OPTION(WITH_WEBP                 "Include WebP support"                             ON  IF (NOT IOS) )
256-OCV_OPTION(WITH_OPENEXR              "Include ILM support via OpenEXR"                  ON  IF (NOT IOS) )
257:OCV_OPTION(WITH_OPENVX               "Include OpenVX support"                           OFF )
258-OCV_OPTION(WITH_OPENNI               "Include OpenNI support"                           OFF IF (NOT ANDROID AND NOT IOS AND NOT WINRT) )
259-OCV_OPTION(WITH_OPENNI2              "Include OpenNI2 support"                          OFF IF (NOT ANDROID AND NOT IOS AND NOT WINRT) )
260-OCV_OPTION(WITH_LIBREALSENSE         "Include Intel RealSense support"                  OFF IF (NOT ANDROID AND NOT IOS AND NOT WINRT) )
261-OCV_OPTION(WITH_PVAPI                "Include Prosilica GigE support"                   OFF IF (NOT ANDROID AND NOT IOS AND NOT WINRT) )
262-OCV_OPTION(WITH_ARAVIS               "Include Aravis GigE support"                      OFF IF (UNIX AND NOT ANDROID AND NOT IOS) )
263-OCV_OPTION(WITH_AVFOUNDATION         "Use AVFoundation for Video I/O (iOS/visionOS/Mac)" ON  IF APPLE )
264:OCV_OPTION(WITH_GIGEAPI              "Include Smartek GigE support"                     OFF IF (NOT ANDROID AND NOT IOS) )
265-OCV_OPTION(WITH_MFX                  "Include Intel Media SDK support"                  OFF IF (UNIX AND NOT ANDROID) )
266-OCV_OPTION(WITH_GPHOTO2              "Include gPhoto2 library support"                  ON  IF (UNIX AND NOT ANDROID) )
267-OCV_OPTION(WITH_LAPACK               "Include Lapack library support"                   (NOT CMAKE_CROSSCOMPILING AND NOT APPLE_FRAMEWORK) IF (NOT IOS) )
268-OCV_OPTION(WITH_ITT                  "Include Intel ITT support"                        ON  IF (NOT APPLE_FRAMEWORK) )
269-OCV_OPTION(WITH_PROTOBUF             "Enable libprotobuf"                               ON)
270-OCV_OPTION(WITH_IMGCODEC_HDR         "Include HDR support"                              ON )
--
270-OCV_OPTION(WITH_IMGCODEC_HDR         "Include HDR support"                              ON )
271-OCV_OPTION(WITH_IMGCODEC_SUNRASTER   "Include SUNRASTER support"                        ON )
272-OCV_OPTION(WITH_IMGCODEC_PXM         "Include PNM (PBM,PGM,PPM) and PAM formats support" ON )
273-OCV_OPTION(WITH_IMGCODEC_PFM         "Include PFM formats support"                      ON )
274-OCV_OPTION(WITH_QUIRC                "Include library QR-code decoding"                 ON )
275