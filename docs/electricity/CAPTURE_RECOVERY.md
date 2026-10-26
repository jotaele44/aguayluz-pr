# Interrupted capture recovery — bounded follow-up

Parent candidate: `9740e7c1cf95efc437984680edff7f0ddc15725f`, PR #381.
That candidate and its original qualification evidence remain unchanged.

A synthetic interrupted-write reproduction showed that the parent implementation
could leave incomplete bytes directly under the final SHA-256 name. Integrity
checks correctly refused those bytes, but a subsequent acquisition of the same
source could not recover without operator intervention.

The follow-up writes a private staging file in the raw directory, checks the
write length, flushes and fsyncs the file, then publishes the completed content
using an exclusive hard link. Existing targets are verified and never replaced.
On POSIX, the raw directory is fsynced before a receipt is admitted. Filesystems
must support hard links; unsupported publication fails closed. This is not a
claim of hardware durability or a production backup certification.

Normal failure cleanup removes only the staging file created by that call.
Abrupt process death may leave a `.capture-*` staging file; it is not eligible as
a source blob and cannot enter a projection by its filename. Do not remove files
from a shared live store while writers are active. Pre-existing corrupt final
blobs remain preserved and refused; this change never silently repairs or
overwrites them.

Fault injection covers disk-full interruption, short write, flush failure and
file-fsync failure. Concurrent captures of identical source bytes must produce
one verified final blob and an idempotent receipt. A database failure after
publication must permit retry without rewriting the source blob. Existing
corruption must remain unchanged and unadmitted.

The native GUI retains a fail-closed projection error and retry path. The browser
test injects a 503 integrity error, checks that export is disabled, then retries
the real producer. No successful measurement payload is synthesized. Mobile
capture waits for the actual projection revision after reloading preferences.

There is no public API or schema change. Source acquisition permissions, source
quarantine, scientific verification, source access, independent scientific review,
consumer acceptance and all other open release gates remain unchanged. This
follow-up does not complete the Electricity Intelligence product.

One-line bounded validation (dependencies preinstalled):

`python3 -m pytest -q tests/test_electricity_capture_recovery.py tests/test_electricity.py`
