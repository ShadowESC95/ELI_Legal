# Using the command line

ELI Legal's command line does everything the desktop application does, and some administration
the desktop does not: starting the server as a service, saving the database key, scripted work.
It is the same program as the server, and it uses the same data folder as the desktop
application, so all three see the same cases.

This guide shows how to open a terminal on each system, how to call the program for each way of
installing it, and the commands most people need. Every command and option is listed in the
[command-line reference](07_command_line_reference.md), and `<command> --help` explains any one.

## 1. Open a terminal and find the program

| Installed with | Open a terminal | The program is |
|---|---|---|
| Windows setup | Start menu → **ELI Legal command line** (a Command Prompt in the program's folder). With *Add to PATH* ticked at install, any Command Prompt or PowerShell | `eli-legal` |
| macOS `.dmg` | Applications → Utilities → **Terminal** | `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal"` |
| Ubuntu or Debian `.deb` | **Terminal** (Ctrl+Alt+T on Ubuntu) | `eli-legal` |
| Linux `.run` installer | Terminal | `eli-legal` (in `~/.local/bin`) |
| Linux AppImage (also Arch) | Terminal, then `cd` to the folder holding the file | `./ELI_Legal-0.8.19-linux-x86_64.AppImage` |
| Linux archive (`.tar.gz`) | Terminal, in the folder you unpacked | `./eli-legal/eli-legal` |

In the rest of this guide the program is written `eli-legal`. On macOS, or with the AppImage, type
the name from the table instead, or make a short name for it once:

```
# macOS (zsh): add to ~/.zshrc, then open a new Terminal
alias eli-legal='"/Applications/ELI Legal.app/Contents/MacOS/eli-legal"'

# AppImage (bash): add to ~/.bashrc, then open a new terminal
alias eli-legal="$HOME/Downloads/ELI_Legal-0.8.19-linux-x86_64.AppImage"
```

`eli-legal` typed in a developer's source checkout (with its `.venv` active) is a different
thing: it works on that checkout's own test data in `./data`, not your installed copy's. Use the
installed program above for your real cases.

## 2. First steps

```
eli-legal --help                    # every command, one line each
eli-legal doctor                    # is this installation sound? says what is wrong, in plain words
eli-legal licence                   # is this copy licensed? (licence activate <key> to add one)
eli-legal init --admin <your-id>    # first time only, if the desktop app has not done it
```

`init` creates the keys and the first administrator, and asks how long each kind of record is
kept. Unattended, give the periods: `--audit-days N --closed-matter-days N` and, if you want,
`--analysis-days`, `--reports-days`, `--evidence-days`, `--record-days`, `--inactive-matter-days`.

## 3. Signing in

Most commands act as a signed-in person, and every action is recorded under that name.

```
eli-legal login <user>              # asks for the passphrase (and a code, with a second factor)
eli-legal whoami
eli-legal logout
```

A session expires. A decision (resolving a hold, approving a report, releasing it) asks for your
passphrase again. In scripts, `--passphrase-stdin` reads it from standard input.

## 4. The server

```
eli-legal serve                                  # this machine only: http://localhost:8443/
eli-legal serve --lan --self-signed              # other machines too, over HTTPS (TLS required)
eli-legal serve --lan --tls-cert server.crt --tls-key server.key --allowed-host legal.example
eli-legal serve --port 9443                      # another port
```

It prints the data folder it is serving, the address to give everyone, the certificate's
fingerprint, and whether a second factor is required. Stop it with Ctrl+C. Run it on the machine
that holds the cases, with the installed program, so that the desktop application and every
browser share the same live data. See [Web application and server](06_web_application_and_server.md).

## 5. People

```
eli-legal user add j.murphy --name "Judge Murphy" --role judge
eli-legal passphrase j.murphy        # an administrator sets the first passphrase
eli-legal unlock j.murphy            # after five wrong attempts
eli-legal user deactivate j.murphy   # someone who has left
```

## 6. A case

```
M=$(eli-legal matter create --name "A v B" --purpose "Bench memorandum" --jurisdiction IE \
      --profile adjudicator --party "A Ltd:claimant" --party "B Ltd:respondent" \
      --issue "Whether time was of the essence" --relevant-date 2023-04-28)
eli-legal matter reviewers $M j.murphy
eli-legal matter sources $M my-corpus
eli-legal matter set $M --issue "Whether the notice of 28 April was valid"   # add an issue later
eli-legal ingest $M ./bundle --party "A Ltd"        # a file, or a whole folder
eli-legal status $M                                 # where it stands and what to do next
eli-legal run start $M
eli-legal holds $M <run>                            # what is held, and why
eli-legal hold $M <hold> --action waive --reason "Checked the original; nothing missing."
eli-legal run resume $M <run> --reason "Holds dealt with."
eli-legal review $M <run> --decision approve --reasons "..." --acknowledge-all
```

On Windows Command Prompt, set a value with `set M=mat_...` and use `%M%`; in PowerShell,
`$M = "mat_..."`. Nobody approves a run they started: another named reviewer runs `review`.

## 7. Keys, backups and the record

```
eli-legal database-key --out eli-legal-database-key.txt   # save the databases' key, off the machine
eli-legal audit verify                                    # does the audit chain verify?
eli-legal audit checkpoint --out checkpoint.json          # a signed note of where the ledger stands
eli-legal evidence $M <run>                               # an evidence pack, readable, in this folder
eli-legal evidence $M <run> --out D:\handover             # or in a folder you choose
```

Keep the key file in a password manager or a safe, apart from your backups of `data/`; anyone with
it and the data can read every case.

## 8. Retention and the routine checks

```
eli-legal compliance retention --audit-days 2190 --closed-days 2190 \
    --evidence-days 3650 --record-days 3650 --inactive-days 365
eli-legal checks run                 # run the routine checks now
eli-legal checks show                # what they found
eli-legal checks timer --install     # run them daily from the system's scheduler
```

`--closed-days` is how long a closed case's papers are kept; its analysis and reports follow the
papers unless `--analysis-days` or `--reports-days` say otherwise, and the decision record must be
kept at least as long as anything it accounts for.

## 9. When something goes wrong

- `eli-legal doctor` first.
- `eli-legal audit tail <matter> -n 50` shows the last events on a case, refusals included, with
  their reasons.
- "command not found": the program is not on your `PATH`. Use the full name from section 1, or
  (Linux `.run`) add `~/.local/bin` to your `PATH`.
- More in [Troubleshooting](10_troubleshooting.md).
