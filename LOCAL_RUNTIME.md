This fork retains the MIT upstream license in `license.txt`. Its origin is
`Reese-max/travel-planning-app`; upstream is `https://github.com/itskovacs/trip.git`.

Run an isolated build and real HTTP smoke test with Docker Compose v2:

```sh
python scripts/check_runtime.py --out runtime-evidence/local.json
```

The command builds this checkout (Angular frontend and Python backend), starts
a random local Compose project with a disposable named volume, checks health
and the HTTP home page, creates a temporary local user and a test Trip, reads
and deletes that Trip, then removes the project's containers and volume.
It does not connect to an existing deployment, provider, or real account.
The receipt lists PASS, FAIL, and NOT_RUN per stage; a failed build never
counts as verified runtime. Use a fresh receipt path on each attempt.

BuildKit's optional CA secret mounts support the managed environment's proxy
without disabling TLS verification or putting certificates in image layers.
`CODEX_PROXY_CERT` selects the public Node trust certificate if provided;
the system CA bundle is mounted for pip. Registry and proxy configuration
are preserved. With no custom proxy, normal public CA trust applies.

No AI planning write surface is added. Import, proposal approval, diff UI,
and writeback remain separate phases tracked in
`Reese-max/travel-planning-mcp#7`.
