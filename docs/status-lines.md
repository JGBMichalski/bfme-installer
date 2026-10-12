# Status lines

`scripts/bfme-linux-setup.sh --machine <command>` (or `BFME_PROGRESS=1`) prints status lines for a program to read, such as the setup wizard. The normal text output is unchanged and is still printed, so a program can show it as a log.

Each status line is one line, starts with `@bfme `, and goes to stdout. Ignore every other line.

## Lines

| Line | Meaning |
| --- | --- |
| `@bfme STEP <id> start` | A step began. |
| `@bfme STEP <id> done` | The step finished. |
| `@bfme STEP <id> skip` | The step was not needed (already in place, or not applicable). |
| `@bfme PROGRESS <0-100>` | Download progress for the current step. A step that prints none is working with no known size. |
| `@bfme CHECK <id> <ok\|warn\|fail> <message>` | One system check from `doctor`. |
| `@bfme FIX <check id> <command>` | A command that fixes a failed check. Only the user's system can run it. Show it with a Copy button. |
| `@bfme WARN <message>` | A non-fatal problem. |
| `@bfme ERROR <step\|-> <message>` | The command failed. The step is `-` if no step was running. Always the last status line before a non-zero exit, except after `CANCELLED`. |
| `@bfme CANCELLED` | The install stopped cleanly because it was asked to. Exit status 130. |
| `@bfme DONE` | `install` finished. |
| `@bfme STATUS <key> <value>` | Printed by `status`. Keys: `runner`, `prefix` (`ready` or `missing`), `launcher`, `arena` and `aotr` (`installed` or `missing`; `aotr` is Age of the Ring), `bfme1`, `bfme2` and `rotwk` (`installed` when the game's program is there, else `missing`), `complete` (`yes` or `no`). |

## Steps

`install` runs these steps in order:

| Id | What it does |
| --- | --- |
| `doctor` | System checks (`CHECK` and `FIX` lines come from here). |
| `runner` | Downloads and verifies umu and Proton (`PROGRESS` lines). |
| `prefix` | Creates the prefix and applies its settings. |
| `launcher` | Downloads and installs the All-in-One Launcher. `skip` if already installed. |
| `arena` | Downloads or updates the Online Arena. |
| `shortcuts` | Writes the menu shortcuts. `skip` inside the Flatpak, which provides its own. |

`aotr-install <zip>` installs Age of the Ring (optional, after the setup is complete) and runs these steps:

| Id | What it does |
| --- | --- |
| `aotr-check` | Checks the zip the player downloaded (name, complete, every part present) and the free space. |
| `aotr-unpack` | Unpacks the zip into the downloads folder (`PROGRESS` lines, from how much has been written). Skipped work is not repeated on a second run. |
| `aotr-install` | Runs the Age of the Ring installer without its own window. `PROGRESS` lines come from how far the installer has read into its data files (capped at 99 until it ends). No `PROGRESS` lines when the installer cannot be seen, and the reader shows "working". |
| `aotr-settings` | Deletes the unpacked files. |

## Check ids

`cpu`, `cmd-curl`, `cmd-tar`, `cmd-python3`, `cmd-bwrap`, `cmd-wine`, `cmd-cabextract`, `bwrap`, `wine-version`, `i386-arch`, `vulkan64`, `vulkan32`, `disk`, `firewall`, `flatpak` and `flatpak-32bit`. The Flatpak build only prints the ones that apply there.

## Running and stopping

- A failed `doctor` inside `install` prints its `CHECK` and `FIX` lines, then `ERROR doctor ...`, and exits 1.
- To check again after the user ran a `FIX`, run `--machine doctor`.
- To stop an install cleanly, send the script `SIGUSR1`. It finishes the step that is running, prints `CANCELLED` and exits 130 before the next one. A later `install` carries on where it stopped, because every step can run again.
- Any other termination (for example `SIGTERM`) stops the script at once. Partial downloads resume.

## Example

```
$ bfme-linux-setup.sh --machine install
@bfme STEP doctor start
@bfme CHECK cpu ok x86_64 processor
@bfme CHECK flatpak-32bit fail the 32-bit Flatpak extensions are not installed
@bfme FIX flatpak-32bit flatpak install --user flathub org.freedesktop.Platform.Compat.i386//25.08 org.freedesktop.Platform.GL32.default//25.08
@bfme ERROR doctor Fix the problems above, then run install again.
```
