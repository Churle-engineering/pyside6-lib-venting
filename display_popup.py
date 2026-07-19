# Shim to load the display_popup script (no .py extension) and expose its functions
import runpy
import os

_here = os.path.dirname(__file__)
_impl_path = os.path.join(_here, "display_popup")

# Execute the existing script as a module namespace
ns = runpy.run_path(_impl_path)

try:
    display_toxicity_result_popup = ns["display_toxicity_result_popup"]
    display_flammability_result_popup = ns["display_flammability_result_popup"]
except KeyError as e:
    raise ImportError("display_popup implementation does not define the expected functions") from e
