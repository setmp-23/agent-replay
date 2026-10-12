# agent-replay

Save a command-line agent run once. Come back later and see exactly what it printed, what changed in the working tree, and whether a fresh run still behaves the same.

`agent-replay` is a small local CLI. It works with any command that can run without an interactive terminal, so you can use the agent you already have installed. Recordings stay in the current project; nothing is uploaded.

## Install

Requires Python 3.10 or newer.

```bash
python -m pip install .
```

## Record a run

Put `--` between agent-replay's options and the command you want to run:

```bash
agent-replay record --label "fix the parser" -- python -c "print('hello from the agent')"
```

Add a project-specific mask when your agent prints a value the built-in rules do not know about:

```bash
agent-replay record --redact-regex "internal-[A-Z0-9]{12}" -- my-agent --prompt "check the build"
```

You can pass `--redact-regex` more than once. Matches are replaced in saved command arguments and output.

Use your agent's non-interactive mode where available. For example, pass its usual prompt or task flag after the separator. The command runs once; its output and exit code are saved even if it exits with an error.

## Find and inspect runs

```bash
agent-replay list
agent-replay show 8f31a2c0
agent-replay replay 8f31a2c0
```

`replay` prints the saved stdout and stderr. It does not start the agent again.

## Compare a fresh run

```bash
agent-replay compare 8f31a2c0
```

The command asks before it runs the saved command again. In automation, make that choice explicit with `--yes`:

```bash
agent-replay compare 8f31a2c0 --yes
```

The comparison checks stdout, stderr, and the exit code. It deliberately ignores elapsed time, since that varies between runs.

## What a recording contains

Each JSON file stores the command, label, start time, duration, exit code, output, the current Git commit when available, and the paths Git reports as changed when the recording is saved. Files live under `.agent-replay/runs/` in the directory where you ran the command. That directory is ignored by the included `.gitignore`.

Common GitHub, AWS, bearer, and key-value style secrets are masked in the saved command and output. Redaction is a guardrail, not a guarantee: inspect a recording before sharing it. After the process exits, its captured output is printed back to your terminal.

## Limits

- Commands run with captured output, so they must not require interactive terminal input.
- `replay` reprints a transcript; it does not recreate filesystem or network side effects.
- `compare` really runs the saved command again. Review it before confirming, especially if it can write files, call services, or spend money.
- Agent-specific tool calls and hidden reasoning are not captured. Only the wrapped process output and basic run metadata are recorded.

## License

MIT. See [LICENSE](LICENSE).
