# Open-WebUI Plugin Protocol

A plugins folder in git, bundled into the single-file functions Open-WebUI stores and deployed to an instance.

## Language

### Code taken from git

**Sources**:
Everything one run reads from git for its plugins: the files each `source:` names, at pinned commits, each fetched once; also the commit a branch or tag points at, and which of the two a name is.
_Avoid_: remote, checkout

**Resolved plugin**:
A plugin folder with its `source:` applied: the folder that is bundled, its merged manifest, its files and the commits they were pinned to.
_Avoid_: upstream root, plugin root

### Bundling

**Build**:
A folder `owpp build` writes: each plugin's bundle and what the deploy needs besides the code, made by one owpp version, deployed elsewhere with `owpp deploy --from`. Generated, never committed.
_Avoid_: artifact, package, dist

**Library**:
Built-in code owpp links into a plugin's bundle, asked for with `include:` or turned on by what the plugin holds (a `static/` folder, a `config.yaml`). A plugin imports its names from `owpp.lib`.
_Avoid_: lib, mixin, include

**Flattening**:
What the bundler does to a plugin's files, written as ordinary Python: it inlines `shared.py` and the libraries above `function.py` (or `tool.py`) and removes the imports of them, so they become the one module Open-WebUI stores.
_Avoid_: concatenation, inlining

**Unbundling**:
What `owpp import` does to a function's code: owpp's libraries, the data they carry and the runtime come back out as `include:`, files and the tool and skills, and the Shared Assets Protocol's byte-identical blocks as `include:`, leaving the plugin's own code. Bundling the result gives the same function again.
_Avoid_: decompiling, extracting

**Library catalogue**:
The list of every library with what it pulls in, what turns it on and what data it carries.
_Avoid_: LIBS, library table

### Testing

**Test harness**:
What a plugin's unit tests run against: the real Open-WebUI's code in the test process, with a fresh database, a fake model and a record of what was sent.
_Avoid_: mock Open-WebUI, mock
