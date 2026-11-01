#!/usr/bin/env bash
set -euo pipefail

# rTorrent 0.16 sizes its socket and open-file budget from the soft descriptor
# limit, and .rtorrent.rc asks for a 3072 budget, so lift the usual 1024.
want=8192
hard="$(ulimit -Hn)"
if [[ "$hard" == unlimited ]] || ((hard >= want)); then
    ulimit -Sn "$want"
else
    ulimit -Sn "$hard"
fi
# A crash must not write a multi-hundred-megabyte core into the download folder.
ulimit -Sc 0

exec /usr/local/bin/rtorrent "$@"
