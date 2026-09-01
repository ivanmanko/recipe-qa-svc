import threading

# Concurrent torch model construction/inference across threads (as happens
# under asyncio.to_thread with several in-flight requests) can deadlock; a
# single process-wide lock serializes all local-model CPU work. For a
# ~50-document corpus the throughput cost is negligible next to the
# reliability win.
TORCH_INFERENCE_LOCK = threading.Lock()
