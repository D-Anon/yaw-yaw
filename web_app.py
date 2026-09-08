"""Browser launcher using the same paths and speech engine as the desktop."""
import sys
from phase14_bootstrap import configure

if __name__ == "__main__":
    offline = "--offline" in sys.argv
    configure(offline=offline)
    if offline:
        sys.argv.remove("--offline")
    from kokoro_tts_local.gradio_interface import main
    main()
