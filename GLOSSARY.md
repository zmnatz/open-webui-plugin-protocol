# Open-WebUI Plugin Protocol

A plugins folder in git, bundled into the single-file functions Open-WebUI stores and deployed to an instance.

## Language

### Code taken from git

**Sources**:
Everything one run reads from git for its plugins: the files each `source:` names, at pinned commits, each fetched once.
_Avoid_: remote, checkout

**Resolved plugin**:
A plugin folder with its `source:` applied: the folder that is bundled, its merged manifest, its files and the commits they were pinned to.
_Avoid_: upstream root, plugin root

### Bundling

**Build**:
A folder `owpp build` writes: each plugin's bundle and what the deploy needs besides the code, made by one owpp version, deployed elsewhere with `owpp deploy --from`. Generated, never committed.
_Avoid_: artifact, package, dist

**Library**:
Built-in code owpp links into a plugin's bundle, asked for with `include:` or turned on by what the plugin holds (a `static/` folder, a `config.yaml`).
_Avoid_: lib, mixin, include

**Library catalogue**:
The list of every library with what it pulls in, what turns it on and what data it carries.
_Avoid_: LIBS, library table
