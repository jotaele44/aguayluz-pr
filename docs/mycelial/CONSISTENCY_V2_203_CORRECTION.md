# Bounded timezone-resource correction 2.0.3

This corrects Z1 from review 5188155364 of head
`82396d41293413b734a128e21c61b9fe8d8fec8d`, following the user's affirmative
response. That reviewed revision and its four failed expectations are preserved.
Record schemas remain 2.0.0 with identical bytes and logical serialization.
No ingestion, field authorization, disclosure, model, application surface, ready
transition or merge is introduced. Existing historical-reference logic is unchanged.

## The boundary is bytes, not another exception list

Lookup validates the existing key constraints, follows configured system TZPATH
priority, and falls back to an unpacked local tzdata package only for absent files.
A malformed or inaccessible primary resource does not trigger a silent fallback.
A single file descriptor is opened read-only, with nonblocking/close-on-exec flags
where available. fstat must identify a regular file; size, byte count and descriptor
metadata are checked before/after its bounded read. The descriptor is always closed.

A maximum 1 MiB immutable byte buffer is retained for this call. The validator
checks the buffer and `ZoneInfo.from_file(BytesIO(buffer), key=key)` decodes that
same buffer. It does not reopen the path or reuse the constructor's mutable cache.
Replacing a path after validation cannot substitute different decoder bytes.
No original source record is changed and no byte/hash assertion is fabricated.

This is bounded local resource handling, not an independent timezone data authority
or integrity signature. TZPATH and installed packages remain trusted configuration.
Symlink aliases in those configured sources are supported. A failing kernel or
remote-mounted filesystem has no wall-clock deadline here; this patch introduces
no subprocess, polling service, cancellation worker, network client or scheduler.
Zip/custom import-resource backends are explicitly unsupported rather than invoking
an unbounded decompressor or arbitrary resource stream.

## Preflight scope and operational limits

Before decoding, both required TZif blocks must have complete 44-byte headers,
recognized consistent versions (1/2/3/4), bounded counts and complete counted arrays.
Checks cover strictly increasing transitions, transition-type indices, type flags,
NUL-terminated designations, bounded leap-record ordering/correction structure, and
standard/UT flags. Version 1 must end exactly after its data block. Versions 2+
require a complete footer with both newline delimiters, no embedded control bytes
or trailing material, and a bounded ASCII payload. The previously unterminated
footer is rejected before the dependency can enter its EOF loop.

Operational limits: 1 MiB/file; 16,384 transitions/block; 256 types/block;
4,096 designation bytes/block; 1,024 leap records/block; 256 footer bytes;
32 configured system roots; 64 read calls/file. Offset values must be representable
by datetime (strictly within +/-24 hours); designation indices above 127 and
nonprintable/non-ASCII designation encodings are excluded for decoder compatibility.
These are declared implementation constraints, not assertions that every excluded
resource violates RFC 9636. Leap semantics, every POSIX footer rule, historical
civil-time correctness and the full RFC are not certified by structural preflight.

Expected reader and decoder failures retain constant reason codes and all false
authority flags; no paths, keys or exception details are returned. Byte/resource
limits, changed snapshots, unsupported backends and invalid structure fail closed.
There is no UTC substitution. Defense-in-depth decoder exception handling is
secondary to preflight, which prevents malformed arrays and unterminated footers
from reaching an unbounded parse.

Primary references:
- https://www.rfc-editor.org/rfc/rfc9636.html (headers, counted blocks, footer, integrity)
- https://docs.python.org/3.13/library/zoneinfo.html (TZPATH, tzdata, from_file)

## Regression and certification scope

The earlier 225 cases retain their behavior. One expected implementation-version
literal changes to 2.0.3; three old fault-injection targets move from the removed
unchecked constructor to the new byte-reader boundary. Assertions are not weakened.
The 30 real-resource review cases are carried with the same behavior expectations;
loading/output paths use the repository and pytest temporary directories, and the
version assertion advances. Their simulated files remain temporary and isolated.

Seventy-five new cases test counted-array limits, corrupt indices/flags, versions,
footers, every prefix of a valid v2 fixture, valid controls, same-buffer decoding
after path replacement, changed/short reads, regular-file enforcement, read bounds,
source priority, missing resources, unsupported backends, decoder-fault simulation,
row conservation and non-admission. Tests are synthetic, not biological evidence.
Expected distinct suite size is 225 + 30 + 75 = 330; actual executed results are
recorded separately, not implied by this document.

The installed timezone sweep is separately bounded to its frozen key list and 24
sample instants per key. It is not extra pytest cases or universal/platform
certification. Full repository/conftest, Python 3.10/3.12, lint, security, coverage,
GUI and desktop obligations remain separate. No review is dismissed or approved.
The three earlier OPEN design questions are not settled by this resource patch.
