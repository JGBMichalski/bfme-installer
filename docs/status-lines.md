# Status lines

`scripts/bfme-linux-setup.sh --machine <command>` (or `BFME_PROGRESS=1`) prints status lines alongside its normal output. Each starts with `@bfme ` and goes to stdout. Ignore every other line.

## Lines

| Line | Meaning |
| --- | --- |
| `@bfme STEP <id> start` | A step began. |
| `@bfme STEP <id> done` | The step finished. |
| `@bfme STEP <id> skip` | Nothing to do (already in place, or not applicable). |
| `@bfme PROGRESS <0-100>` | Progress of the current step. Steps of unknown size print none. |
| `@bfme CHECK <id> <ok\|warn\|fail> <message>` | One system check from `doctor`. |
| `@bfme FIX <check id> <command>` | Command that fixes a failed check. Show it with a Copy button. |
| `@bfme WARN <message>` | A non-fatal problem. |
| `@bfme ERROR <step\|-> <message>` | The command failed. The step is `-` if none was running. Last status line before a non-zero exit, except after `CANCELLED`. |
| `@bfme CANCELLED` | Stopped cleanly on request. Exit status 130. |
| `@bfme DONE` | The job finished: `install`, `prepare`, `launcher-install` or `aotr-install`. |
| `@bfme STATUS <key> <value>` | Printed by `status` and before every `DONE`. |

`STATUS` keys: `runner`; `prefix` (`ready` or `missing`); `launcher`, `arena` and `aotr` (`installed` or `missing`; `launcher` is the AIO Launcher and `aotr` is Age of the Ring); `bfme1`, `bfme2` and `rotwk` (`installed` when the game's program is present, else `missing`); `complete` (`yes` or `no`: the game environment is ready and holds at least one of `launcher`, `arena` and `aotr`).

## Jobs and steps

The wizard runs only the jobs the player chose, one after the other. Each job ends with `DONE` and can be rerun, skipping work already in place.

| Command | Steps | What it is for |
| --- | --- | --- |
| `prepare` | `doctor`, `runner`, `prefix` | Game environment only. |
| `launcher-install` | `launcher`, `arena`, `shortcuts` | The All-in-One Launcher and the Arena. Needs `prepare` first. |
| `aotr-install <zip>` | `aotr-check`, `aotr-unpack`, `aotr-install`, `aotr-settings` | Age of the Ring. Needs only `prepare`. |
| `install` | `prepare`, then `launcher-install` | The terminal setup. |
| `remove <program>` | none | Takes `launcher`, `arena` or `aotr` out of the game environment: its folder, its shortcut, and what an interrupted install of it left. Keeps the games, the other programs and the settings a program keeps in the player's own folder. Ends the Wine session first and refuses while a setup runs. Prints `STATUS` lines, then `DONE`. |

The wizard adds `aotr-download` before Age of the Ring's steps, where the player gets the file from ModDB. The script never prints it.

| Id | What it does |
| --- | --- |
| `doctor` | System checks (prints `CHECK` and `FIX`). |
| `runner` | Downloads and verifies umu and Proton (`PROGRESS` lines). |
| `prefix` | Creates the prefix and applies its settings. |
| `launcher` | Downloads and installs the All-in-One Launcher. `skip` if already installed. |
| `arena` | Downloads or updates the Online Arena. |
| `shortcuts` | Writes missing menu shortcuts and removes those of programs not installed. A shortcut that cannot be written is a warning. |

`aotr-install <zip>` runs these steps:

| Id | What it does |
| --- | --- |
| `aotr-check` | Checks the zip (name, every part present) and free space. |
| `aotr-unpack` | Unpacks the zip into the downloads folder, with `PROGRESS`. Not repeated on a rerun. |
| `aotr-install` | Runs the Age of the Ring installer without its window. `PROGRESS` tracks how far it has read its data files, capped at 99 until it ends. None if that cannot be seen. |
| `aotr-settings` | Deletes the unpacked files. |

## Check ids

`cpu`, `cmd-curl`, `cmd-tar`, `cmd-python3`, `cmd-bwrap`, `cmd-wine`, `cmd-cabextract`, `bwrap`, `wine-version`, `i386-arch`, `vulkan64`, `vulkan32`, `disk`, `firewall`, `flatpak` and `flatpak-32bit`. The Flatpak build prints only those that apply.

## Running and stopping

- A failed `doctor` prints its `CHECK` and `FIX` lines, then `ERROR doctor ...`, and exits 1. Run `--machine doctor` to check again.
- `SIGUSR1` stops cleanly: the script finishes the running step, prints `CANCELLED` and exits 130. Rerunning carries on from there.
- Any other signal (such as `SIGTERM`) stops at once. Partial downloads resume.

## Example

```
$ bfme-linux-setup.sh --machine install
@bfme STEP doctor start
@bfme CHECK cpu ok x86_64 processor
@bfme CHECK flatpak-32bit fail the 32-bit Flatpak extensions are not installed
@bfme FIX flatpak-32bit flatpak install --user flathub org.freedesktop.Platform.Compat.i386//25.08 org.freedesktop.Platform.GL32.default//25.08
@bfme ERROR doctor Fix the problems above, then run install again.
```
