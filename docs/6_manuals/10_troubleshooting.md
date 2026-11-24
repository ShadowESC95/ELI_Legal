# Troubleshooting

`eli-legal doctor` is the first thing to run. It checks the installation and says what is wrong.

## Starting and signing in

| What you see | Why | What to do |
|---|---|---|
| "audit key missing" | First run, or the key was moved | First run: `eli-legal init`. Otherwise restore `secrets/audit_hmac.key` from backup. Do not create a new key over an existing ledger |
| "audit key permissions must not permit group/other access" | The key file is readable by others | `chmod 600 secrets/audit_hmac.key` |
| "unknown user or wrong passphrase" | As it says, or the account has no passphrase yet | An administrator sets the first passphrase |
| "too many failed attempts; this account is locked" | Five wrong attempts | Wait fifteen minutes, or ask an administrator to unlock |
| "enter the code from your authenticator app" | You have a second factor | Enter the six digits |
| "that code is not correct, or has already been used" | Wrong code, a code used twice, or the phone's clock is wrong | Wait for the next code; set the phone's time to automatic |
| "this session belongs to X; it cannot act as Y" | A command was run for a different user than the one signed in | `eli-legal login <you>` |
| "to …, confirm your passphrase" | The action is a decision | Give your passphrase when asked |
| The desktop application does not open on Linux | Missing graphics libraries | Ubuntu, Debian: `sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libxcb-cursor0`; Fedora: `sudo dnf install mesa-libEGL mesa-libGL libxkbcommon fontconfig dbus-libs xcb-util-cursor`; Arch: `sudo pacman -S --needed libglvnd libxkbcommon fontconfig dbus xcb-util-cursor` |
| The AppImage says it cannot mount, or "fuse: device not found" (Arch and others) | FUSE 2 is not installed | Arch: `sudo pacman -S fuse2`; Fedora: `sudo dnf install fuse`; Ubuntu 24.04: `sudo apt install libfuse2t64`; or add `--appimage-extract-and-run` as the first argument |
| `eli-legal: command not found` | The program is not on your `PATH`, or you used the AppImage or macOS app | Use the full name: the AppImage file (`./ELI_Legal-<v>-linux-x86_64.AppImage <command>`), `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal"` on macOS, *ELI Legal command line* on Windows; after the `.run` installer add `~/.local/bin` to `PATH`. See [Using the command line](14_command_line_guide.md) |
| Windows says "Windows protected your PC" | The build is unsigned | Check the file against `SHA256SUMS`, then *More info*, *Run anyway* |
| macOS says the application "cannot be opened" | The build is unsigned | Right-click it in Applications, *Open*; or `xattr -dr com.apple.quarantine "/Applications/ELI Legal.app"` |
| It asks for a licence key | An installed copy needs one | Paste an ELI Legal key, or an ELI v3 key that includes it; or `eli-legal licence activate <key>` |
| "the database key (…) is missing, and … cannot be opened without it", or "… could not be opened with its key" | `secrets/database.key` is missing or wrong (a restore without `secrets/`, another Windows account) | Put back the key saved with `eli-legal database-key --out`, as `secrets/database.key`. Without it the databases cannot be opened |
| "the program does not run on this system" from the installer | The build needs a newer system library than this machine has | Use a build made for an older system, or install from source |

## The model and the graphics card

Settings, Model shows the machine, the llama.cpp in use and how the selected model would be placed.
`eli-legal gpu status` and `eli-legal model plan <file>` print the same.

| What you see | Why | What to do |
|---|---|---|
| Chat says "model: none — answers are the sources themselves" | No model is chosen | Settings, Model, choose one and Apply |
| "no GGUF model file at (none)" when applying a model (0.5.0) | The verifier box was read as a file name | Fixed in 0.6.0 |
| Chat says "The model did not return a usable answer (… 'str object' has no attribute 'text')" (0.6.0) | The model's own chat template reads a message as a list of parts and failed on plain text (Mistral Small 3.1 among them) | Fixed in 0.6.1: the conversation is given in the form the template takes, and the model's report says which |
| "…'s own chat template accepts a system message and a question in none of the forms tried" | The file's chat template is broken | Use another build of the model; the error names what the template raised |
| "the desktop application cannot start. This system has no libEGL.so.1 …" | A system library Qt needs is missing (a server or minimal system) | Run the command the message gives; the command line and the server work without it |
| Lines such as "undefined symbol: g_task_set_static_name … Failed to load module" or "Loading IM context type 'ibus' failed" in the terminal (0.6.0, Linux) | The installer carried GTK from its build machine, which loaded this system's newer plug-ins | Fixed in 0.6.1: the Linux builds carry no GTK; file dialogs are the desktop's own |
| "TypeError: 'NoneType' object is not callable" from `Llama.__del__` when closing (0.6.0) | The model was closed after Python had begun shutting down | Fixed in 0.6.1 |
| "… is present, but the llama.cpp in use has no graphics support" | No graphics pack passed on this card, so the model runs on the processor | See the note under it for why each pack was not used; install one from a file, or install the graphics driver |
| "… did not start on this card" | The pack's own test failed. The note gives the system's reason: a system older than the packs are built for ("version `GLIBC_2.38' not found"), a driver that is missing or too old, or (Vulkan) no loader | A system as new as Ubuntu 24.04; update the graphics driver; on Linux install `libvulkan1` and the card's Vulkan driver |
| "… is not the version built into this copy" | An installed copy can only use a pack of its own llama.cpp version | Install the pack of that version from a file |
| Fewer layers on the card than the model has | That is what fits the graphics memory free now with the context the work needs | Close what else is using the card (it is named); or choose a smaller model or quantisation |
| "other programs are using the card's memory: …" | Another program holds graphics memory | Close it, or have it release the model it keeps loaded |
| "context reduced from … to … tokens" | The memory free now cannot hold more | As above. Steps then fit less material and say what they left out |
| "The model's context holds N of the M sources" | The sources for that question are longer than the model's context | The passages not drawn on are named and still shown; a larger context needs more free memory |
| "…'s reply was cut off after N tokens" | The model ran out of context or tokens mid-answer | The answer is not used. Ask a narrower question, or free memory for a larger context |
| "this step's material does not fit the context ELI v3's model is loaded with" | Opened from ELI v3, whose model has a short context | Load the model in ELI v3 with a longer context |
| "… could not be loaded: this llama.cpp does not support its architecture" | The model file is newer than the llama.cpp in use | Use a model this llama.cpp reads; or a newer ELI Legal |
| The first answer takes much longer than later ones | The model loads at its first use | Expected: once, per start |

## Working on a matter

Refusals are shown in the system's own words. The commonest:

| What you see | Why | What to do |
|---|---|---|
| "user … is not permitted to perform …" | Your role does not include that action | Ask someone whose role does; or an administrator to review roles |
| A matter is missing from your list, or opening it is refused | You were not added to it | Someone already on the matter adds you |
| You cannot be added to a matter | Your role does not fit the matter's profile | A party's lawyer joins a tribunal's matter only as one party's representative: the lead adds them with *Grant access…*, naming the party they act for |
| "matter … is closed" | The matter was closed | Closed matters cannot be worked on |
| "no document has been ingested into this matter" | Nothing was filed | File the documents first |
| "no named human with a reviewing role for this profile is assigned to the matter" | The matter has no reviewer | Case details, Name the reviewers… |
| The first step is held for an unapproved source | The matter has no approved source, or its source was revoked | Case details, Choose sources…; Legal sources, Approve |
| The report warns that a jurisdiction pack is unvalidated | No qualified lawyer has signed the pack off | Expected until one does. It is a stated limit you must acknowledge |
| A document is "unsupported" or "failed" | A scan, an image, a damaged or encrypted file | Review and approve, Holds: double-click the hold, look at the original, then describe it by hand, file a readable copy, or accept the gap |
| "image file that could not be opened: it is damaged, or not the kind of file its name says" | The file is not a readable image (cut short, or another kind of file renamed) | Ask the party who filed it for a readable copy, or accept the gap. OCR is not the cause |
| "image with no writing OCR could read" | A photograph or drawing, or text too faint | Look at it in the hold window and describe it by hand |
| Every authority is held with "status last confirmed … older than the …-day limit" | The source's status data is stale | Refresh the corpus; or verify each by hand |
| Every citation in one form is held as not found | The source is recorded as complete for a form it does not fully cover, or the pack does not recognise the form | Correct the source record; check the jurisdiction pack |
| No arguments in the report | No model is set, or the issue was only proposed by the model | Set a model; confirm the issue |
| "… hold(s) are open" | You tried to approve while holds remain | Close each hold |
| "run is …; only a run awaiting review can be approved" | The run was not restarted after the holds were closed | Progress, Restart… |
| Approve, Return and Reject are greyed out; "You ran this work, so another named reviewer decides it" | Nobody approves a run they started | The box *Who can decide this* names who can: **Switch person…** and let them sign in on this machine, or they decide in the browser. If nobody else can, **Name another reviewer…** |
| "the law and standards package … has changed or been removed since this run was prepared" | A package the run was prepared under was updated, removed or replaced | Restart the run from its first step (Progress, Restart…, the first step) or start a new run; restarting from a later step keeps the old package and fails again |
| Start a run and Restart are greyed out on Progress | A run is still working in this application (a model step can take minutes) | Wait for it, or Stop it; the step map shows which step is running |
| **Next: State the issues** stays in the stage bar | The case has no issues stated | Press it: Case details, Edit details… opens at the issues; one per line |
| "run is …; only a held or stopped run can restart" | The run is in another state | Start a new run |
| "these limits must be acknowledged before approval" | A stated limit was not ticked | Tick each one |
| "the findings changed after the draft was built" or "the report hash given does not match the current report" | The report you read is no longer the current one | Restart the run and read the new version |
| A recipient is shown as not entitled | They are not a party to, or a member of, the matter | Only entitled recipients can receive a release |

## The server and browser

| What you see | Why | What to do |
|---|---|---|
| "refusing to listen beyond this machine without TLS" | `--lan` with no certificate | Add `--tls-cert` and `--tls-key`, or `--self-signed` |
| "no users exist yet" | First run | `eli-legal init --admin <id>` |
| Browser warns about the certificate | Self-signed | Compare fingerprints, then accept; or install a proper certificate |
| "this server does not answer to that host name" | You used a name the server was not told about | Start it with `--allowed-host <that name>` |
| "set up your second factor before going any further" | The server requires one | Follow the prompt |
| "requests from another origin are refused" | A request came from a different site, or a proxy rewrote `Host` | Open the server's own address; make the proxy forward `Host` unchanged |
| "the X-ELI-CSRF header is missing or wrong" | A program used a browser session without the value | Programs should use a token, not a cookie |
| "too many requests" | Rate limit | Wait the number of seconds given |
| "the body is larger than …" | A file over the limit | Raise `ELI_LEGAL_SERVER_MAX_UPLOAD_MB`, or split the file |
| Signed out unexpectedly | Thirty idle minutes, or your passphrase or second factor was changed | Sign in again |
| A blank page | JavaScript is off, or a browser extension blocked the script | Allow scripts from the server's own address |
| The browser shows different cases, events or accounts from the desktop application (for example "You have no matters yet", or only a `judge` account) | The server was started on other data: a developer's source checkout, the demo, or another `ELI_LEGAL_HOME` | Stop it. Start it from the desktop application (Settings → System → Server) or with the installed program's `serve`. The server prints the data folder it serves, and the browser shows it after signing in |
| "refused: this is a developer checkout of ELI Legal: it would serve the test data in …, not your installed ELI Legal's data in …" | `eli-legal serve` was run from a source checkout while an installed copy's data exists | Use the installed program; `--dev-data` only if you really mean the checkout's test data |
| Other machines cannot reach the server | It listens on this machine only, or a firewall blocks the port | Start it for the network with TLS (`--lan`), give them the address it prints, and allow port 8443 through the firewall |

## The audit trail

| What you see | Why | What to do |
|---|---|---|
| "AUDIT CHAIN INVALID" | The ledger was altered, truncated, or restored without its anchor | **Stop.** Preserve both databases and the key as they are. Follow the [Operations runbook](09_operations_runbook.md) |
| Verifying against a checkpoint fails | The ledger is older than the checkpoint: a restore from an old backup | Find out why before continuing |
| "Gaps" in a run's record | The store and the ledger disagree about what happened | Treat as an incident |

## Getting more information

- `eli-legal doctor` and `eli-legal governance`.
- `eli-legal audit tail <matter> -n 50` shows the last events for a matter, including refusals
  and their reasons.
- `ELI_LEGAL_LOG_LEVEL=DEBUG` for more detail on the console. Logs never contain document text.
