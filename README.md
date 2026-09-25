# Show Available Quests (SAQ)

Nexus Mods page: https://www.nexusmods.com/starfield/mods/18315

An [SFSE](https://sfse.silverlock.org/) plugin for **Starfield** that adds an **"Available Quests"** tab to the vanilla mission menu.

Vanilla Starfield never tells you where a quest can be picked up: you have to run into the quest giver,
walk up to a mission board, or trigger an event by accident - and quests you have not accepted yet are
not shown anywhere. This mod closes that gap. It lists every non-main quest (side / faction / activity /
event) that is still available at your current progress and integrates with the game's native tracking
and guidance, so you can select an entry, track it, and follow the HUD marker / scanner route line to
the pickup location.

| | |
| --- | --- |
| Game | Starfield 1.16.244 |
| Requires | SFSE 0.2.21+ (`sfse_1_16_244.dll`) |
| Languages | English / Chinese (other game locales fall back to English) |
| License | GPL-3.0-or-later |

## Features

- Adds an "Available Quests" tab to the vanilla mission menu.
- Lists only quests that can actually be picked up right now - not started, not completed, and all
  known progress conditions satisfied:
  - record-level conditions that reference another quest,
  - dialogue (INFO) conditions, official DLC included,
  - quest-chain gates (a follow-up quest stays hidden until its prerequisite is finished).
- Full guidance integration: selecting an entry starts the native quest guidance (HUD marker +
  scanner route line); SET COURSE (R / X) also opens the star map with the route plotted.
- Radiant ("infinite") quests are not listed, but their pickup points are: 13 mission boards plus
  8 repeatable-job NPCs, each listed as a single navigable entry.
- 24 recruitable crew members are listed as `(Recruitable)` entries; they only appear once they are
  actually recruitable and disappear after you hire them.
- Entries without a usable navigation target are marked `(No navigation)` and their button is greyed
  out instead of failing silently.
- Official content aware: quests from a DLC / Creation you do not own are never listed
  (Shattered Space, Trackers Alliance, Free Lanes, ...).
- Two UI forms: the bundled SWF override, or a built-in injection mode that works on top of a
  vanilla or third-party mission menu (with a structure self-check - if a game update ever changes
  the layout, the feature stays off and the log says why).
- Logging: rolling log file, 1 MB cap by default (configurable), written next to the plugin inside
  the mod folder - nothing is left behind in the user profile.

## Repository layout

| Path | Contents |
| --- | --- |
| `plugin/` | SFSE native plugin: C++23, CommonLibSF, built with xmake |
| `plugin/src/SAQ_QuestTable.h` | Generated static quest table (quests, localized names, types, guide targets) |
| `plugin/src/SAQ_Decision.*` | Pure decision logic, shared by the plugin and the offline tests |
| `plugin/tests/` | Offline unit tests (no game, no CommonLibSF needed) |
| `ui/missionmenu*/` | AS3 sources, vanilla base SWF, and the SWF patch/build flow (FFDec) |
| `scripts/` | Papyrus script (`SAQ_Main.psc`) used by the guidance layer |
| `esm/` | Data plugin (`SAQ_ShowAvailableQuests.esm`): guide aliases and targets |
| `tools/` | Build / deploy / package scripts, quest data pipeline, reverse-engineering tools |
| `resources/` | INI template, player-facing README, Nexus description |
| `docs/` | Development notes (Chinese) |

## Building from source

### 1. Prerequisites

- Windows x64
- [xmake](https://xmake.io) 3.0+
- Visual Studio 2022 or 2026 with the MSVC v143 toolset (C++23)
- Python 3.10+
- Java 8+ (only when rebuilding the SWFs with FFDec)
- Starfield + Creation Kit (only for the data pipeline and the Papyrus compile)
- Mod Organizer 2 (optional, only for automated deployment)

### 2. Third-party dependencies (not committed)

| Dependency | Where it goes | How to get it |
| --- | --- | --- |
| CommonLibSF | `tools/commonlibsf-main/` | `git clone --recurse-submodules https://github.com/libxse/commonlibsf tools/commonlibsf-main` |
| FFDec (JPEXS) 26.3.0 | `tools/ffdec/` | https://github.com/jindrapetrik/jpexs-decompiler/releases |
| xEdit (Starfield build, `xSFEdit64.exe`) | `tools/vendor/xEdit/` | Starfield branch of xEdit |
| Champollion (Orvid fork, v1.3.2) | `tools/champollion/` | https://github.com/Orvid/Champollion/releases |
| Starfield UI AS3 reference | `ref/Interface-main/` | https://github.com/Creation-Hub/Interface |

### 3. Build

```powershell
# Full pipeline: static quest table -> DLL -> SWF -> Papyrus -> deploy to MO2
& ".\tools\build-saq.ps1"

# Native DLL only (uses the committed quest table; no game data required)
& ".\tools\build-saq.ps1" -SkipTable -SkipSwf -SkipPapyrus -SkipDeploy
```

Common switches of `tools/build-saq.ps1`:

| Switch | Meaning |
| --- | --- |
| `-SkipTable` / `-SkipSwf` / `-SkipPlugin` / `-SkipPapyrus` / `-SkipDeploy` | Skip that stage |
| `-RebuildEsm` | Regenerate the ESM with xEdit (~5 minutes) |
| `-Harness` | Dev / self-test build: DLL contains the in-engine test harness, test assets are deployed, INI `[Test] Harness=1` |
| `-Release` | Release build: the harness is compiled out of the DLL entirely |
| `-Only <ids>` | Incremental harness run: only run test cases matching the given id substrings |
| `-AutoLoad <save>` | Harness: auto-load the given save at the main menu |
| `-P2` | Experimental "no SWF override" deployment used for UI testing |

Manual build of the plugin (what the script does under the hood):

```powershell
cd plugin
xmake f -y -p windows -a x64 -m releasedbg --vs=2022
xmake build SAQ_ShowAvailableQuests
# -> plugin/build/windows/x64/releasedbg/SAQ_ShowAvailableQuests.dll
```

**Machine-specific paths**: `tools/build-saq.ps1` defines `$dataDir` (the Starfield `Data` folder,
also used to locate `Tools\Papyrus Compiler\PapyrusCompiler.exe` and the master ESM/BA2 files) and
`$mo2Mods` (the Mod Organizer 2 mods folder) at the top of the script. Adjust both before running
the full pipeline on your machine.

### 4. Tests

```powershell
# Offline suite: decision unit tests + data-pipeline golden snapshot (milliseconds, no game)
& ".\tools\test\run-all-tests.ps1"
```

The decision unit tests are a separate xmake target (`plugin/tests/SAQ_DecisionTests.cpp`) and can
also be run directly:

```powershell
cd plugin
xmake build SAQ_Tests
xmake run SAQ_Tests
```

### 5. Packaging

```powershell
# Nexus release zip: switches to the release build, verifies it, and packs dist\*.zip
& ".\tools\package-saq.ps1"

# Source snapshot zip (every git-tracked file)
& ".\tools\package-source.ps1"
```

## Notes

- The release build compiles the in-engine test harness out of the DLL
  (xmake option `saq_harness=n`, see `plugin/xmake.lua`). Development builds include it; whether it
  activates at runtime is controlled by `[Test] Harness` in the INI.
- Development notes, the data pipeline description and a list of known pitfalls live in `docs/`
  (Chinese), starting with `docs/00-项目总览与技术方案.md` and `docs/01-构建与环境.md`.

## Credits

- [SFSE](https://sfse.silverlock.org/) and [CommonLibSF](https://github.com/libxse/commonlibsf)
- [FFDec / JPEXS](https://github.com/jindrapetrik/jpexs-decompiler) for the SWF toolchain
- [xEdit](https://github.com/TES5Edit/TES5Edit) for ESM generation
- [Creation Hub Interface](https://github.com/Creation-Hub/Interface) (Starfield UI AS3 sources)

## License

GPL-3.0-or-later.
