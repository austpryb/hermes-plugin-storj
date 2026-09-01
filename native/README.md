Drop the `libuplink` shared library for your platform here:

- Linux: `libuplink.so`
- macOS: `libuplink.dylib`
- Windows: `libuplink.dll`

Build it from https://github.com/storj/uplink-c with `make build`, or set
`STORJ_LIBUPLINK_PATH` to point somewhere else. Binaries are gitignored.
